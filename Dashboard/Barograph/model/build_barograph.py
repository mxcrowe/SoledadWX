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
  --view NAME       hero (default), front, right, or a close view of the movement:
                    mech, mech_left, mech_back, mech_top, or pen (the writing point)
  --bare            leave the hood off, to see the movement plainly
  --samples N       Cycles samples (default 256)
  --res WxH         default 1920x1080
  --pressure P      inHg shown by pen and needle (default: where the placeholder trace ends)
  --temp F          degrees Fahrenheit shown by the dial thermometer (default 68)
  --wood-scale K    shrink the veneer figure to suit a small case (default 0.5)
  --env-rot DEG     turn the studio lighting about the vertical

Names the web page relies on: Drum, ChartClip, PenArbor, PenArm, CrankPin, TopLever,
LeverPin, StackPin, Link, StackPost, PenLifter, Needle, Table, and the material names.
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
THERMO_F0_DEG, THERMO_F140_DEG = 236.0, 124.0     # as in make_textures.py: clockwise from the top of the dial
THERMO_SWEEP = (-150.0, -30.0)         # the tube, bulb end first, anticlockwise from the dial's +X (scene.ts must agree)
STACK_XY = (2.0, 12.0)

# The movement stands on its own satin plate, on top of the polished bed plate.
MECH_TOP = PLATE_TOP + 3.0
MECH_X, MECH_Y = (-31.0, 121.0), (-64.0, 60.0)
BALL_R = 4.7                           # the ball in each pillar that holds an arbor's pivot
TOP_ARBOR = (18.0, 181.0)              # x and z of the top lever's arbor; like the pen's, it runs along Y
TALL_Y, LOW_Y = (-21.0, 45.0), (-53.5, 30.0)      # where each bridge's two pillars stand
LEVER_Y = STACK_XY[1]                  # the lever, link and crank all work in this plane
LEVER_PIN = (60.0, 0.0)                # from the top arbor to the link's upper pin, at mid scale
STACK_PIN = (STACK_XY[0] - TOP_ARBOR[0], 0.0)     # from the top arbor to the point over the stack
CRANK_PIN = (-17.0, -4.5)              # from the pen arbor to the link's lower pin, at mid scale
LINK = math.hypot(PIVOT[0] + CRANK_PIN[0] - TOP_ARBOR[0] - LEVER_PIN[0], PIVOT[2] + CRANK_PIN[1] - TOP_ARBOR[1] - LEVER_PIN[1])
LIFTER = (-8.0, -50.0)                 # the pen lifter's stud
INK_WELL = (-10.0, 46.0)
ENGRAVING_FONT = "C:/Windows/Fonts/COPRGTB.TTF"   # Copperplate Gothic, as on the dial


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
    p.add_argument("--view", default="hero", choices=["hero", "front", "right", "mech", "mech_left", "mech_back", "mech_top", "pen"])
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--res", default="1920x1080")
    p.add_argument("--pressure", type=float, default=29.777)
    p.add_argument("--temp", type=float, default=68.0)
    p.add_argument("--bare", action="store_true")
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
    cleaned = os.path.join(TEX, "wood_diff_clean.jpg")          # clean_wood.py
    if ARGS.wood == "rosewood" and not os.path.exists(cleaned):
        raise SystemExit("Run clean_wood.py first: it makes tex/wood_diff_clean.jpg")
    diff = image_node(nt, cleaned if ARGS.wood == "rosewood" else os.path.join(ASSETS, f"{WOOD_STEM}_diff_{WOOD_RES}.jpg"))
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


def make_thermo(name, level):
    """The thermometer tube: red spirit up to `level` of its length (by U), enamel white beyond."""
    mat, nt, bsdf, _ = new_material(name)
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    parts = nt.nodes.new("ShaderNodeSeparateXYZ")
    below = nt.nodes.new("ShaderNodeMath")
    below.operation = "LESS_THAN"
    below.inputs[1].default_value = level
    pick = nt.nodes.new("ShaderNodeMixRGB")
    pick.inputs["Color1"].default_value = rgba(*THERMO_WHITE)
    pick.inputs["Color2"].default_value = rgba(*THERMO_RED)
    nt.links.new(uv.outputs["UV"], parts.inputs["Vector"])
    nt.links.new(parts.outputs["X"], below.inputs[0])
    nt.links.new(below.outputs[0], pick.inputs["Fac"])
    nt.links.new(pick.outputs["Color"], bsdf.inputs["Base Color"])
    set_inputs(bsdf, Roughness=0.08)
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

    One strip of veneer wraps all the way round, so the grain runs on round
    each corner instead of jumping. Its two ends meet at the back left corner,
    where it is least seen.
    """
    arc = [0.0]
    for (i0, z0), (i1, z1) in zip(prof, prof[1:]):
        arc.append(arc[-1] + math.hypot(i1 - i0, z1 - z0))
    # Left side (back to front), front, right, back: anticlockwise seen from above.
    sides = [((-1, 1), (-1, -1)), ((-1, -1), (1, -1)), ((1, -1), (1, 1)), ((1, 1), (-1, 1))]
    off = wood_offset()
    verts, faces, uvs = [], [], []
    walked = [0.0] * len(prof)         # distance round the strip so far, per profile row
    for (sx0, sy0), (sx1, sy1) in sides:
        base = len(verts)
        lengths = []
        for k, (inset, z) in enumerate(prof):
            verts.append((sx0 * (hx - inset), sy0 * (hy - inset), z))
            verts.append((sx1 * (hx - inset), sy1 * (hy - inset), z))
            a, b = verts[-2], verts[-1]
            lengths.append(math.hypot(b[0] - a[0], b[1] - a[1]))
        for k in range(len(prof) - 1):
            quad = (base + 2 * k, base + 2 * k + 1, base + 2 * k + 3, base + 2 * k + 2)
            faces.append(quad)
            face_uv = []
            for vi in quad:
                row, end = (vi - base) // 2, (vi - base) % 2
                face_uv.append(wood_uv(arc[row], walked[row] + end * lengths[row], off))
            uvs.append(face_uv)
        walked = [w + n for w, n in zip(walked, lengths)]
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


def box(name, center, size, mat, bevel=0.4, **kw):
    """A plain metal block: a board without the veneer bookkeeping."""
    keep = _wood_seq[0]
    ob = board(name, center, size, "x", mat, bevel=bevel, **kw)
    _wood_seq[0] = keep
    ob.data.uv_layers.remove(ob.data.uv_layers[0])
    return ob


def ball_pts(zc, r, r0, r1, steps=10):
    """Profile of a ball centred at height zc, between necks of radius r0 (below) and r1 (above)."""
    a0, a1 = -math.acos(min(1.0, r0 / r)), math.acos(min(1.0, r1 / r))
    angles = [a0 + (a1 - a0) * i / steps for i in range(steps + 1)]
    return [(r * math.cos(a), zc + r * math.sin(a)) for a in angles]


def turned(name, prof, mat, axis, loc=(0, 0, 0), segs=32, **kw):
    """A lathe whose profile heights run along +X ("x"), -X ("-x"), +Y ("y") or +Z ("z") from `loc`."""
    rot = {"x": (0, 90, 0), "-x": (0, -90, 0), "y": (-90, 0, 0), "z": (0, 0, 0)}[axis]
    return lathe(name, prof, mat, segs=segs, closed=True, loc=loc, rot=rot, **kw)


def ring_pts(r, n=24):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def extruded(pts, z0, z1):
    """Vertices and faces of an outline of (x, y) points pulled from z0 up to z1."""
    n = len(pts)
    verts = [(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts]
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return verts, faces


def solid(name, parts, mat, **kw):
    """One object from several extruded pieces."""
    verts, faces = [], []
    for part_verts, part_faces in parts:
        base = len(verts)
        verts += part_verts
        faces += [tuple(base + i for i in face) for face in part_faces]
    return new_object(name, verts, faces, None, mat, closed=True, **kw)


def slotted_head(name, r, h, mat, slot=0.0, **kw):
    """A cheese-head screw standing on its local Z=0, with a real slot across the top."""
    a = math.asin(0.18)                # the slot is 0.36 r wide
    t = math.radians(slot)
    parts = [extruded(ring_pts(r), 0.0, 0.55 * h)]
    for side in (0.0, math.pi):
        angles = [t + side + a + (math.pi - 2 * a) * i / 12 for i in range(13)]
        parts.append(extruded([(r * math.cos(b), r * math.sin(b)) for b in angles], 0.55 * h, h))
    return solid(name, parts, mat, **kw)


def knurled(name, r, z0, z1, mat, teeth=30, depth=0.4, **kw):
    """A knurled rim: a disc with a toothed edge."""
    pts = []
    for i in range(teeth):
        for k, rr in ((0.0, r), (0.5, r - depth)):
            a = 2 * math.pi * (i + k) / teeth
            pts.append((rr * math.cos(a), rr * math.sin(a)))
    return solid(name, [extruded(pts, z0, z1)], mat, smooth=None, **kw)


def strap(points, w, steps=6):
    """Outline of a flat bar of half-width w along a path of (x, y) points.

    The ends are rounded, and so is the outside of each bend.
    """
    def half(path):
        out = []
        for i in range(len(path) - 1):
            d = (path[i + 1] - path[i]).normalized()
            left = Vector((-d.y, d.x))
            if i == 0:
                out.append(path[0] + left * w)
                continue
            d0 = (path[i] - path[i - 1]).normalized()
            left0 = Vector((-d0.y, d0.x))
            if d0.x * d.y - d0.y * d.x < 0.0:          # turning right: this side is the outside
                a0, a1 = math.atan2(left0.y, left0.x), math.atan2(left.y, left.x)
                if a1 > a0:
                    a1 -= 2 * math.pi
                for s in range(steps + 1):
                    a = a0 + (a1 - a0) * s / steps
                    out.append(path[i] + w * Vector((math.cos(a), math.sin(a))))
            else:                                       # the inside of the bend: one mitred point
                m = (left0 + left).normalized()
                out.append(path[i] + m * (w / max(0.3, m.dot(left))))
        d = (path[-1] - path[-2]).normalized()
        a0 = math.atan2(d.x, -d.y)
        for s in range(2 * steps):
            a = a0 - math.pi * s / (2 * steps)
            out.append(path[-1] + w * Vector((math.cos(a), math.sin(a))))
        return out
    path = [Vector(p) for p in points]
    return [tuple(p) for p in half(path) + half(path[::-1])]


def engrave(name, text, size, loc, mat):
    """Flat lettering lying on a plate, read from the front. `loc` is the middle of its baseline."""
    curve = bpy.data.curves.new(name + "Text", "FONT")
    curve.body = text
    curve.size = size * S
    curve.align_x = "CENTER"
    curve.space_character = 1.18
    if os.path.exists(ENGRAVING_FONT):
        curve.font = bpy.data.fonts.load(ENGRAVING_FONT, check_existing=True)
    scratch = bpy.data.objects.new(name + "Text", curve)
    bpy.context.scene.collection.objects.link(scratch)
    bpy.context.view_layer.update()
    mesh = bpy.data.meshes.new_from_object(scratch.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(scratch)
    mesh.name = name
    mesh.materials.clear()
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = Vector(loc) * S
    return ob


def flush_screw(name, x, y, z, slot):
    """A countersunk brass screw, its head just proud of the plate, its slot dark."""
    r = 2.7
    lathe(name, [(0, z), (r, z), (r, z + 0.1), (r - 0.35, z + 0.3), (0, z + 0.3)], BRASS, segs=32, closed=True, loc=(x, y, 0.0))
    c, s = math.cos(math.radians(slot)), math.sin(math.radians(slot))
    strip = [(c * u - s * v, s * u + c * v) for u, v in ((-0.9 * r, -0.3), (0.9 * r, -0.3), (0.9 * r, 0.3), (-0.9 * r, 0.3))]
    solid(name + "Slot", [extruded(strip, z + 0.29, z + 0.33)], ENGRAVE, loc=(x, y, 0.0), smooth=None)


def ball_pillar(name, x, y, z_ball, z_top):
    """A turned pillar on the movement plate: socket, taper, the ball that holds a pivot, and a neck."""
    z0, sock = MECH_TOP, 16.0
    prof = [(0, z0), (5.5, z0), (5.5, z0 + sock - 0.8), (5.0, z0 + sock), (4.3, z0 + sock + 0.3)]
    prof += ball_pts(z_ball, BALL_R, 2.7, 3.0)
    prof += [(3.0, z_top), (0, z_top)]
    return lathe(name, prof, BRASS, segs=40, closed=True, loc=(x, y, 0.0))


def pivot_screw(name, x, y, z, out, long=True):
    """The blackened screw that carries an arbor's point, entering a pillar's ball from outside.

    `out` is +1 or -1: which way along Y the screw sticks out.
    """
    rot = (-90.0 * out, 0.0, 0.0)
    start = BALL_R - 0.4
    if not long:
        slotted_head(name, 2.0, 1.5, BLACK, slot=25.0, loc=(x, y + out * start, z), rot=rot)
        return
    thread = [(1.5 if i % 2 == 0 else 1.15, start + 0.3 * i) for i in range(10)]
    lathe(name + "Thread", [(0, start)] + thread + [(0, start + 2.8)], BLACK, segs=20, closed=True, loc=(x, y, z), rot=rot)
    slotted_head(name, 2.0, 3.4, BLACK, slot=25.0, loc=(x, y + out * (start + 2.7), z), rot=rot)


def swing(v, angle):
    """Turn an (x, z) offset about +Y, the way every arbor here turns."""
    return (v[0] * math.cos(angle) + v[1] * math.sin(angle), -v[0] * math.sin(angle) + v[1] * math.cos(angle))


def lever_angle(pen_angle):
    """The top lever's turn for a turn of the pen arbor: the link between them keeps its length.

    scene.ts poses the page by the same rule.
    """
    crank = swing(CRANK_PIN, pen_angle)
    vx, vz = PIVOT[0] + crank[0] - TOP_ARBOR[0], PIVOT[2] + crank[1] - TOP_ARBOR[1]
    reach, span = math.hypot(*LEVER_PIN), math.hypot(vx, vz)
    spread = math.acos((reach ** 2 + span ** 2 - LINK ** 2) / (2.0 * reach * span))
    base = math.atan2(LEVER_PIN[1], LEVER_PIN[0]) - math.atan2(vz, vx)
    return min((base - spread, base + spread), key=abs)


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
BRASS_SATIN = make_metal("BrassSatin", (0.80, 0.55, 0.20), 0.30, vary=0.05, scale=40.0)
BLACK = make_metal("BlackSteel", (0.09, 0.09, 0.10), 0.34)
METALS = (BRASS, BRASS_BRIGHT, BRASS_SATIN, NICKEL, STEEL, BLUED, BLACK)
ENGRAVE = make_plain("Engraving", (0.015, 0.012, 0.010), 0.7)
EBONITE = make_plain("Ebonite", (0.012, 0.012, 0.014), 0.25)
INK_GLASS = make_plain("InkGlass", (0.012, 0.012, 0.035), 0.03)
# The page cannot show clear glass inside the case, so the thermometer is an
# enamel-backed tube (opaque white) and the ink bottle is full to the neck.
THERMO_WHITE, THERMO_RED = (0.80, 0.78, 0.70), (0.45, 0.012, 0.02)       # scene.ts must agree
THERMO_GLASS = make_plain("ThermoGlass", THERMO_WHITE, 0.08)
THERMO_SPIRIT = make_plain("ThermoSpirit", THERMO_RED, 0.06)
thermo_deg = 90.0 - (THERMO_F0_DEG + (THERMO_F140_DEG - THERMO_F0_DEG) * ARGS.temp / 140.0)
THERMO_TUBE = make_thermo("ThermoTube", (thermo_deg - THERMO_SWEEP[0]) / (THERMO_SWEEP[1] - THERMO_SWEEP[0]))

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

# Bed plate: the polished floor of the case. On it, the satin plate that carries the movement.
box("BedPlate", (0.0, 0.0, PLATE_TOP - 3.0), (264.0, 136.0, 6.0), BRASS_BRIGHT, bevel=1.0)
box("MechPlate", ((MECH_X[0] + MECH_X[1]) / 2.0, (MECH_Y[0] + MECH_Y[1]) / 2.0, (PLATE_TOP + MECH_TOP) / 2.0),
    (MECH_X[1] - MECH_X[0], MECH_Y[1] - MECH_Y[0], MECH_TOP - PLATE_TOP), BRASS_SATIN, bevel=0.6)
for n, (x, y, turn) in enumerate(((-24.0, -57.0, 20.0), (114.0, -57.0, 75.0), (114.0, 53.0, 140.0), (45.0, 53.5, 5.0),
                                  (-25.0, 54.0, 100.0))):
    flush_screw(f"PlateScrew{n}", x, y, MECH_TOP, turn)
engrave("EngravedName", "MOUNT SOLEDAD", 3.4, (DIAL_C[0], -58.6, MECH_TOP + 0.04), ENGRAVE)
engrave("EngravedPlace", "LA JOLLA", 2.6, (DIAL_C[0], -62.5, MECH_TOP + 0.04), ENGRAVE)

# Drum: turns about its own Z. Chart U runs with time, anticlockwise seen from above.
drum = empty("Drum", (DRUM_X, DRUM_Y, 0.0))
drum.rotation_euler = Euler((0.0, 0.0, math.radians(-90.0 - 360.0 * CHART_NOW_HOURS / 168.0)))
paper_top = PAPER_Z0 + PAPER_H
lathe("DrumBody", [(0, PAPER_Z0 - 2.0), (DRUM_R - 0.4, PAPER_Z0 - 2.0), (DRUM_R - 0.4, paper_top), (0, paper_top)],
      BRASS, closed=True, parent=drum)
lathe("DrumFlange", [(0, PAPER_Z0 - 3.5), (DRUM_R + 2.0, PAPER_Z0 - 3.5), (DRUM_R + 2.0, PAPER_Z0 - 0.6),
                     (DRUM_R + 1.2, PAPER_Z0), (0, PAPER_Z0)], BRASS, closed=True, parent=drum)
# The lid: a rolled rim, a shallow dome, and the knurled nut that holds it down.
lid_z, rim = paper_top - 0.5, DRUM_R + 2.2
dome_r = rim - 4.2
lid = [(0, lid_z), (rim - 0.6, lid_z), (rim, lid_z + 0.6), (rim, lid_z + 2.6), (rim - 0.5, lid_z + 3.4),
       (rim - 1.6, lid_z + 3.8), (rim - 3.0, lid_z + 3.4)]
lid += [(dome_r * (1.0 - i / 16.0), lid_z + 3.0 + 4.0 * (1.0 - (1.0 - i / 16.0) ** 2)) for i in range(17)]
lathe("DrumLid", lid, BRASS, closed=True, parent=drum)
nut_z = lid_z + 6.8
lathe("DrumNut", [(0, nut_z), (5.4, nut_z), (5.4, nut_z + 1.2), (4.2, nut_z + 1.8), (2.6, nut_z + 2.4), (2.6, nut_z + 4.6),
                  (5.6, nut_z + 5.2), (5.6, nut_z + 9.0), (5.0, nut_z + 9.9), (2.5, nut_z + 10.5), (0, nut_z + 10.7)],
      BRASS, segs=48, closed=True, parent=drum)
knurled("DrumNutRim", 7.0, nut_z + 5.4, nut_z + 9.0, BRASS, teeth=40, parent=drum)
lathe("ChartPaper", [(PAPER_R, PAPER_Z0), (PAPER_R, paper_top)], PAPER, segs=128, uv="cyl", parent=drum, smooth=60.0)
# The clip that holds the chart's two ends, at the seam. It goes round with the
# paper on the page.
clip = empty("ChartClip", (0.0, 0.0, 0.0), parent=drum)
prism("ClipBar", [(-2.0, PAPER_Z0), (2.0, PAPER_Z0), (2.0, lid_z), (-2.0, lid_z)], 1.0, BRASS,
      (PAPER_R + 0.25, 0.0, 0.0), (0, 1, 0), (0, 0, 1), parent=clip, bevel=0.25)
turned("ClipKnob", [(0, 0.0), (1.2, 0.0), (1.2, 2.2)] + ball_pts(4.6, 2.4, 1.2, 0.0), BRASS, "x",
       loc=(PAPER_R + 0.6, 0.0, lid_z - 3.0), segs=24, parent=clip)
knurled("DrumGear", 31.0, PLATE_TOP + 2.5, PLATE_TOP + 4.5, BRASS, teeth=96, depth=0.9, parent=drum)
lathe("DrumSpindle", [(0, PLATE_TOP), (5.0, PLATE_TOP), (5.0, PAPER_Z0 - 3.0), (0, PAPER_Z0 - 3.0)], BRASS, segs=32,
      closed=True, parent=drum)

# Aneroid stack: seven sealed capsules joined at their centres.
stack_z0, pitch, cap_r, boss_r, count = MECH_TOP + 3.0, 6.6, 27.0, 5.0, 7
lathe("StackPedestal", [(0, MECH_TOP), (11.0, MECH_TOP), (11.0, MECH_TOP + 1.2), (7.0, MECH_TOP + 2.0), (7.0, stack_z0),
                        (0, stack_z0)], BRASS, segs=48, closed=True, loc=(STACK_XY[0], STACK_XY[1], 0.0))
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
lathe("StackBoss", [(0, stack_top - 1.2), (4.6, stack_top - 1.2), (4.6, stack_top + 0.6), (2.4, stack_top + 1.2),
                    (2.4, stack_top + 2.0), (0, stack_top + 2.0)], BRASS, segs=32, closed=True,
      loc=(STACK_XY[0], STACK_XY[1], 0.0))

# ---- The movement ------------------------------------------------------------
# Rising pressure squeezes the stack, which pulls the short end of the top lever
# down; the long end rises and lifts the link, the link lifts the crank on the
# pen arbor, and the pen rises. The page poses TopLever, Link, StackPost,
# PenArbor and PenArm by the same rule, finding the pins by name.
dz = (ARGS.pressure - 29.5) / 3.0 * CHART_GRID
pen_angle = math.asin(dz / PEN_ARM)
top_angle = lever_angle(pen_angle)

tall_top, low_top = TOP_ARBOR[1] + 9.5, PIVOT[2] + 9.5
for label, x, z, ys, top in (("Tall", TOP_ARBOR[0], TOP_ARBOR[1], TALL_Y, tall_top), ("Low", PIVOT[0], PIVOT[2], LOW_Y, low_top)):
    for n, y in enumerate(ys):
        ball_pillar(f"{label}Pillar{n}", x, y, z, top)
        slotted_head(f"{label}BarScrew{n}", 2.6, 2.2, BLACK, slot=35.0 + 70.0 * n, loc=(x, y, top + 4.5))
    box(f"{label}Bar", (x, (ys[0] + ys[1]) / 2.0, top + 2.25), (9.0, ys[1] - ys[0] + 13.0, 4.5), BRASS, bevel=0.35)
pivot_screw("TallPivot0", TOP_ARBOR[0], TALL_Y[0], TOP_ARBOR[1], -1)
pivot_screw("TallPivot1", TOP_ARBOR[0], TALL_Y[1], TOP_ARBOR[1], 1)
pivot_screw("LowPivot0", PIVOT[0], LOW_Y[0], PIVOT[2], -1, long=False)   # the dial stands close in front of it
pivot_screw("LowPivot1", PIVOT[0], LOW_Y[1], PIVOT[2], 1)


def arbor(name, y0, y1, parent, cone0=5.0, cone1=5.0):
    """A steel arbor along Y, running on a point at each end."""
    return turned(name, [(0, y0), (0.25, y0), (1.5, y0 + cone0), (1.5, y1 - cone1), (0.25, y1), (0, y1)], STEEL, "y",
                  segs=20, parent=parent)


# Top lever: its arbor, the boss on it, the long turned arm to the link and the short arm to the stack.
lever = empty("TopLever", (TOP_ARBOR[0], LEVER_Y, TOP_ARBOR[1]), rot=(0.0, math.degrees(top_angle), 0.0))
tip = BALL_R - 1.3                     # an arbor's point reaches this far short of the ball's centre
arbor("TopArbor", TALL_Y[0] + tip - LEVER_Y, TALL_Y[1] - tip - LEVER_Y, lever)
turned("LeverBoss", [(0, -4.6), (3.4, -4.6), (4.3, -3.9), (4.3, 3.9), (3.4, 4.6), (0, 4.6)], BRASS, "y", parent=lever)
fork = LEVER_PIN[0] - 4.5              # where the slotted end begins
long_arm = [(0, 3.0), (2.5, 3.0), (2.5, 22.0), (3.3, 22.4), (3.3, 23.6), (2.8, 24.2)]
long_arm += ball_pts(29.5, 4.6, 2.8, 2.8) + [(2.8, 34.8), (3.3, 35.4), (3.3, 36.6), (2.7, 37.0), (2.7, fork), (0, fork)]
turned("LeverArm", long_arm, BRASS, "x", parent=lever)
gap = math.asin(0.55 / 2.7)
cheeks = []
for side in (0.0, math.pi):
    angles = [side + gap + (math.pi - 2 * gap) * i / 12 for i in range(13)]
    cheeks.append(extruded([(2.7 * math.cos(a), 2.7 * math.sin(a)) for a in angles], 0.0, 7.7))
solid("LeverFork", cheeks, BRASS, loc=(fork, 0.0, 0.0), rot=(0, 90, 0), parent=lever)
rod("LeverPinRod", (LEVER_PIN[0], -3.0, LEVER_PIN[1]), (LEVER_PIN[0], 3.0, LEVER_PIN[1]), 0.55, STEEL, segs=12, parent=lever)
turned("LeverShortArm", [(0, 3.0), (1.5, 3.0), (1.5, 8.0), (2.1, 8.3), (2.1, 9.5), (1.5, 9.8),
                         (1.5, -STACK_PIN[0] + 1.6), (0, -STACK_PIN[0] + 2.0)], BRASS, "-x", segs=20, parent=lever)
empty("LeverPin", (LEVER_PIN[0], 0.0, LEVER_PIN[1]), parent=lever)
empty("StackPin", (STACK_PIN[0], 0.0, STACK_PIN[1]), parent=lever)

# The post on top of the stack, and the wire and yoke that hang it from the short arm.
post = empty("StackPost", (STACK_XY[0], STACK_XY[1], stack_top + swing(STACK_PIN, top_angle)[1]))
rise = TOP_ARBOR[1] - stack_top
lathe("PostStem", [(0, -2.5), (1.0, -2.5), (1.0, 2.6), (2.2, 2.6), (2.2, 3.2), (1.0, 3.2), (1.0, 7.2), (2.2, 7.2), (2.2, 7.8),
                   (1.0, 7.8), (1.0, rise - 6.5), (0.45, rise - 6.1), (0.45, rise - 1.6), (0, rise - 1.6)], STEEL, segs=16,
      closed=True, parent=post)
knurled("PostNut", 2.8, 3.2, 7.2, BRASS, teeth=18, depth=0.35, parent=post)
box("PostYoke", (0.0, 0.0, rise), (3.2, 4.4, 4.4), BRASS, bevel=0.3, parent=post)

# Pen arbor: everything that turns with the pen. PenArm, inside it, is the part the lifter swings off the paper.
pen_arbor = empty("PenArbor", PIVOT, rot=(0.0, math.degrees(pen_angle), 0.0))
arm = empty("PenArm", (0.0, 0.0, 0.0), parent=pen_arbor)
crank_y = LEVER_Y - PIVOT[1]           # the crank and the link work in the top lever's plane
arbor("PenArborRod", LOW_Y[0] + tip - PIVOT[1], LOW_Y[1] - tip - PIVOT[1], pen_arbor, cone0=3.0)
turned("PenNut", [(0, -1.7), (2.2, -1.7), (2.8, -1.3), (2.8, 0.3), (0, 0.3)], BRASS, "y", segs=24, parent=pen_arbor)
prism("PenCarrier", [(-21.0, -2.2), (-8.0, -3.4), (8.0, -3.4), (17.0, -2.2), (17.0, 2.2), (8.0, 3.4), (-8.0, 3.4), (-21.0, 2.2)],
      1.2, BRASS, (0.0, 1.5, 0.0), (1, 0, 0), (0, 0, 1), parent=pen_arbor, smooth=None, bevel=0.2)
turned("PenHub", [(0, 1.5), (4.4, 1.5), (4.4, 4.2), (3.6, 4.8), (2.4, 12.0), (0, 12.0)], BRASS, "y", parent=pen_arbor)
slotted_head("PenTailScrew", 1.7, 1.4, BLACK, slot=60.0, loc=(12.5, 0.3, 0.0), rot=(90, 0, 0), parent=pen_arbor)
turned("CrankBoss", [(0, crank_y - 4.3)] + ball_pts(crank_y, 4.3, 1.5, 1.5, steps=14) + [(0, crank_y + 4.3)], BRASS, "y",
       parent=pen_arbor)
prism("CrankArm", strap([(0.0, 0.0), CRANK_PIN], 1.9), 2.0, BRASS, (0.0, crank_y - 0.4, 0.0), (1, 0, 0), (0, 0, 1),
      parent=pen_arbor, smooth=40.0, bevel=0.25)
rod("CrankPinRod", (CRANK_PIN[0], crank_y - 2.8, CRANK_PIN[1]), (CRANK_PIN[0], crank_y + 0.9, CRANK_PIN[1]), 0.55, STEEL,
    segs=12, parent=pen_arbor)
empty("CrankPin", (CRANK_PIN[0], crank_y, CRANK_PIN[1]), parent=pen_arbor)

# The pen: a thin steel blade that runs right to the writing point, where its
# end is bent at a right angle toward the paper and tipped with ink.
blade_end = -PEN_ARM - 0.25
prism("PenArmBlade", [(-9.0, -3.2), (-9.0, 3.2), (blade_end, 1.0), (blade_end, -1.0)], 0.5, STEEL, (0.0, 0.25, 0.0),
      (1, 0, 0), (0, 0, 1), parent=arm, smooth=None)
slotted_head("PenBladeScrew", 1.9, 1.3, BRASS, slot=15.0, loc=(-15.0, -0.25, 0.0), rot=(90, 0, 0), parent=arm)
box("PenSleeve", (-PEN_ARM + 5.5, 0.0, 0.0), (2.4, 1.1, 2.6), STEEL, bevel=0.15, parent=arm)
# The bent tip, in the plane across the blade: from the blade (y = 0) out to the paper (y = 3.4), tapering.
prism("PenNib", [(-0.25, -1.0), (2.6, -0.45), (2.6, 0.45), (-0.25, 1.0)], 0.5, STEEL, (blade_end, 0.0, 0.0),
      (0, 1, 0), (0, 0, 1), parent=arm, smooth=None)
prism("PenInk", [(2.6, -0.45), (3.4, -0.25), (3.4, 0.25), (2.6, 0.45)], 0.5, INK, (blade_end, 0.0, 0.0),
      (0, 1, 0), (0, 0, 1), parent=arm, smooth=None)

# The link between the top lever's slotted end and the crank.
lever_end, crank_end = swing(LEVER_PIN, top_angle), swing(CRANK_PIN, pen_angle)
link_at = (TOP_ARBOR[0] + lever_end[0], LEVER_Y, TOP_ARBOR[1] + lever_end[1])
link_dx, link_dz = PIVOT[0] + crank_end[0] - link_at[0], PIVOT[2] + crank_end[1] - link_at[2]
link = empty("Link", link_at, rot=(0.0, math.degrees(math.atan2(-link_dx, -link_dz)), 0.0))
prism("LinkStrip", strap([(0.0, 0.0), (0.0, -LINK)], 1.25), 0.5, BLUED, (0.0, 0.25, 0.0), (1, 0, 0), (0, 0, 1), parent=link,
      smooth=40.0)

# Pen lifter: a lever on the plate that swings about its stud, so the rod at its
# end pushes the pen arm off the paper. The page swings it; here it is at rest.
lifter = empty("PenLifter", (LIFTER[0], LIFTER[1], MECH_TOP))
lift_rod, lift_knob = (-16.0, 7.5), (12.0, -7.0)
lathe("LifterWasher", [(0, 0.0), (4.4, 0.0), (4.4, 0.8), (0, 0.8)], BRASS, segs=32, closed=True, parent=lifter)
prism("LifterFoot", strap([lift_rod, (0.0, 0.0), lift_knob], 3.3), 2.2, BRASS, (0.0, 0.0, 0.8), (1, 0, 0), (0, 1, 0),
      parent=lifter, smooth=40.0, bevel=0.3)
slotted_head("LifterStud", 3.0, 1.8, BRASS, slot=70.0, loc=(0.0, 0.0, 3.0), parent=lifter)
rod_top = 208.0 - MECH_TOP
lathe("LifterRod", [(0, 3.0), (1.9, 3.0), (1.9, 4.0), (1.1, 4.6)] + ball_pts(rod_top, 1.7, 1.1, 0.0), BRASS, segs=20,
      closed=True, loc=(lift_rod[0], lift_rod[1], 0.0), parent=lifter)
lathe("LifterKnob", [(0, 3.0), (1.5, 3.0), (1.5, 5.4)] + ball_pts(8.0, 3.1, 1.5, 0.0), BRASS, segs=24, closed=True,
      loc=(lift_knob[0], lift_knob[1], 0.0), parent=lifter)

# The knurled knob that sets the stack's height, and so the pen's zero.
kx, ky, kz = 112.0, 20.0, MECH_TOP
lathe("ZeroKnob", [(0, kz), (4.0, kz), (4.0, kz + 1.0), (2.6, kz + 1.6), (2.6, kz + 5.0), (5.6, kz + 5.6), (5.6, kz + 9.6),
                   (4.6, kz + 10.4), (1.2, kz + 11.0), (0, kz + 11.6)], BRASS, segs=40, closed=True, loc=(kx, ky, 0.0))
knurled("ZeroKnobRim", 6.3, kz + 5.8, kz + 9.4, BRASS, teeth=36, loc=(kx, ky, 0.0))

# Ink well: a bottle of ink in a brass cup, with its stopper and dropper knob.
ix, iy, iz = INK_WELL[0], INK_WELL[1], MECH_TOP
lathe("InkCup", [(0, iz), (9.5, iz), (9.5, iz + 1.2), (8.2, iz + 1.9), (7.5, iz + 2.8), (7.5, iz + 31.0), (7.9, iz + 31.3),
                 (7.9, iz + 32.0), (6.6, iz + 32.0), (0, iz + 32.0)], BRASS, segs=48, closed=True, loc=(ix, iy, 0.0))
lathe("InkBottle", [(0, iz + 31.5), (6.5, iz + 31.5), (6.5, iz + 37.0), (5.6, iz + 39.2), (4.0, iz + 40.4), (4.0, iz + 45.0),
                    (4.9, iz + 45.4), (4.9, iz + 46.6), (0, iz + 46.6)], INK_GLASS, segs=40, closed=True, loc=(ix, iy, 0.0))
lathe("InkStopper", [(0, iz + 46.4), (3.3, iz + 46.4), (3.8, iz + 48.0), (3.8, iz + 51.0), (2.2, iz + 53.0), (0, iz + 53.0)],
      EBONITE, segs=32, closed=True, loc=(ix, iy, 0.0))
lathe("InkKnob", [(0, iz + 52.8), (1.3, iz + 52.8), (1.3, iz + 57.5)] + ball_pts(iz + 60.5, 3.0, 1.3, 0.0), BRASS, segs=24,
      closed=True, loc=(ix, iy, 0.0))

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
    lathe(f"DialPillar_{int(dx)}", pillar_profile(MECH_TOP, DIAL_C[2] + 30.0, r=3.0), BRASS, segs=48, closed=True,
          loc=(DIAL_C[0] + dx, DIAL_C[1] + 9.0, 0.0))
    rod(f"DialStud_{int(dx)}", (DIAL_C[0] + dx, DIAL_C[1] + 9.0, DIAL_C[2] + 22.0), (DIAL_C[0] + dx, DIAL_C[1], DIAL_C[2] + 22.0),
        1.6, BRASS, segs=16)

# Thermometer along the bottom of the dial: an enamel-backed tube with a red
# spirit column. U runs along the tube from the bulb, and the page moves the
# end of the column by sliding a two-colour texture along it.
tube_r, tube_w = 0.80 * DIAL_R, 1.5
lathe("ThermoTube", [(tube_r + tube_w * math.cos(math.radians(t)), 1.2 + tube_w + tube_w * math.sin(math.radians(t)))
                     for t in range(0, 361, 30)], THERMO_TUBE, segs=96, sweep=THERMO_SWEEP, uv="cyl", parent=dial, smooth=60.0)
for label, deg, mat, r in (("Bulb", THERMO_SWEEP[0], THERMO_SPIRIT, 2.7), ("Tip", THERMO_SWEEP[1], THERMO_GLASS, tube_w)):
    a = math.radians(deg)
    lathe("Thermo" + label, [(0, -r)] + [(r * math.cos(math.radians(t)), r * math.sin(math.radians(t))) for t in range(-60, 61, 30)]
          + [(0, r)], mat, segs=24, closed=True, parent=dial, loc=(tube_r * math.cos(a), tube_r * math.sin(a), 1.2 + tube_w),
          smooth=60.0)

# What the page moves must leave nothing behind in the bake: no shadow on the
# paper where the pen was, no dark patch on the plate where the lifter stood.
MOVING = ("ChartClip", "PenArbor", "TopLever", "Link", "StackPost", "PenLifter")
for ob in scene.objects:
    node = ob
    while node is not None and node.name not in MOVING:
        node = node.parent
    if node is not None:
        ob.visible_shadow = False

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
         "front": (0.0, 9.0, 1150.0, 80.0, (0.0, 0.0, 132.0)),
         "right": (-58.0, 12.0, 1500.0, 85.0, (40.0, 0.0, 70.0)),
         "mech": (-35.0, 22.0, 520.0, 50.0, (50.0, -5.0, 158.0)),
         "mech_left": (35.0, 28.0, 520.0, 50.0, (25.0, 0.0, 158.0)),
         "mech_back": (150.0, 25.0, 520.0, 50.0, (45.0, 0.0, 158.0)),
         "mech_top": (0.0, 80.0, 600.0, 50.0, (30.0, 0.0, 140.0)),
         "pen": (40.0, 18.0, 260.0, 60.0, (-95.0, -42.0, 168.0))}
yaw, elev, dist, lens, target = VIEWS[ARGS.view]
cam_data.lens = lens
yaw_r, elev_r = math.radians(yaw), math.radians(elev)
cam.location = (Vector(target) + dist * Vector((-math.sin(yaw_r) * math.cos(elev_r), -math.cos(yaw_r) * math.cos(elev_r),
                                                math.sin(elev_r)))) * S
aim(cam, target)

if ARGS.bare:
    for ob in scene.objects:
        if ob.name.startswith(("Glass", "Post_", "Rail")):
            ob.hide_render = True

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
    light.png holds the diffuse light arriving at each point (no surface colour;
    metal takes none, so its part of the atlas is left black),
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
    lit_targets = [ob for ob in targets if ob.data.materials[0] not in METALS]
    aim_materials(lit_targets, light)
    select(lit_targets)
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"}, margin=margin, use_clear=True, uv_layer="Light")
    lit = read_pixels(light, size)
    print("light map: max", float(lit.max()), "mean", float(lit.mean()))
    save_png("light", srgb_encode(lit / LIGHT_SCALE), size, out_dir)

    ao = bpy.data.images.new("ao", size, size, alpha=False, float_buffer=True, is_data=True)
    aim_materials(targets, ao)
    select(targets)
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
