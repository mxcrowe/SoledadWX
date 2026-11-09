"""Record Blender's view transform as a lookup table for the web page.

The page should show the same colours as a Blender render. Rather than
re-derive Blender's AgX curve and contrast look in a shader, this passes a
grid of colours through Blender's own colour management and saves the answers.

  E:\\Graphics\\Blender\\blender.exe --background --factory-startup --python make_view_lut.py -- --out PATH

The table is N x N x N (N = 48), saved as an N*N by N strip of sRGB values.
Each axis is log2 of a linear-sRGB channel, from LO to HI stops. Exposure is
not baked in: the page applies it before the lookup. tonemap.ts must agree
with N, LO and HI.
"""
import argparse
import os
import sys

import bpy
import numpy as np

N = 48
LO, HI = -12.5, 4.5                    # log2 of scene-linear value
VIEW, LOOK = "AgX", "AgX - Medium High Contrast"

parser = argparse.ArgumentParser()
parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tex", "view_lut.png"))
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

axis = np.power(2.0, LO + (HI - LO) * np.arange(N) / (N - 1)).astype(np.float32)
# Strip layout: x = red + blue * N, y = green. Blender's rows run bottom to top,
# so green is reversed here to put green index 0 on the file's top row.
pixels = np.ones((N, N * N, 4), dtype=np.float32)
for b in range(N):
    block = pixels[:, b * N:(b + 1) * N, :]
    block[..., 0] = axis[None, :]
    block[..., 1] = axis[::-1, None]
    block[..., 2] = axis[b]

img = bpy.data.images.new("view_lut", N * N, N, alpha=False, float_buffer=True)
img.pixels.foreach_set(pixels.ravel())
scene = bpy.context.scene
scene.view_settings.view_transform = VIEW
scene.view_settings.look = LOOK
scene.view_settings.exposure = 0.0
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.image_settings.color_depth = "8"
scene.render.image_settings.compression = 60
img.save_render(os.path.abspath(args.out), scene=scene)
print("wrote", os.path.abspath(args.out), f"({VIEW}, {LOOK}, {N}^3, stops {LO}..{HI})")
