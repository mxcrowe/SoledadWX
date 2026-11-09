"""Draw the barograph's printed surfaces: the dial face and a placeholder chart.

Our own artwork (the reference photo is used for proportions only).
Run with the system Python (needs Pillow):  python make_textures.py
Outputs: tex/dial.png, tex/chart_placeholder.png

The chart here is only a stand-in for Blender renders. In the app the chart
is painted live from the Archive.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "tex"
FONTS = Path("C:/Windows/Fonts")
INK = (26, 24, 22)

# Shared with build_barograph.py: keep these in step.
DIAL_DEG_PER_INHG = 66.0      # needle travel; 29.5 inHg is straight up
THERMO_F0_DEG = 236.0         # 0 F on the thermometer arc (clockwise from top)
THERMO_F140_DEG = 124.0       # 140 F
PEN_ARM_MM = 173.0            # pen arm length: sets the curve of the time lines
CHART_MM = (292.8, 97.0)      # paper length (one turn of the drum) and height
CHART_GRID_MM = 90.0          # 28.0 .. 31.0 inHg
CHART_TOP_MARGIN_MM = 5.0


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), int(round(size)))


def polar(c, r, deg):
    """Point at radius r, angle measured clockwise from 12 o'clock."""
    a = math.radians(deg)
    return (c + r * math.sin(a), c - r * math.cos(a))


def arc_text(img, c, text, fnt, r, deg_center, inward=False, fill=INK, tracking=0.0):
    """Set text along a circle. Baseline at radius r.

    Outward text (top of the dial) has glyph tops toward the rim and reads
    clockwise. Inward text (bottom of the dial) has tops toward the centre and
    reads anticlockwise, so it is upright at 6 o'clock.
    """
    widths = [fnt.getlength(ch) + tracking for ch in text]
    total = sum(widths) - tracking
    sign = -1.0 if inward else 1.0
    pos = -total / 2.0
    m = int(fnt.size * 3)
    for ch, w in zip(text, widths):
        mid = pos + (w - tracking) / 2.0
        deg = deg_center + sign * math.degrees(mid / r)
        g = Image.new("L", (m, m), 0)
        ImageDraw.Draw(g).text((m / 2, m / 2), ch, font=fnt, fill=255, anchor="ms")
        rot = (180.0 - deg) if inward else -deg
        g = g.rotate(rot, resample=Image.BICUBIC)
        x, y = polar(c, r, deg)
        img.paste(fill, (int(round(x - m / 2)), int(round(y - m / 2))), g)
        pos += w


def text_span_deg(text, fnt, r, tracking=0.0):
    total = sum(fnt.getlength(ch) + tracking for ch in text) - tracking
    return math.degrees(total / r)


def tick(d, c, r0, r1, deg, width, fill=INK):
    d.line([polar(c, r0, deg), polar(c, r1, deg)], fill=fill, width=int(round(width)))


def ring(d, c, r, deg0, deg1, width, fill=INK):
    """Arc from deg0 to deg1 (clockwise from top)."""
    d.arc([c - r, c - r, c + r, c + r], deg0 - 90.0, deg1 - 90.0, fill=fill, width=int(round(width)))


def make_dial(size=2048, ss=2):
    n = size * ss
    c = n / 2.0
    R = n / 2.0                       # texture edge = dial edge
    img = Image.new("RGB", (n, n), (234, 228, 210))
    d = ImageDraw.Draw(img)
    lw = n / 2048.0                   # 1 unit = 1 px at 2048

    # Border rules.
    ring(d, c, 0.990 * R, 0, 360, 3 * lw)
    ring(d, c, 0.525 * R, 0, 360, 2 * lw)

    # Pressure scale, 28 to 31 inHg.
    def p_deg(p):
        return (p - 29.5) * DIAL_DEG_PER_INHG

    ring(d, c, 0.765 * R, p_deg(27.97), p_deg(31.03), 2.5 * lw)
    ring(d, c, 0.745 * R, p_deg(27.97), p_deg(31.03), 2.5 * lw)
    small = font("COPRGTB.TTF", 0.050 * R)
    big = font("COPRGTB.TTF", 0.125 * R)
    for i in range(0, 61):            # every 0.05 inHg
        p = 28.0 + i * 0.05
        deg = p_deg(p)
        if i % 20 == 0:
            tick(d, c, 0.745 * R, 0.690 * R, deg, 6 * lw)
            arc_text(img, c, str(int(round(p))), big, 0.555 * R, deg)
        elif i % 10 == 0:
            tick(d, c, 0.745 * R, 0.690 * R, deg, 4 * lw)
            arc_text(img, c, "5", small, 0.650 * R, deg)
        elif i % 2 == 0:
            tick(d, c, 0.745 * R, 0.700 * R, deg, 3 * lw)
            arc_text(img, c, str((i // 2) % 10), small, 0.650 * R, deg)
        else:
            tick(d, c, 0.745 * R, 0.718 * R, deg, 2 * lw)

    # Weather words, spread evenly over the scale's arc.
    words = ["STORMY", "RAIN", "CHANGE", "FAIR", "VERY DRY"]
    wf = font("COPRGTB.TTF", 0.118 * R)
    rw = 0.812 * R
    trk = 0.006 * R
    spans = [text_span_deg(w, wf, rw, trk) for w in words]
    lo, hi = -103.0, 103.0
    gap = (hi - lo - sum(spans)) / (len(words) - 1)
    at = lo
    for w, s in zip(words, spans):
        arc_text(img, c, w, wf, rw, at + s / 2.0, tracking=trk)
        at += s + gap

    # Maker's line.
    arc_text(img, c, "MOUNT SOLEDAD", font("COPRGTL.TTF", 0.034 * R), 0.585 * R, 0.0, tracking=0.004 * R)

    # Thermometer along the bottom: Fahrenheit outside the tube, Centigrade inside.
    def f_deg(f):
        return THERMO_F0_DEG + (THERMO_F140_DEG - THERMO_F0_DEG) * f / 140.0

    tf = font("COPRGTB.TTF", 0.043 * R)
    lab = font("COPRGTB.TTF", 0.036 * R)
    for f in range(0, 141, 2):
        major = f % 10 == 0
        tick(d, c, 0.838 * R, (0.872 if major else 0.858) * R, f_deg(f), (3 if major else 2) * lw)
        if major:
            arc_text(img, c, str(f), tf, 0.925 * R, f_deg(f), inward=True)
    for cdeg in range(-10, 61, 1):
        f = cdeg * 1.8 + 32.0
        major = cdeg % 10 == 0
        mid = cdeg % 5 == 0
        tick(d, c, 0.762 * R, (0.730 if major else 0.740 if mid else 0.748) * R, f_deg(f), (3 if major else 2) * lw)
        if major:
            arc_text(img, c, str(abs(cdeg)), tf, 0.722 * R, f_deg(f), inward=True)
    arc_text(img, c, "CENTIGRADE", lab, 0.655 * R, 180.0, inward=True, tracking=0.004 * R)
    arc_text(img, c, "FAHRENHEIT", lab, 0.972 * R, 180.0, inward=True, tracking=0.004 * R)

    img = img.resize((size, size), Image.LANCZOS)
    img.save(OUT / "dial.png")


def placeholder_pressure(hours):
    """A plausible week of sea-level pressure, inHg."""
    out = []
    for h in hours:
        tide = 0.035 * math.cos(2 * math.pi * (h - 10) / 12.0)
        slow = 0.16 * math.sin(2 * math.pi * h / 110.0) + 0.03 * math.sin(2 * math.pi * h / 31.0 + 1.0)
        out.append(29.93 + slow + tide)
    return out


def make_chart(width=4096, ss=2, now_hours=82.0):
    """One week of paper, Monday to Sunday, inked up to `now_hours`."""
    mm_w, mm_h = CHART_MM
    n_w = width * ss
    px = n_w / mm_w                   # pixels per mm
    n_h = int(round(mm_h * px))
    paper = (243, 235, 214)
    img = Image.new("RGB", (n_w, n_h), paper)
    d = ImageDraw.Draw(img)
    red, red_bold = (205, 92, 88), (188, 60, 60)

    y_top = CHART_TOP_MARGIN_MM * px
    grid_h = CHART_GRID_MM * px
    y_mid = y_top + grid_h / 2.0

    def y_of(p):
        return y_top + (31.0 - p) / 3.0 * grid_h

    def x_of(hours, y):
        """Time lines bow like the pen's swing: a circle of the arm's radius."""
        h = (y - y_mid) / px
        return hours / 168.0 * n_w + (PEN_ARM_MM - math.sqrt(PEN_ARM_MM ** 2 - h * h)) * px

    # Pressure lines every 0.05 inHg.
    for i in range(0, 61):
        p = 28.0 + i * 0.05
        w = 4.6 if i % 20 == 0 else 3.2 if i % 10 == 0 else 2.0
        d.line([(0, y_of(p)), (n_w, y_of(p))], fill=red_bold if i % 10 == 0 else red, width=int(round(w * ss)))

    # Time lines every 2 hours.
    steps = [y_top + grid_h * k / 40.0 for k in range(41)]
    for h in range(0, 169, 2):
        w = 4.6 if h % 24 == 0 else 3.2 if h % 12 == 0 else 2.0
        d.line([(x_of(h, y), y) for y in steps], fill=red_bold if h % 12 == 0 else red, width=int(round(w * ss)))

    # Day names, hour numbers, pressure numbers.
    day_f = font("georgiaz.ttf", 3.3 * px)
    hour_f = font("georgia.ttf", 1.7 * px)
    num_f = font("georgiab.ttf", 3.4 * px)
    half_f = font("georgia.ttf", 2.2 * px)
    hour_labels = [(2, "2"), (4, "4"), (20, "8"), (22, "10")]
    for day, name in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]):
        d.text((x_of(day * 24 + 12, y_top), y_top - 0.6 * px), name, font=day_f, fill=red_bold, anchor="ms")
        for h, lab in hour_labels:
            d.text((x_of(day * 24 + h, y_top), y_top - 0.5 * px), lab, font=hour_f, fill=red, anchor="ms")
        for p in (28.5, 29.0, 29.5, 30.0, 30.5):
            whole = abs(p - round(p)) < 1e-6
            lab, f = (str(int(p)), num_f) if whole else ("5", half_f)
            y = y_of(p)
            x = x_of(day * 24 + 12, y)
            box = d.textbbox((x, y), lab, font=f, anchor="mm")
            d.rectangle([box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2], fill=paper)
            d.text((x, y), lab, font=f, fill=red_bold, anchor="mm")

    # The ink trace.
    hours = [i * 0.1 for i in range(int(now_hours * 10) + 1)]
    pts = [(x_of(h, y_of(p)), y_of(p)) for h, p in zip(hours, placeholder_pressure(hours))]
    d.line(pts, fill=(38, 34, 128), width=int(round(0.34 * px)), joint="curve")

    img = img.resize((width, int(round(n_h / ss))), Image.LANCZOS)
    img.save(OUT / "chart_placeholder.png")
    return placeholder_pressure(hours)[-1]


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    make_dial()
    p_now = make_chart()
    print(f"dial.png and chart_placeholder.png written; pressure at the pen: {p_now:.3f} inHg")
