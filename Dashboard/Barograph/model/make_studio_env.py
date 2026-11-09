"""Paint the barograph's lighting: a dark studio with a few softboxes.

One equirectangular HDR image lights both the Blender render and the web
page, so the two can be compared like for like. Run with Blender's Python:

  E:\\Graphics\\Blender\\blender.exe --background --factory-startup --python make_studio_env.py

Output: tex/studio_env.hdr (2048 x 1024). After `--`: --out PATH, --width N.

Directions are given from the instrument: azimuth in degrees from the front
of the case toward its right, elevation up from the table.
"""
import argparse
import math
import os
import sys

import bpy
import numpy as np

_p = argparse.ArgumentParser()
_p.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tex", "studio_env.hdr"))
_p.add_argument("--width", type=int, default=2048)
_a = _p.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
W, H = _a.width, _a.width // 2
OUT = os.path.abspath(_a.out)

ZENITH = (0.030, 0.030, 0.032)        # dark ceiling
HORIZON = (0.110, 0.104, 0.096)       # dim walls: what vertical brass sees
# Below the horizon is the table, lit green, as the case's sides see it nearby.
TABLE_NEAR = (0.014, 0.056, 0.038)

# name, azimuth, elevation, half width, half height (degrees), radiance, colour
SOFTBOXES = [
    ("key", -38.0, 48.0, 26.0, 18.0, 14.0, (1.00, 0.94, 0.86)),
    ("front key", 32.0, 24.0, 20.0, 13.0, 7.0, (1.00, 0.95, 0.89)),
    ("ceiling", 0.0, 62.0, 60.0, 30.0, 0.5, (1.00, 0.97, 0.93)),
    ("strip right", 62.0, 18.0, 5.0, 30.0, 9.0, (0.95, 0.97, 1.00)),
    ("strip left", -100.0, 15.0, 4.0, 28.0, 4.0, (1.00, 0.97, 0.92)),
    ("back wall", 180.0, 22.0, 55.0, 16.0, 0.9, (1.00, 0.93, 0.84)),
    ("top", 0.0, 88.0, 30.0, 20.0, 2.0, (1.00, 0.97, 0.93)),
    ("front fill", 15.0, 2.0, 50.0, 14.0, 0.22, (1.00, 0.96, 0.90)),
]


def direction(az_deg, el_deg):
    az, el = math.radians(az_deg), math.radians(el_deg)
    return np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])


def smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def main():
    # Blender's equirect layout: u = atan2(y, -x) / 2pi + 0.5, v = elevation / pi + 0.5; row 0 is the bottom.
    u = (np.arange(W) + 0.5) / W
    v = (np.arange(H) + 0.5) / H
    phi, el = np.meshgrid((u - 0.5) * 2.0 * np.pi, (v - 0.5) * np.pi)
    d = np.stack([-np.cos(phi) * np.cos(el), np.sin(phi) * np.cos(el), np.sin(el)], axis=-1)

    img = np.empty((H, W, 3), dtype=np.float32)
    below = smoothstep(0.0, -0.06, d[..., 2])[..., None]
    high = smoothstep(0.0, 0.75, d[..., 2])[..., None]
    walls = np.array(HORIZON) * (1.0 - high) + np.array(ZENITH) * high
    # Below the horizon is the lit table. In Blender the real table hides this part
    # of the image; it matters only to the page's reflections, where a dark band
    # just under the horizon showed as a dark line across the case's sides. So the
    # table stays lit right up to the horizon.
    table = np.broadcast_to(np.array(TABLE_NEAR), img.shape)
    img[:] = walls * (1.0 - below) + table * below

    for _name, az, elev, half_w, half_h, radiance, colour in SOFTBOXES:
        c = direction(az, elev)
        right = np.cross(c, np.array([0.0, 0.0, 1.0]))
        if np.linalg.norm(right) < 1e-3:               # looking straight up
            right = np.array([1.0, 0.0, 0.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, c)
        facing = d @ c
        safe = np.where(facing > 1e-3, facing, 1.0)
        x = np.abs((d @ right) / safe) / math.tan(math.radians(half_w))
        y = np.abs((d @ up) / safe) / math.tan(math.radians(half_h))
        mask = (1.0 - smoothstep(0.82, 1.0, x)) * (1.0 - smoothstep(0.82, 1.0, y)) * (facing > 1e-3)
        # The table hides whatever part of a softbox hangs below the horizon.
        img += (mask * radiance)[..., None] * (1.0 - below) * np.array(colour, dtype=np.float32)

    out = bpy.data.images.new("studio_env", W, H, alpha=False, float_buffer=True)
    rgba = np.ones((H, W, 4), dtype=np.float32)
    rgba[..., :3] = img
    out.pixels.foreach_set(rgba.ravel())
    out.filepath_raw = OUT
    out.file_format = "HDR"
    out.save()
    print("wrote", OUT, "mean radiance", float(img.mean()))


main()
