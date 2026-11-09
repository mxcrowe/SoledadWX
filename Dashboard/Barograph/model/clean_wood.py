"""Remove the small light flecks from the rosewood scan.

The scan has a few pale specks (dust or filler in the veneer). At half scale
on the case they read as marks on the polish. This finds spots much lighter
than the grain around them and fills them from their surroundings.

Run with the system Python (Pillow, numpy, scipy):  python clean_wood.py
Output: tex/wood_diff_clean.jpg, which build_barograph.py and export_web.py use.
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "assets" / "rosewood_veneer1_diff_8k.jpg"
OUT = HERE / "tex" / "wood_diff_clean.jpg"

# A fleck is far lighter than the wood's broad colour: the lightest real grain
# sits about 30 above it, flecks 50 or more. Comparing with nearby grain
# instead would also catch the pale gaps between dark lines.
LIFT = 50.0          # luminance (0..255) above the broad colour
BROAD = 40.0         # blur radius (pixels) for the wood's broad colour
MAX_AREA = 400       # pixels; anything larger is grain, not a fleck
FILL = 6.0           # blur radius (pixels) used to fill a fleck from around it


def main():
    Image.MAX_IMAGE_PIXELS = None
    rgb = np.asarray(Image.open(SOURCE).convert("RGB")).astype(np.float32)
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    around = ndimage.gaussian_filter(lum, BROAD)
    candidate = (lum - around) > LIFT
    labels, count = ndimage.label(candidate)
    areas = ndimage.sum(candidate, labels, index=np.arange(1, count + 1))
    keep = np.zeros(count + 1, dtype=bool)
    keep[1:] = areas <= MAX_AREA
    flecks = ndimage.binary_dilation(keep[labels], iterations=2)

    # Fill each fleck from the surrounding pixels only (normalised blur that ignores the fleck).
    weight = (~flecks).astype(np.float32)
    filled = np.empty_like(rgb)
    w = ndimage.gaussian_filter(weight, FILL)
    for c in range(3):
        filled[..., c] = ndimage.gaussian_filter(rgb[..., c] * weight, FILL) / np.maximum(w, 1e-4)
    out = np.where(flecks[..., None], filled, rgb)

    OUT.parent.mkdir(exist_ok=True)
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(OUT, quality=95)
    print(f"{int(keep.sum())} flecks, {int(flecks.sum())} pixels filled -> {OUT}")


if __name__ == "__main__":
    main()
