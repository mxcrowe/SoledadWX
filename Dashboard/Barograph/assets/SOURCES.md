# Barograph assets: sources

All from Poly Haven (https://polyhaven.com), licence CC0. Downloaded 2026-11-09.
The image files are not in git; fetch them again from the links if needed.

In use:

- `rosewood_veneer1_diff_8k.jpg`, `rosewood_veneer1_nor_gl_8k.jpg`: the case wood
  (asset `rosewood_veneer1`, a 2.43 m scan; https://polyhaven.com/a/rosewood_veneer1).

Kept as alternatives, not used by the default build:

- `rosewood_veneer1_rough_8k.jpg`: roughness map; it is a flat value, so the build ignores it.
- `oak_veneer_01_*_2k.jpg`: oak colour, normal and roughness (asset `oak_veneer_01`, a 1.83 m scan);
  used by `build_barograph.py --wood oak`.
- `studio_small_08_2k.hdr`: a photographed studio (asset `studio_small_08`). The build lights
  the scene with its own `make_studio_env.py` instead.
