"""Build the SoledadWX barograph: model, materials, lights, render, export.

The whole instrument is generated from this script, so the .blend is a build
product and this file is the source. Authored in millimetres, +X right,
+Y back, +Z up; the front of the case faces -Y.

Run (PowerShell or Bash):
  E:\\Graphics\\Blender\\blender.exe --background --factory-startup \
      --python build_barograph.py -- --render ..\\renders\\hero.png

Options after `--`:
  --render PATH     Cycles still
  --export PATH     .glb for the web page (geometry, UVs, names, hierarchy)
  --bake DIR        bake the lighting for the web page into DIR:
                    light.png (diffuse light, second UV set), ao.png, table.png
  --save PATH       .blend to open in Blender
  --wood NAME       rosewood (default) or oak
  --view NAME       hero (default) or front
  --samples N       Cycles samples (default 256)
  --res WxH         default 1920x1080
  --pressure P      inHg shown by pen and needle (default: where the placeholder trace ends)
  --wood-scale K    shrink the veneer figure to suit a small case (default 0.5)
  --env-rot DEG     turn the studio lighting about the vertical

Names the web page relies on: Drum, ChartPaper, PenArm, Needle, Dial.
"""
import argparse
import math
import os
import sys

import bmesh
import bpy
from mathutils import Euler, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.normpath(os.path.join(HERE, "..", "assets"))
TEX = os.path.join(HERE, "tex")
S = 0.001                              # millimetres to Blender metres
LIGHT_SCALE = 2.5                      # light.png stores light / LIGHT_SCALE (scene.ts must agree)
TABLE_HALF = 1600.0                    # the table is a square this far each way

# ---- Dimensions (mm) -------------------------------------------------------
LIP_HX, LIP_HY = 197.5, 127.0          # widest moulding of the base, half extents
FOOT_H, FOOT_T, FOOT_L = 14.0, 14.0, 62.0
TIER_INSET = 9.0                       # drawer tier, set in from the lip
DECK_Z = 91.0                          # top of the base; the hood stands here
HOOD_HX, HOOD_HY = 155.0, 84.5
POST = 15.0
HOOD_H = 165.0
HOOD_Z1 = DECK_Z + HOOD_H
PLATE_TOP = 112.0                      # brass bed plate

DRUM_X, DRUM_Y, DRUM_R = -78.0, 5.0, 46.5
PAPER_R = DRUM_R + 0.1
PAPER_Z0, PAPER_H = 124.5, 97.0
CHART_TOP_MARGIN, CHART_GRID = 5.0, 90.0          # as in make_textures.py
CHART_MID_Z = PAPER_Z0 + PAPER_H - CHART_TOP_MARGIN - CHART_GRID / 2.0
CHART_NOW_HOURS = 82.0                 # where the placeholder trace ends

PEN_ARM = 173.0                        # as in make_textures.py
PIVOT = (DRUM_X + PEN_ARM, DRUM_Y - PAPER_R - 3.4, CHART_MID_Z)

DIAL_C = (48.0, -62.0, 176.0)
DIAL_R, DIAL_HOLE = 54.0, 27.0
DIAL_DEG_PER_INHG = 66.0               # as in make_textures.py
STACK_XY = (2.0, 12.0)


# ---- Arguments -------------------------------------------------------------
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--render")
    p.add_argument("--export")
    p.add_argument("--save")
    p.add_argument("--bake")
    p.add_argument("--bake-size", type=int, default=2048)
    p.add_argument("--bake-samples", type=int, default=384)
    p.add_argument("--wood", default="rosewood", choices=["rosewood", "oak"])
    p.add_argument("--view", default="hero", choices=["hero", "front"])
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--res", default="1920x1080")
    p.add_argument("--pressure", type=float, default=29.777)
    p.add_argument("--wood-scale", type=float, default=0.5)
    p.add_argument("--wood-gain", type=float, default=1.25)
    p.add_argument("--env-rot", type=float, default=0.0)
    p.add_argument("--env-gloss", type=float, default=1.0)
    p.add_argument("--env", default=os.path.join(TEX, "studio_env.hdr"))
    p.add_argument("--env-diffuse", type=float, default=1.0)
    p.add_argument("--key", type=float, default=0.0)
    p.add_argument("--exposure", type=float, default=0.5)
    return p.parse_args(argv)


ARGS = parse_args()


# ---- Materials -------------------------------------------------------------
def new_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat, nt, bsdf, out


def set_inputs(bsdf, **vals):
    for key, val in vals.items():
        bsdf.inputs[key.replace("_", " ")].default_value = val


def image_node(nt, path, non_color=False):
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(path, check_existing=True)
    if non_color:
        node.image.colorspace_settings.name = "Non-Color"
    return node


def rgba(r, g, b):
    return (r, g, b, 1.0)


WOODS = {
    # name: (file stem, resolution tag, physical size of the scan in metres)
    "rosewood": ("rosewood_veneer1", "8k", 2.43),
    "oak": ("oak_veneer_01", "2k", 1.83),
}
WOOD_STEM, WOOD_RES, WOOD_M = WOODS[ARGS.wood]
WOOD_M *= ARGS.wood_scale


def make_wood(name, darken=1.0):
    """Lacquered wood: scanned colour and normal under a clear coat.

    The lacquer is the only surface that mirrors anything, so the wood itself
    has no specular of its own. That is also what a live renderer does well.
    """
    mat, nt, bsdf, _ = new_material(name)
    diff = image_node(nt, os.path.join(ASSETS, f"{WOOD_STEM}_diff_{WOOD_RES}.jpg"))
    if darken != 1.0:
        mul = nt.nodes.new("ShaderNodeMixRGB")
        mul.blend_type = "MULTIPLY"
        mul.inputs["Fac"].default_value = 1.0
        mul.inputs["Color2"].default_value = rgba(darken, darken, darken)
        nt.links.new(diff.outputs["Color"], mul.inputs["Color1"])
        nt.links.new(mul.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        nt.links.new(diff.outputs["Color"], bsdf.inputs["Base Color"])
    nor = image_node(nt, os.path.join(ASSETS, f"{WOOD_STEM}_nor_gl_{WOOD_RES}.jpg"), non_color=True)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.inputs["Strength"].default_value = 0.6
    nt.links.new(nor.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    set_inputs(bsdf, Roughness=0.5, Specular_IOR_Level=0.0, Coat_Weight=1.0, Coat_Roughness=0.10)
    return mat


def make_metal(name, color, rough, vary=0.0, scale=55.0):
    """Polished metal. `vary` adds a slow change in roughness: the burnish."""
    mat, nt, bsdf, _ = new_material(name)
    set_inputs(bsdf, Base_Color=rgba(*color), Metallic=1.0, Roughness=rough)
    if vary > 0.0:
        coord = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = scale
        noise.inputs["Detail"].default_value = 4.0
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value = 0.3
        rng.inputs["From Max"].default_value = 0.7
        rng.inputs["To Min"].default_value = max(0.02, rough - vary)
        rng.inputs["To Max"].default_value = rough + vary
        nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], rng.inputs["Value"])
        nt.links.new(rng.outputs["Result"], bsdf.inputs["Roughness"])
    return mat


def make_glass(name):
    """Clear glass that lets light through to what is inside the case."""
    mat, nt, bsdf, out = new_material(name)
    set_inputs(bsdf, Base_Color=rgba(0.93, 0.97, 0.95), Roughness=0.0, IOR=1.5, Transmission_Weight=1.0)
    path = nt.nodes.new("ShaderNodeLightPath")
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    clear.inputs["Color"].default_value = rgba(0.90, 0.95, 0.92)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(path.outputs["Is Shadow Ray"], mix.inputs[0])
    nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    nt.links.new(clear.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def make_printed(name, path, rough, specular=0.5):
    mat, nt, bsdf, _ = new_material(name)
    nt.links.new(image_node(nt, path).outputs["Color"], bsdf.inputs["Base Color"])
    set_inputs(bsdf, Roughness=rough, Specular_IOR_Level=specular)
    return mat


def make_felt(name):
    """Green baize that fades to darkness away from the instrument.

    Plain diffuse, with no sheen: the table is baked for the web page, and a
    bake can only be right from every angle if the cloth looks the same from
    every angle.
    """
    mat, nt, bsdf, _ = new_material(name)
    set_inputs(bsdf, Roughness=1.0, Specular_IOR_Level=0.0)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    dist = nt.nodes.new("ShaderNodeVectorMath")
    dist.operation = "LENGTH"
    fade = nt.nodes.new("ShaderNodeMapRange")
    fade.interpolation_type = "SMOOTHSTEP"
    fade.inputs["From Min"].default_value = 0.22
    fade.inputs["From Max"].default_value = 1.05
    fade.inputs["To Min"].default_value = 1.0
    fade.inputs["To Max"].default_value = 0.0
    tint = nt.nodes.new("ShaderNodeMixRGB")
    tint.inputs["Color1"].default_value = rgba(0.0, 0.0, 0.0)
    tint.inputs["Color2"].default_value = rgba(0.035, 0.140, 0.095)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 2600.0
    noise.inputs["Detail"].default_value = 3.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.0004
    nt.links.new(coord.outputs["Object"], dist.inputs[0])
    nt.links.new(dist.outputs["Value"], fade.inputs["Value"])
    nt.links.new(fade.outputs["Result"], tint.inputs["Fac"])
    nt.links.new(tint.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def make_plain(name, color, rough, **extra):
    mat, _, bsdf, _ = new_material(name)
    set_inputs(bsdf, Base_Color=rgba(*color), Roughness=rough, **extra)
    return mat


# ---- Mesh helpers ----------------------------------------------------------
_wood_seq = [0]


def wood_offset():
    """A different patch of the veneer for each board (metres, deterministic)."""
    _wood_seq[0] += 1
    k = _wood_seq[0]
    return ((k * 0.6180339887) % 1.0 * WOOD_M, (k * 0.7548776662) % 1.0 * WOOD_M)


def wood_uv(across_mm, along_mm, off):
    """Veneer UV: the grain runs along V in both scans."""
    return ((across_mm * S + off[0]) / WOOD_M, (along_mm * S + off[1]) / WOOD_M)


def new_object(name, verts, faces, uvs=None, mat=None, parent=None, loc=(0, 0, 0), rot=(0, 0, 0),
               smooth=35.0, closed=False, weld=False, bevel=0.0):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x * S, y * S, z * S) for x, y, z in verts], [], faces)
    if uvs is not None:
        layer = me.uv_layers.new(name="UVMap")
        layer.data.foreach_set("uv", [c for face in uvs for uv in face for c in uv])
    bm = bmesh.new()
    bm.from_mesh(me)
    if weld:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    if closed:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if smooth is not None:
        limit = math.radians(smooth)
        for f in bm.faces:
            f.smooth = True
        for e in bm.edges:
            e.smooth = len(e.link_faces) == 2 and e.calc_face_angle(0.0) <= limit
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = Vector(loc) * S
    ob.rotation_euler = Euler([math.radians(a) for a in rot])
    if parent is not None:
        ob.parent = parent
    if mat is not None:
        me.materials.append(mat)
    if bevel > 0.0:
        mod = ob.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel * S
        mod.segments = 3
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(40.0)
        wn = ob.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        wn.keep_sharp = True
    return ob


def empty(name, loc, rot=(0, 0, 0), parent=None):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 0.01
    bpy.context.scene.collection.objects.link(ob)
    ob.location = Vector(loc) * S
    ob.rotation_euler = Euler([math.radians(a) for a in rot])
    if parent is not None:
        ob.parent = parent
    return ob


def lathe(name, prof, mat=None, segs=96, sweep=None, uv=None, uv_r=1.0, **kw):
    """Turn a profile of (radius, z) points about Z.

    Trace solids anticlockwise in the (r, z) half-plane: out along the bottom,
    up the outside, in along the top. `sweep` (deg0, deg1) makes a partial turn.
    uv='cyl' wraps U around and V up; uv='planar' projects along Z.
    """
    full = sweep is None
    a0, a1 = (0.0, 2 * math.pi) if full else (math.radians(sweep[0]), math.radians(sweep[1]))
    wrap = full and uv != "cyl"
    cols = segs if wrap else segs + 1
    verts, rings = [], []
    for r, z in prof:
        if r < 1e-6:
            rings.append([len(verts)])
            verts.append((0.0, 0.0, z))
        else:
            ring = []
            for i in range(cols):
                a = a0 + (a1 - a0) * i / segs
                ring.append(len(verts))
                verts.append((r * math.cos(a), r * math.sin(a), z))
            rings.append(ring)
    zs = [p[1] for p in prof]
    z_lo, z_span = min(zs), (max(zs) - min(zs)) or 1.0

    def uv_of(k, i, vi):
        if uv == "cyl":
            return (i / segs, (prof[k][1] - z_lo) / z_span)
        x, y, _ = verts[vi]
        return (0.5 + x / (2 * uv_r), 0.5 + y / (2 * uv_r))

    faces, uvs = [], []
    for k in range(len(prof) - 1):
        lower, upper = rings[k], rings[k + 1]
        if len(lower) == 1 and len(upper) == 1:
            continue
        for i in range(segs):
            j = (i + 1) % cols if wrap else i + 1
            if len(lower) == 1:
                corners = [(k, 0, lower[0]), (k + 1, j, upper[j]), (k + 1, i, upper[i])]
            elif len(upper) == 1:
                corners = [(k, i, lower[i]), (k, j, lower[j]), (k + 1, 0, upper[0])]
            else:
                corners = [(k, i, lower[i]), (k, j, lower[j]), (k + 1, j, upper[j]), (k + 1, i, upper[i])]
            faces.append(tuple(c[2] for c in corners))
            uvs.append([uv_of(*c) for c in corners])
    return new_object(name, verts, faces, uvs if uv else None, mat, **kw)


def loft_rect(name, hx, hy, prof, mat, cap_top=True):
    """Sweep a moulding profile of (inset, z) points around a rectangle.

    Each side is its own board with the grain along its length and clean mitres.
    """
    arc = [0.0]
    for (i0, z0), (i1, z1) in zip(prof, prof[1:]):
        arc.append(arc[-1] + math.hypot(i1 - i0, z1 - z0))
    sides = [((-1, -1), (1, -1)), ((1, -1), (1, 1)), ((1, 1), (-1, 1)), ((-1, 1), (-1, -1))]
    verts, faces, uvs = [], [], []
    for (sx0, sy0), (sx1, sy1) in sides:
        off = wood_offset()
        along_x = sy0 == sy1
        base = len(verts)
        for inset, z in prof:
            verts.append((sx0 * (hx - inset), sy0 * (hy - inset), z))
            verts.append((sx1 * (hx - inset), sy1 * (hy - inset), z))
        for k in range(len(prof) - 1):
            quad = (base + 2 * k, base + 2 * k + 1, base + 2 * k + 3, base + 2 * k + 2)
            faces.append(quad)
            face_uv = []
            for vi in quad:
                x, y, _ = verts[vi]
                face_uv.append(wood_uv(arc[(vi - base) // 2], x if along_x else y, off))
            uvs.append(face_uv)
    if cap_top:
        inset, z = prof[-1]
        off = wood_offset()
        base = len(verts)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append((sx * (hx - inset), sy * (hy - inset), z))
        faces.append((base, base + 1, base + 2, base + 3))
        uvs.append([wood_uv(verts[base + n][1], verts[base + n][0], off) for n in range(4)])
    return new_object(name, verts, faces, uvs, mat, smooth=30.0)


def board(name, center, size, grain, mat, bevel=0.5, **kw):
    """A rectangular board with the grain along axis 'x', 'y' or 'z'."""
    g = "xyz".index(grain)
    half = [s / 2.0 for s in size]
    off = wood_offset()
    verts, faces, uvs = [], [], []
    for n in range(3):
        a, b = (n + 1) % 3, (n + 2) % 3
        for sign in (-1, 1):
            order = ((-1, -1), (1, -1), (1, 1), (-1, 1))
            if sign < 0:
                order = order[::-1]
            base = len(verts)
            face_uv = []
            for da, db in order:
                p = [0.0, 0.0, 0.0]
                p[n], p[a], p[b] = sign * half[n], da * half[a], db * half[b]
                verts.append((center[0] + p[0], center[1] + p[1], center[2] + p[2]))
                along, across = (p[a], p[b]) if g == a else (p[b], p[a])
                face_uv.append(wood_uv(across, along, off))
            faces.append((base, base + 1, base + 2, base + 3))
            uvs.append(face_uv)
    return new_object(name, verts, faces, uvs, mat, weld=True, closed=True, bevel=bevel, **kw)


def prism(name, pts, thick, mat, origin, udir, vdir, wood=False, **kw):
    """Extrude a flat outline of (u, v) points by `thick` along udir x vdir."""
    u, v = Vector(udir), Vector(vdir)
    n = u.cross(v)
    o = Vector(origin)
    off = wood_offset() if wood else None
    count = len(pts)
    verts = [tuple(o + u * a + v * b) for a, b in pts] + [tuple(o + u * a + v * b + n * thick) for a, b in pts]
    faces = [tuple(range(count - 1, -1, -1)), tuple(range(count, 2 * count))]
    uvs = None
    if wood:
        uvs = [[wood_uv(pts[i][1], pts[i][0], off) for i in range(count - 1, -1, -1)],
               [wood_uv(pts[i][1], pts[i][0], off) for i in range(count)]]
    for i in range(count):
        j = (i + 1) % count
        faces.append((i, j, count + j, count + i))
        if wood:
            uvs.append([wood_uv(0.0, pts[i][0], off), wood_uv(0.0, pts[j][0], off),
                        wood_uv(thick, pts[j][0], off), wood_uv(thick, pts[i][0], off)])
    return new_object(name, verts, faces, uvs, mat, closed=True, **kw)


def rod(name, p0, p1, radius, mat, segs=24, **kw):
    """A cylinder from p0 to p1."""
    a, b = Vector(p0), Vector(p1)
    length = (b - a).length
    ob = lathe(name, [(0, 0), (radius, 0), (radius, length), (0, length)], mat, segs=segs, closed=True, **kw)
    ob.location = a * S
    ob.rotation_euler = Vector((0, 0, 1)).rotation_difference((b - a).normalized()).to_euler()
    return ob


def glass_pane(name, w, h, back_center, right, up, mat, thick=4.0, edge=1.6, bevel=9.0):
    """A pane with a bevelled margin on its outer face (outward = right x up)."""
    r, u = Vector(right), Vector(up)
    n = r.cross(u)
    o = Vector(back_center)
    verts = []
    for depth, inset in ((0.0, 0.0), (edge, 0.0), (thick, bevel)):
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(tuple(o + r * sx * (w / 2 - inset) + u * sy * (h / 2 - inset) + n * depth))
    faces = [(3, 2, 1, 0), (8, 9, 10, 11)]
    for i in range(4):
        j = (i + 1) % 4
        faces.append((i, j, 4 + j, 4 + i))
        faces.append((4 + i, 4 + j, 8 + j, 8 + i))
    return new_object(name, verts, faces, None, mat, smooth=None, closed=True)


def arc_pts(cx, cy, r, deg0, deg1, steps):
    return [(cx + r * math.cos(math.radians(deg0 + (deg1 - deg0) * i / steps)),
             cy + r * math.sin(math.radians(deg0 + (deg1 - deg0) * i / steps))) for i in range(steps + 1)]


def disc_pts(cx, cy, r, steps=40):
    return arc_pts(cx, cy, r, 0.0, 360.0, steps)[:-1]


def pillar_profile(z0, z1, r=3.4):
    """A turned brass column."""
    return [(0, z0), (r + 3.2, z0), (r + 3.2, z0 + 1.6), (r + 1.2, z0 + 2.8), (r, z0 + 4.5),
            (r, z1 - 5.0), (r + 1.4, z1 - 4.0), (r + 1.4, z1 - 2.4), (r, z1 - 1.6), (r - 0.4, z1), (0, z1)]


# ---- Scene -----------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

WOOD = make_wood("Wood", darken=ARGS.wood_gain)
WOOD_DARK = make_wood("WoodDark", darken=0.25)
BRASS = make_metal("Brass", (0.80, 0.53, 0.17), 0.16, vary=0.06)
BRASS_BRIGHT = make_metal("BrassPolished", (0.82, 0.56, 0.19), 0.045)
NICKEL = make_metal("Nickel", (0.72, 0.70, 0.66), 0.20, vary=0.05, scale=90.0)
STEEL = make_metal("Steel", (0.62, 0.63, 0.65), 0.14)
BLUED = make_metal("BluedSteel", (0.035, 0.05, 0.13), 0.22)
GLASS = make_glass("Glass")
PAPER = make_printed("ChartPaper", os.path.join(TEX, "chart_placeholder.png"), 0.82)
DIAL = make_printed("DialFace", os.path.join(TEX, "dial.png"), 0.55, specular=0.3)
FELT = make_felt("Felt")
INK = make_plain("Ink", (0.03, 0.025, 0.20), 0.3)

# Table.
new_object("Table", [(-TABLE_HALF, -TABLE_HALF, 0), (TABLE_HALF, -TABLE_HALF, 0), (TABLE_HALF, TABLE_HALF, 0),
                     (-TABLE_HALF, TABLE_HALF, 0)], [(0, 1, 2, 3)], [[(0, 0), (1, 0), (1, 1), (0, 1)]], FELT, smooth=None)

# Base: feet, then the drawer tier and mouldings as one swept profile.
fx, fy = LIP_HX - 3.0, LIP_HY - 3.0
foot = [(0.0, 0.0)] + arc_pts(FOOT_L, 0.0, FOOT_H, 180.0, 90.0, 12) + [(0.0, FOOT_H)]
for sx in (-1, 1):
    for sy in (-1, 1):
        y0 = sy * (fy - FOOT_T) if sx == sy else sy * fy
        prism(f"Foot_x_{sx}_{sy}", foot, FOOT_T, WOOD, (sx * fx, y0, 0.0), (-sx, 0, 0), (0, 0, 1), wood=True, smooth=30.0)
        x0 = sx * (fx - FOOT_T) if sx != sy else sx * fx
        prism(f"Foot_y_{sx}_{sy}", foot, FOOT_T, WOOD, (x0, sy * fy, 0.0), (0, -sy, 0), (0, 0, 1), wood=True, smooth=30.0)

base_prof = [(5.0, FOOT_H), (5.0, 17.0), (TIER_INSET, 18.5), (TIER_INSET, 62.0), (4.0, 62.0)]
base_prof += [(4.0 - 4.0 * math.cos(math.radians(t)), 66.0 + 4.0 * math.sin(math.radians(t))) for t in range(-75, 91, 15)]
base_prof += [(6.0, 70.0)]
base_prof += [(6.0 + 27.0 * t / 24.0, 70.0 + 18.0 * (1.0 - math.cos(math.pi * t / 24.0)) / 2.0) for t in range(1, 25)]
base_prof += [(33.0, 90.2), (34.0, DECK_Z), (LIP_HX - HOOD_HX, DECK_Z)]
loft_rect("Base", LIP_HX, LIP_HY, base_prof, WOOD)

tier_front = -(LIP_HY - TIER_INSET)
board("DrawerFront", (0.0, tier_front - 0.75, 40.0), (352.0, 3.0, 36.0), "x", WOOD, bevel=0.8)
lathe("DrawerKnob", [(0, 0), (5.2, 0), (5.2, 4.5), (4.0, 7.0), (8.2, 10.0), (9.4, 13.0), (8.6, 16.0), (5.0, 17.6), (0, 17.9)],
      WOOD_DARK, segs=48, closed=True, loc=(0.0, tier_front - 2.0, 40.0), rot=(90, 0, 0))

# Hood: four posts, top and bottom rails, five bevelled panes.
px, py = HOOD_HX - POST / 2.0, HOOD_HY - POST / 2.0
for sx in (-1, 1):
    for sy in (-1, 1):
        board(f"Post_{sx}_{sy}", (sx * px, sy * py, DECK_Z + HOOD_H / 2.0), (POST, POST, HOOD_H), "z", WOOD)
for label, z in (("Bottom", DECK_Z + POST / 2.0), ("Top", HOOD_Z1 - POST / 2.0)):
    for sy in (-1, 1):
        board(f"Rail{label}_x_{sy}", (0.0, sy * py, z), (2 * (HOOD_HX - POST), POST, POST), "x", WOOD)
    for sx in (-1, 1):
        board(f"Rail{label}_y_{sx}", (sx * px, 0.0, z), (POST, 2 * (HOOD_HY - POST), POST), "y", WOOD)

open_w, open_d, open_h = 2 * (HOOD_HX - POST), 2 * (HOOD_HY - POST), HOOD_H - 2 * POST
mid_z = DECK_Z + HOOD_H / 2.0
set_in = 3.0 + 4.0                     # pane back face, measured in from the frame's outer face
glass_pane("GlassFront", open_w + 4, open_h + 4, (0, -HOOD_HY + set_in, mid_z), (1, 0, 0), (0, 0, 1), GLASS)
glass_pane("GlassBack", open_w + 4, open_h + 4, (0, HOOD_HY - set_in, mid_z), (-1, 0, 0), (0, 0, 1), GLASS)
glass_pane("GlassLeft", open_d + 4, open_h + 4, (-HOOD_HX + set_in, 0, mid_z), (0, -1, 0), (0, 0, 1), GLASS)
glass_pane("GlassRight", open_d + 4, open_h + 4, (HOOD_HX - set_in, 0, mid_z), (0, 1, 0), (0, 0, 1), GLASS)
glass_pane("GlassTop", open_w + 4, open_d + 4, (0, 0, HOOD_Z1 - set_in), (1, 0, 0), (0, 1, 0), GLASS)

# Bed plate.
plate = board("BedPlate", (0.0, 0.0, PLATE_TOP - 3.0), (264.0, 136.0, 6.0), "x", BRASS_BRIGHT, bevel=1.0)
plate.data.uv_layers.remove(plate.data.uv_layers[0])

# Drum: turns about its own Z. Chart U runs with time, anticlockwise seen from above.
drum = empty("Drum", (DRUM_X, DRUM_Y, 0.0))
drum.rotation_euler = Euler((0.0, 0.0, math.radians(-90.0 - 360.0 * CHART_NOW_HOURS / 168.0)))
paper_top = PAPER_Z0 + PAPER_H
lathe("DrumBody", [(0, PAPER_Z0 - 2.0), (DRUM_R - 0.4, PAPER_Z0 - 2.0), (DRUM_R - 0.4, paper_top), (0, paper_top)],
      BRASS, closed=True, parent=drum)
lathe("DrumFlange", [(0, PAPER_Z0 - 3.5), (DRUM_R + 2.0, PAPER_Z0 - 3.5), (DRUM_R + 2.0, PAPER_Z0 - 0.6),
                     (DRUM_R + 1.2, PAPER_Z0), (0, PAPER_Z0)], BRASS, closed=True, parent=drum)
lid_z = paper_top - 0.5
lathe("DrumLid", [(0, lid_z), (DRUM_R + 1.5, lid_z), (DRUM_R + 1.5, lid_z + 3.6), (DRUM_R + 0.7, lid_z + 4.4),
                  (DRUM_R - 3.0, lid_z + 4.4), (DRUM_R - 3.6, lid_z + 3.2), (12.0, lid_z + 3.2), (11.0, lid_z + 6.0),
                  (6.5, lid_z + 6.6), (6.5, lid_z + 9.0), (9.0, lid_z + 9.4), (9.0, lid_z + 14.4), (7.6, lid_z + 15.6),
                  (0, lid_z + 15.6)], BRASS, closed=True, parent=drum)
lathe("ChartPaper", [(PAPER_R, PAPER_Z0), (PAPER_R, paper_top)], PAPER, segs=128, uv="cyl", parent=drum, smooth=60.0)
prism("PaperClip", [(-2.0, PAPER_Z0 - 1.0), (2.0, PAPER_Z0 - 1.0), (2.0, paper_top + 0.5), (-2.0, paper_top + 0.5)], 1.1,
      BRASS, (PAPER_R + 1.2, 0.0, 0.0), (0, 1, 0), (0, 0, 1), parent=drum, bevel=0.25)
lathe("DrumGear", [(0, PLATE_TOP + 2.5), (31.0, PLATE_TOP + 2.5), (31.0, PLATE_TOP + 4.5), (0, PLATE_TOP + 4.5)],
      BRASS, segs=120, closed=True, parent=drum)
lathe("DrumSpindle", [(0, PLATE_TOP), (5.0, PLATE_TOP), (5.0, PAPER_Z0 - 3.0), (0, PAPER_Z0 - 3.0)], BRASS, segs=32,
      closed=True, parent=drum)

# Aneroid stack: seven sealed capsules joined at their centres.
stack_z0, pitch, cap_r, boss_r, count = 120.0, 7.2, 27.0, 5.0, 7
lathe("StackPedestal", [(0, PLATE_TOP), (17.0, PLATE_TOP), (17.0, PLATE_TOP + 2.0), (9.0, PLATE_TOP + 4.0), (9.0, stack_z0),
                        (0, stack_z0)], BRASS, segs=64, closed=True, loc=(STACK_XY[0], STACK_XY[1], 0.0))
stack = [(0.0, stack_z0)]
for c in range(count):
    zc = stack_z0 + pitch * (c + 0.5)
    half = pitch / 2.0 - 0.9
    lower, upper = [], []
    for i in range(33):
        t = i / 32.0
        r = boss_r + (cap_r - boss_r) * t
        gap = 0.4 + (half - 0.4) * (1.0 - t ** 5) ** 0.5
        ripple = 0.28 * math.sin(2 * math.pi * 4.0 * t) * math.sin(math.pi * t)
        lower.append((r, zc - gap - ripple))
        upper.append((r, zc + gap + ripple))
    stack += lower + upper[::-1]
stack_top = stack_z0 + pitch * count
stack.append((0.0, stack_top))
lathe("AneroidStack", stack, NICKEL, segs=96, closed=True, loc=(STACK_XY[0], STACK_XY[1], 0.0), smooth=50.0)

# Linkage (schematic for now): stack -> lever -> arbor -> pen arm.
dz = (ARGS.pressure - 29.5) / 3.0 * CHART_GRID
pen_angle = math.asin(dz / PEN_ARM)
link_top = (STACK_XY[0], STACK_XY[1], stack_top + 9.0)
rod("StackLink", (STACK_XY[0], STACK_XY[1], stack_top), link_top, 1.3, STEEL, segs=16)
rod("Lever", link_top, (PIVOT[0], STACK_XY[1], PIVOT[2]), 1.5, BRASS, segs=16)
rod("Arbor", (PIVOT[0], PIVOT[1] - 3.0, PIVOT[2]), (PIVOT[0], 46.0, PIVOT[2]), 2.0, STEEL, segs=24)
for y in (-22.0, 42.0):
    lathe(f"ArborPillar_{int(y)}", pillar_profile(PLATE_TOP, PIVOT[2] + 6.0), BRASS, segs=48, closed=True, loc=(PIVOT[0], y, 0.0))

arm = empty("PenArm", PIVOT, rot=(0.0, math.degrees(pen_angle), 0.0))
new_object("PenArmBlade",
           [(0, -0.35, -3.6), (0, 0.35, -3.6), (0, 0.35, 3.6), (0, -0.35, 3.6),
            (-PEN_ARM, -0.3, -1.1), (-PEN_ARM, 0.3, -1.1), (-PEN_ARM, 0.3, 1.1), (-PEN_ARM, -0.3, 1.1)],
           [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)],
           None, STEEL, parent=arm, closed=True, smooth=None)
new_object("PenNib",
           [(-PEN_ARM - 2.2, 0.3, -1.3), (-PEN_ARM + 3.5, 0.3, -1.3), (-PEN_ARM + 3.5, 0.3, 1.3), (-PEN_ARM - 2.2, 0.3, 1.3),
            (-PEN_ARM, 3.4, 0.0)],
           [(0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)], None, INK, parent=arm, closed=True, smooth=None)
lathe("PenHub", [(0, -2.4), (4.2, -2.4), (4.2, 2.4), (0, 2.4)], BRASS, segs=32, closed=True, parent=arm, rot=(90, 0, 0))
rod("PenLifter", (-24.0, -40.0, PLATE_TOP), (-24.0, -40.0, 214.0), 1.2, STEEL, segs=16)

# Dial: local X right, Y up, Z toward the viewer.
dial = empty("Dial", DIAL_C, rot=(90, 0, 0))
lathe("DialFace", [(DIAL_HOLE, 0.0), (DIAL_R, 0.0), (DIAL_R, 1.2), (DIAL_HOLE, 1.2), (DIAL_HOLE, 0.0)], DIAL, segs=128,
      uv="planar", uv_r=DIAL_R, parent=dial, closed=True)
lathe("DialBezel", [(DIAL_R - 0.6, -0.4), (DIAL_R + 2.4, -0.4), (DIAL_R + 2.4, 1.6), (DIAL_R + 1.6, 2.5), (DIAL_R + 0.2, 2.5),
                    (DIAL_R - 0.6, 1.9), (DIAL_R - 0.6, -0.4)], BRASS_BRIGHT, segs=128, parent=dial, closed=True)
lathe("DialInnerRing", [(DIAL_HOLE - 1.2, -0.3), (DIAL_HOLE + 0.5, -0.3), (DIAL_HOLE + 0.5, 1.7), (DIAL_HOLE - 0.4, 2.1),
                        (DIAL_HOLE - 1.2, 1.7), (DIAL_HOLE - 1.2, -0.3)], BRASS_BRIGHT, segs=96, parent=dial, closed=True)
needle = empty("Needle", (0.0, 0.0, 4.2), rot=(0, 0, -(ARGS.pressure - 29.5) * DIAL_DEG_PER_INHG), parent=dial)
prism("NeedleHand", [(-1.2, -15.0), (1.2, -15.0), (0.95, 0.0), (0.22, 41.0), (-0.22, 41.0), (-0.95, 0.0)], 0.45, BLUED,
      (0, 0, 0), (1, 0, 0), (0, 1, 0), parent=needle, smooth=None)
lathe("NeedleHub", [(0, 0), (3.4, 0), (3.4, 1.0), (2.2, 1.8), (0, 1.9)], BRASS_BRIGHT, segs=32, closed=True, parent=needle)

# The bridge behind the dial that carries the needle's arbor.
bz = -6.0
prism("BridgeUpright", [(-4.2, -32.0), (4.2, -32.0), (4.2, 32.0), (-4.2, 32.0)], 2.4, BRASS, (0, 0, bz), (1, 0, 0), (0, 1, 0),
      parent=dial, bevel=0.4)
prism("BridgeCross", [(-21.0, -3.6), (21.0, -3.6), (21.0, 3.6), (-21.0, 3.6)], 2.4, BRASS, (0, 0, bz), (1, 0, 0), (0, 1, 0),
      parent=dial, bevel=0.4)
for label, cx, cy, r in (("Hub", 0, 0, 8.5), ("N", 0, 32, 6.5), ("S", 0, -32, 6.5), ("E", 21, 0, 5.5), ("W", -21, 0, 5.5)):
    prism(f"BridgeBoss{label}", disc_pts(cx, cy, r), 3.0, BRASS, (0, 0, bz), (1, 0, 0), (0, 1, 0), parent=dial, smooth=40.0, bevel=0.4)
for dx in (-33.0, 33.0):
    lathe(f"DialPillar_{int(dx)}", pillar_profile(PLATE_TOP, DIAL_C[2] + 30.0, r=3.0), BRASS, segs=48, closed=True,
          loc=(DIAL_C[0] + dx, DIAL_C[1] + 9.0, 0.0))
    rod(f"DialStud_{int(dx)}", (DIAL_C[0] + dx, DIAL_C[1] + 9.0, DIAL_C[2] + 22.0), (DIAL_C[0] + dx, DIAL_C[1], DIAL_C[2] + 22.0),
        1.6, BRASS, segs=16)

# Thermometer tube along the bottom of the dial.
tube_r, tube_w = 0.80 * DIAL_R, 1.5
lathe("ThermoTube", [(tube_r + tube_w * math.cos(math.radians(t)), 1.2 + tube_w + tube_w * math.sin(math.radians(t)))
                     for t in range(0, 361, 30)], NICKEL, segs=64, sweep=(-150.0, -30.0), parent=dial, smooth=60.0)
bulb_a = math.radians(-150.0)
lathe("ThermoBulb", [(0, -2.6)] + [(2.6 * math.cos(math.radians(t)), 2.6 * math.sin(math.radians(t))) for t in range(-60, 61, 30)]
      + [(0, 2.6)], NICKEL, segs=24, closed=True, parent=dial,
      loc=(tube_r * math.cos(bulb_a), tube_r * math.sin(bulb_a), 1.2 + tube_w), smooth=60.0)

# ---- Lighting and camera -----------------------------------------------------
world = bpy.data.worlds.new("Studio")
world.use_nodes = True
scene.world = world
wn = world.node_tree
wn.nodes.clear()
w_out = wn.nodes.new("ShaderNodeOutputWorld")
coord = wn.nodes.new("ShaderNodeTexCoord")
mapping = wn.nodes.new("ShaderNodeMapping")
mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(ARGS.env_rot))
env = wn.nodes.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load(ARGS.env)
lit = wn.nodes.new("ShaderNodeBackground")
dark = wn.nodes.new("ShaderNodeBackground")
dark.inputs["Color"].default_value = rgba(0.0, 0.0, 0.0)
path = wn.nodes.new("ShaderNodeLightPath")
strength = wn.nodes.new("ShaderNodeMath")          # diffuse + (gloss - diffuse) * is_glossy
strength.operation = "MULTIPLY_ADD"
strength.inputs[1].default_value = ARGS.env_gloss - ARGS.env_diffuse
strength.inputs[2].default_value = ARGS.env_diffuse
# The camera sees darkness behind the instrument, directly or through the glass.
# A ray that has already bounced off something still sees the studio.
seen = wn.nodes.new("ShaderNodeMath")
seen.operation = "MAXIMUM"
bounced = wn.nodes.new("ShaderNodeMath")
bounced.operation = "ADD"
direct = wn.nodes.new("ShaderNodeMath")
direct.operation = "LESS_THAN"
direct.inputs[1].default_value = 0.5
backdrop = wn.nodes.new("ShaderNodeMath")
backdrop.operation = "MULTIPLY"
mix = wn.nodes.new("ShaderNodeMixShader")
wn.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
wn.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
wn.links.new(env.outputs["Color"], lit.inputs["Color"])
wn.links.new(path.outputs["Is Glossy Ray"], strength.inputs[0])
wn.links.new(strength.outputs[0], lit.inputs["Strength"])
wn.links.new(path.outputs["Is Camera Ray"], seen.inputs[0])
wn.links.new(path.outputs["Is Transmission Ray"], seen.inputs[1])
wn.links.new(path.outputs["Glossy Depth"], bounced.inputs[0])
wn.links.new(path.outputs["Diffuse Depth"], bounced.inputs[1])
wn.links.new(bounced.outputs[0], direct.inputs[0])
wn.links.new(seen.outputs[0], backdrop.inputs[0])
wn.links.new(direct.outputs[0], backdrop.inputs[1])
wn.links.new(backdrop.outputs[0], mix.inputs[0])
wn.links.new(lit.outputs[0], mix.inputs[1])
wn.links.new(dark.outputs[0], mix.inputs[2])
wn.links.new(mix.outputs[0], w_out.inputs["Surface"])


def aim(ob, target_mm):
    direction = Vector(target_mm) * S - ob.location
    ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


if ARGS.key > 0.0:
    key_data = bpy.data.lights.new("Key", "SPOT")
    key_data.energy = ARGS.key
    key_data.spot_size = math.radians(58.0)
    key_data.spot_blend = 0.9
    key_data.shadow_soft_size = 0.14
    key_data.color = (1.0, 0.95, 0.88)
    key = bpy.data.objects.new("Key", key_data)
    scene.collection.objects.link(key)
    key.location = Vector((-650.0, -900.0, 1050.0)) * S
    aim(key, (0.0, 0.0, 120.0))

cam_data = bpy.data.cameras.new("Camera")
cam_data.sensor_width = 36.0
cam_data.clip_start = 0.05
cam_data.clip_end = 30.0
cam = bpy.data.objects.new("Camera", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
VIEWS = {"hero": (16.0, 10.0, 1750.0, 85.0, (0.0, 0.0, 118.0)),
         "front": (0.0, 9.0, 1150.0, 80.0, (0.0, 0.0, 132.0))}
yaw, elev, dist, lens, target = VIEWS[ARGS.view]
cam_data.lens = lens
yaw_r, elev_r = math.radians(yaw), math.radians(elev)
cam.location = (Vector(target) + dist * Vector((-math.sin(yaw_r) * math.cos(elev_r), -math.cos(yaw_r) * math.cos(elev_r),
                                                math.sin(elev_r)))) * S
aim(cam, target)

# ---- Output ------------------------------------------------------------------
width, height = (int(v) for v in ARGS.res.lower().split("x"))
scene.render.engine = "CYCLES"
scene.render.resolution_x, scene.render.resolution_y = width, height
scene.render.resolution_percentage = 100
scene.cycles.samples = ARGS.samples
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 16
scene.cycles.glossy_bounces = 8
scene.cycles.transmission_bounces = 14
scene.cycles.transparent_max_bounces = 16
scene.view_settings.exposure = ARGS.exposure
for attr, value in (("view_transform", "AgX"), ("look", "AgX - Medium High Contrast")):
    try:
        setattr(scene.view_settings, attr, value)
    except TypeError as err:
        print("colour management:", err)
prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "OPTIX"
    prefs.refresh_devices()
    for dev in prefs.devices:
        dev.use = dev.type == "OPTIX"
    scene.cycles.device = "GPU"
    scene.cycles.denoiser = "OPTIX"
except (TypeError, AttributeError) as err:
    print("GPU setup failed, rendering on CPU:", err)

# ---- Baked lighting for the web page ---------------------------------------
def save_png(name, pixels, size, out_dir):
    """Write an (size, size, 3) array of 0..1 values as an 8-bit PNG, untouched."""
    import numpy as np
    img = bpy.data.images.new(name + "_out", size, size, alpha=False, is_data=True)
    rgba = np.ones((size, size, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(pixels, 0.0, 1.0)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = os.path.join(out_dir, name + ".png")
    img.file_format = "PNG"
    img.save()
    print("baked", img.filepath_raw)


def srgb_encode(x):
    import numpy as np
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def read_pixels(img, size):
    import numpy as np
    buf = np.empty(size * size * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return buf.reshape(size, size, 4)[..., :3]


def bake_lighting(out_dir, size, samples):
    """Bake what a live renderer cannot work out: shadowed, bounced diffuse light.

    Everything but the glass and the table shares one atlas on a second UV set.
    light.png holds the diffuse light arriving at each point (no surface colour),
    ao.png holds how enclosed each point is (for dimming reflections), and
    table.png holds the finished table, shadows and all.
    """
    os.makedirs(out_dir, exist_ok=True)
    table = bpy.data.objects["Table"]
    meshes = [ob for ob in scene.objects if ob.type == "MESH"]
    panes = [ob for ob in meshes if ob.data.materials[0] is GLASS]
    targets = [ob for ob in meshes if ob is not table and ob not in panes]

    def select(objects):
        bpy.ops.object.select_all(action="DESELECT")
        for ob in objects:
            ob.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]

    def aim_materials(objects, image):
        for mat in {ob.data.materials[0] for ob in objects}:
            nodes = mat.node_tree.nodes
            node = nodes.get("BakeTarget") or nodes.new("ShaderNodeTexImage")
            node.name = "BakeTarget"
            node.image = image
            for other in nodes:
                other.select = False
            node.select = True
            nodes.active = node

    # Bevels become real geometry, then every target gets a place in the atlas.
    select(targets)
    bpy.ops.object.convert(target="MESH")
    for ob in targets:
        layers = ob.data.uv_layers
        if not layers:
            layers.new(name="UVMap")
        layers.active = layers.new(name="Light")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.0015, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")

    scene.cycles.samples = samples
    margin = max(4, size // 256)

    light = bpy.data.images.new("light", size, size, alpha=False, float_buffer=True)
    aim_materials(targets, light)
    select(targets)
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, margin=margin, use_clear=True, uv_layer="Light")
    lit = read_pixels(light, size)
    print("light map: max", float(lit.max()), "mean", float(lit.mean()))
    save_png("light", srgb_encode(lit / LIGHT_SCALE), size, out_dir)

    ao = bpy.data.images.new("ao", size, size, alpha=False, float_buffer=True, is_data=True)
    aim_materials(targets, ao)
    for pane in panes:
        pane.hide_render = True
    scene.world.light_settings.distance = 0.06
    bpy.ops.object.bake(type="AO", margin=margin, use_clear=True, uv_layer="Light")
    for pane in panes:
        pane.hide_render = False
    save_png("ao", read_pixels(ao, size), size, out_dir)

    cloth = bpy.data.images.new("table", size, size, alpha=False, float_buffer=True)
    aim_materials([table], cloth)
    select([table])
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR", "DIRECT", "INDIRECT"}, margin=0, use_clear=True)
    save_png("table", srgb_encode(read_pixels(cloth, size)), size, out_dir)
    scene.cycles.samples = ARGS.samples


if ARGS.bake:
    bake_lighting(os.path.abspath(ARGS.bake), ARGS.bake_size, ARGS.bake_samples)
if ARGS.save:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(ARGS.save))
if ARGS.render:
    scene.render.filepath = os.path.abspath(ARGS.render)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print("rendered", scene.render.filepath)
if ARGS.export:
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(ARGS.export), export_format="GLB", export_apply=True,
                              export_yup=True, export_image_format="NONE", export_cameras=True, export_lights=False)
    print("exported", os.path.abspath(ARGS.export))
