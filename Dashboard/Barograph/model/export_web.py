"""Export the barograph for the Monitor page.

Run with the system Python (needs Pillow):  python export_web.py
Writes soledadwx-ui/public/barograph/: the model, the studio lighting, and
web-sized textures. Set BLENDER to override the Blender path.
"""
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
DEST = HERE.parents[2] / "soledadwx-ui" / "public" / "barograph"
BLENDER = os.environ.get("BLENDER", "E:/Graphics/Blender/blender.exe")
WOOD_PX = 4096


def blender(script, *args):
    cmd = [BLENDER, "--background", "--factory-startup", "--python", str(HERE / script), "--", *args]
    done = subprocess.run(cmd, capture_output=True, text=True)
    for line in done.stdout.splitlines():
        if line.startswith(("baked", "light map", "exported", "wrote")):
            print(line)
    if done.returncode != 0 or "Traceback" in done.stderr + done.stdout:
        raise SystemExit(done.stdout[-3000:] + done.stderr[-3000:])


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    blender("build_barograph.py", "--bake", str(DEST), "--export", str(DEST / "barograph.glb"))
    blender("make_studio_env.py", "--out", str(DEST / "studio_env.hdr"), "--width", "1024")
    blender("make_view_lut.py", "--out", str(DEST / "view_lut.png"))
    Image.MAX_IMAGE_PIXELS = None
    for src, dst, quality in (("rosewood_veneer1_diff_8k.jpg", "wood_diff.jpg", 88),
                              ("rosewood_veneer1_nor_gl_8k.jpg", "wood_normal.jpg", 90)):
        Image.open(ASSETS / src).resize((WOOD_PX, WOOD_PX), Image.LANCZOS).save(DEST / dst, quality=quality)
    for name in ("dial.png", "chart_placeholder.png"):
        shutil.copyfile(HERE / "tex" / name, DEST / name)
    for f in sorted(DEST.iterdir()):
        print(f"{f.stat().st_size / 1e6:7.2f} MB  {f.name}")


if __name__ == "__main__":
    main()
