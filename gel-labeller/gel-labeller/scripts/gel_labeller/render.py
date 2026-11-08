"""Draw the labelled gel figure from a layout (and optional band calls)."""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import ladders as ladders_mod

NO_BAND = "No band"

# --------------------------------------------------------------------------- style
_INTER = "/usr/share/fonts/opentype/inter/"


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    inter = {"regular": "Inter-Regular.otf", "medium": "Inter-Medium.otf",
             "semibold": "Inter-SemiBold.otf", "bold": "Inter-Bold.otf"}[weight]
    if os.path.exists(_INTER + inter):
        return ImageFont.truetype(_INTER + inter, size)
    try:
        import matplotlib
        base = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        name = "DejaVuSans-Bold.ttf" if weight in ("semibold", "bold") else "DejaVuSans.ttf"
        return ImageFont.truetype(os.path.join(base, name), int(size * 0.92))
    except Exception:
        return ImageFont.load_default()


TARGET_PALETTE = [(29, 78, 216), (194, 65, 12), (21, 128, 61), (126, 34, 206),
                  (15, 118, 110), (190, 24, 93), (133, 77, 14), (71, 85, 105)]
FIXED = {"nc": (185, 28, 28), "pc": (161, 98, 7), "ladder": (40, 40, 40),
         "empty": (150, 150, 150), "unloaded": (150, 150, 150), "sample": (30, 30, 30)}
GUIDE = (255, 214, 0, 120)
TEXT = (35, 35, 35)
MUTED = (110, 110, 110)

MARGIN = 40          # outer margin (px)
SIDE = 150           # side margin that holds the size scales
TITLE_H = 120
NOTE_LINE = 36
SIZE_GAP = 20
HEAD_PAD = 60        # space for well numbers and ticks under the labels


def target_colours(layout: dict) -> dict[str, tuple]:
    seen = []
    for g in layout["gels"]:
        for row in g["rows"]:
            for ln in row["lanes"]:
                t = ln.get("target")
                if t and t not in seen:
                    seen.append(t)
    for t in layout.get("targets") or []:
        if t not in seen:
            seen.append(t)
    return {t: TARGET_PALETTE[i % len(TARGET_PALETTE)] for i, t in enumerate(seen)}


def lane_colour(ln: dict, tcol: dict) -> tuple:
    if ln.get("type") in ("sample", "pc") and ln.get("target") in tcol:
        return tcol[ln["target"]]
    return FIXED.get(ln.get("type"), FIXED["sample"])


def rotated_text(text: str, font, colour) -> Image.Image:
    l, t, r, b = font.getbbox(text)
    im = Image.new("RGBA", (r - l + 4, b - t + 8), (255, 255, 255, 0))
    ImageDraw.Draw(im).text((2 - l, 4 - t), text, font=font, fill=tuple(colour) + (255,))
    return im.rotate(90, expand=True)


def dashed(draw, p0, p1, dash=14, gap=10, fill=GUIDE, width=2):
    (xa, ya), (xb, yb) = p0, p1
    L = ((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5
    if L == 0:
        return
    n = int(L // (dash + gap)) + 1
    for i in range(n):
        s0 = i * (dash + gap) / L
        s1 = min(1, (i * (dash + gap) + dash) / L)
        if s0 >= 1:
            break
        draw.line([(xa + s0 * (xb - xa), ya + s0 * (yb - ya)),
                   (xa + s1 * (xb - xa), ya + s1 * (yb - ya))], fill=fill, width=width)


def spread(ys, gap, lo, hi):
    """Label positions as close to ys as possible, at least `gap` apart, inside [lo, hi]."""
    clusters = [[y] for y in ys]

    def start(c):
        return sum(c) / len(c) - (len(c) - 1) * gap / 2

    merged = True
    while merged:
        merged, out = False, []
        for c in clusters:
            if out and start(out[-1]) + len(out[-1]) * gap > start(c):
                out[-1] = out[-1] + c
                merged = True
            else:
                out.append(c)
        clusters = out
    pos = [start(c) + i * gap for c in clusters for i in range(len(c))]
    n = len(pos)
    for i in range(n):
        pos[i] = max(pos[i], lo + i * gap)
    for i in range(n - 1, -1, -1):
        pos[i] = min(pos[i], hi - (n - 1 - i) * gap)
    return pos


def wrap(text: str, font, width: float) -> list[str]:
    out, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if font.getlength(trial) > width and line:
            out.append(line)
            line = word
        else:
            line = trial
    if line:
        out.append(line)
    return out


# --------------------------------------------------------------------------- geometry
def _row_strip(g: dict, r_i: int) -> tuple[int, int]:
    rows = g["rows"]
    row = rows[r_i]
    d = row["spacing"]
    top = min(ln["well_y"] for ln in row["lanes"]) - 0.9 * d
    if r_i > 0:
        prev = rows[r_i - 1]
        top = max(top, min(ln["well_y"] for ln in row["lanes"]) - 0.45 * d, prev["y_end"])
    if r_i + 1 < len(rows):
        nxt = rows[r_i + 1]
        bottom = min(ln["well_y"] for ln in nxt["lanes"]) - 0.45 * nxt["spacing"]
        bottom = max(bottom, row["y_end"])
    else:
        bottom = min(row["y_end"] + 0.6 * d, g["size"][1])
    return int(max(0, top)), int(min(g["size"][1], bottom))


def _row_shear(row: dict) -> float:
    tr = [ln["slant"] for ln in row["lanes"] if ln.get("tracked")]
    return float(np.mean(tr)) if tr else float(row.get("shear", 0.0))


def should_straighten(g: dict, mode: str) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False
    return any(abs(_row_shear(r)) > 0.035 for r in g["rows"])   # about 2 degrees


# --------------------------------------------------------------------------- figure
def render_gel(g: dict, layout: dict, out_path: str, calls: list[dict] | None = None,
               straighten: str = "auto", mark_bands: bool = False) -> str:
    lad = ladders_mod.load(layout["ladder"]["id"], layout["ladder"].get("catalogue"),
                           layout["ladder"].get("lot"))
    tcol = target_colours(layout)
    f_label = _font("semibold", 31)
    f_num = _font("medium", 23)
    f_cap = _font("semibold", 30)
    f_title = _font("bold", 44)
    f_leg = _font("medium", 27)
    f_note = _font("regular", 25)
    f_size = _font("medium", 19)
    f_size_b = _font("bold", 19)

    src = Image.open(g["image"]).convert("RGB")
    if g.get("invert"):
        src = Image.eval(src, lambda v: 255 - v)
    W_img, H_img = src.size
    bx0, _, bx1, _ = g["box"]
    pad = int(0.03 * (bx1 - bx0))
    cx0, cx1 = max(0, bx0 - pad), min(W_img, bx1 + pad)
    strip_w = cx1 - cx0
    straight = should_straighten(g, straighten)
    call_map = {}
    for c in calls or []:
        if c["gel"] == g["name"]:
            call_map[(c["row"], c["lane"])] = c

    # longest label decides header height
    longest = max([f_label.getlength(ln.get("label") or "") for r in g["rows"] for ln in r["lanes"]] + [60])
    head_h = int(longest + HEAD_PAD + 50)
    strips = []
    for r_i, row in enumerate(g["rows"]):
        ya, yb = _row_strip(g, r_i)
        strips.append((row, ya, yb))

    notes = list(_figure_notes(g, layout, lad, straight))
    W = strip_w + 2 * SIDE
    note_lines = []
    for n in notes:
        note_lines += wrap(n, f_note, W - 2 * MARGIN)
    used_t = []
    types = set()
    for r in g["rows"]:
        for ln in r["lanes"]:
            types.add(ln.get("type"))
            if ln.get("target") and ln.get("type") in ("sample", "pc") and ln["target"] not in used_t:
                used_t.append(ln["target"])
    legend = [(tcol[t], t) for t in used_t]
    if "sample" in types and any(ln.get("type") == "sample" and not ln.get("target")
                                 for r in g["rows"] for ln in r["lanes"]):
        legend.append((FIXED["sample"], "Sample"))
    if "pc" in types:
        legend.append((FIXED["pc"], "Pos. control"))
    if "nc" in types:
        legend.append((FIXED["nc"], "Neg. control"))
    legend.append((FIXED["ladder"], "Ladder"))
    if "empty" in types:
        legend.append((FIXED["empty"], "NA / empty"))
    placed, lx, ly = [], MARGIN, 84
    for col, txt in legend:
        wtxt = 28 + int(f_leg.getlength(txt)) + 34
        if lx + wtxt > W - MARGIN:
            lx, ly = MARGIN, ly + 36
        placed.append((lx, ly, col, txt))
        lx += wtxt
    top_h = TITLE_H + (ly - 84)
    H = top_h + sum(head_h + (yb - ya) for _, ya, yb in strips) + (len(note_lines) * NOTE_LINE + 40)
    canvas = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(canvas)
    wells = [ln["well"] for r in g["rows"] for ln in r["lanes"] if ln.get("well")]
    title = g["name"] + (f"  (wells {min(wells)}-{max(wells)})" if wells else "")
    d.text((MARGIN, 26), title, font=f_title, fill=(20, 20, 20))
    for lx, ly, col, txt in placed:
        d.rectangle([lx, ly + 4, lx + 20, ly + 24], fill=col)
        d.text((lx + 28, ly), txt, font=f_leg, fill=(50, 50, 50))
    y = top_h

    for row, ya, yb in strips:
        dd = row["spacing"]
        lanes = [ln for ln in row["lanes"] if ln.get("type") != "unloaded" or ln.get("ladder_like")]
        shear = _row_shear(row) if straight else 0.0
        yref = float(np.mean([ln["well_y"] for ln in row["lanes"]]))

        def tx(x, yy):          # image coords -> canvas x
            return x - shear * (yy - yref) - cx0 + SIDE

        hb = y + head_h
        cap = f"Row {row['index']}" + (f", wells {min(w for w in [ln.get('well') for ln in lanes] if w)}-"
                                       f"{max(w for w in [ln.get('well') for ln in lanes] if w)}"
                                       if any(ln.get("well") for ln in lanes) else "")
        d.text((MARGIN, y + 8), cap, font=f_cap, fill=(90, 90, 90))
        for ln in lanes:
            X = tx(ln["x0"], ln["y0"])
            col = lane_colour(ln, tcol)
            d.line([(X, hb - 12), (X, hb - 2)], fill=(120, 120, 120), width=2)
            if ln.get("well"):
                num = str(ln["well"])
                d.text((X - f_num.getlength(num) / 2, hb - 42), num, font=f_num, fill=MUTED)
            rt = rotated_text(ln.get("label") or "", f_label, col)
            canvas.paste(rt, (int(X - rt.width / 2), int(hb - 50 - rt.height)), rt)
        strip = src.crop((cx0, ya, cx1, yb))
        if shear:
            yr = yref - ya
            strip = strip.transform(strip.size, Image.AFFINE, (1, shear, -shear * yr, 0, 1, 0),
                                    resample=Image.BICUBIC, fillcolor=(0, 0, 0))
        canvas.paste(strip, (SIDE, hb))
        # lane guides: boundaries between neighbouring lane centre lines
        ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        y_top = max(ln["well_y"] for ln in row["lanes"]) + 0.5 * dd
        y_bot = yb - 10

        def cx_at(ln, yy):
            return ln["x0"] + ln["slant"] * (yy - ln["y0"])

        for k in range(len(lanes) + 1):
            pts = []
            for yy in (y_top, y_bot):
                if k == 0:
                    xx = cx_at(lanes[0], yy) - dd / 2
                elif k == len(lanes):
                    xx = cx_at(lanes[-1], yy) + dd / 2
                else:
                    xx = (cx_at(lanes[k - 1], yy) + cx_at(lanes[k], yy)) / 2
                pts.append((tx(xx, yy), yy - ya + hb))
            dashed(od, pts[0], pts[1])
        canvas = Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(canvas)
        # band markers
        if mark_bands:
            for ln in lanes:
                c = call_map.get((row["index"], ln["index"]))
                if not c or c["call"] == NO_BAND or c.get("band_y") is None:
                    continue
                by = c["band_y"]
                X = tx(cx_at(ln, by), by)
                yy = by - ya + hb
                col = (255, 255, 255) if c["call"] == "Band" else (255, 214, 0)
                for sgn in (-1, 1):
                    xa = X + sgn * 0.42 * dd
                    d.line([(xa, yy - 7), (xa, yy + 7)], fill=col, width=3)
        # ladder size scales
        canvas = _draw_scales(canvas, row, lad, ya, hb, yb - ya, tx, cx_at, strip_w, f_size, f_size_b)
        d = ImageDraw.Draw(canvas)
        y = hb + (yb - ya)

    ny = y + 18
    for line in note_lines:
        d.text((MARGIN, ny), line, font=f_note, fill=(70, 70, 70))
        ny += NOTE_LINE
    canvas = canvas.crop((0, 0, W, min(canvas.height, ny + 20)))
    canvas.save(out_path)
    return out_path


def _draw_scales(canvas, row, lad, ya, hb, strip_h, tx, cx_at, strip_w, f_size, f_size_b):
    lad_lanes = [ln for ln in row["lanes"] if ln.get("use_as_ladder") and str(ln["index"]) in row.get("ladders", {})]
    if not lad_lanes:
        return canvas
    n = len(row["lanes"])
    left = [ln for ln in lad_lanes if ln["index"] <= (n + 1) / 2]
    right = [ln for ln in lad_lanes if ln["index"] > (n + 1) / 2]
    sides = []
    if left:
        sides.append((min(left, key=lambda l: l["index"]), "left"))
    if right:
        sides.append((max(right, key=lambda l: l["index"]), "right"))
    bold = set(lad.primary)
    for ln, side in sides:
        call = row["ladders"][str(ln["index"])]
        merged = call.get("merged") or []
        items = []
        for s in lad.sizes:
            b = call["bands"].get(str(s)) or call["bands"].get(s)
            if not b or b["y"] is None or b["status"] in ("missing",):
                continue
            if b["status"] == "merged" or not (ya + 4 <= b["y"] <= ya + strip_h - 4):
                continue
            txt = "/".join(str(m) for m in merged) if merged and s == merged[0] else str(s)
            items.append((s, b["y"], txt))
        if not items:
            continue
        band_y = [hb + (yy - ya) for _, yy, _ in items]
        lab_y = spread(band_y, SIZE_GAP, hb + 40, hb + strip_h - 14)
        edge = SIDE if side == "left" else SIDE + strip_w
        sgn = -1 if side == "left" else 1
        ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        dd = row["spacing"]
        for (s, yy, _), by in zip(items, band_y):
            X = tx(cx_at(ln, yy), yy)
            x_end = X - 0.38 * dd if side == "left" else X + 0.38 * dd
            od.line([(edge, by), (x_end, by)], fill=(255, 255, 255, 105), width=1)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(canvas)
        for (s, yy, txt), by, ly in zip(items, band_y, lab_y):
            d.line([(edge + sgn * 1, by), (edge + sgn * 8, by), (edge + sgn * 34, ly), (edge + sgn * 40, ly)],
                   fill=(120, 120, 120), width=2)
            f = f_size_b if s in bold else f_size
            tw = f.getlength(txt)
            tx_ = edge - 44 - tw if side == "left" else edge + 44
            d.text((tx_, ly - 12), txt, font=f, fill=TEXT)
        hx = edge - 44 - f_size.getlength("bp") if side == "left" else edge + 44
        d.text((hx, lab_y[0] - 36), "bp", font=f_size, fill=MUTED)
    return canvas


def _figure_notes(g, layout, lad, straight):
    notes = []
    desc = lad.describe()
    bold = " and ".join(f"{s}" for s in lad.primary)
    notes.append(f"Ladder: {desc}. Sizes in bp; bold marks the {bold} bp reference bands.")
    merged = set()
    missing = set()
    for r in g["rows"]:
        for call in r.get("ladders", {}).values():
            if call.get("merged"):
                merged.add(tuple(call["merged"]))
            for s, b in call["bands"].items():
                if b["status"] == "missing":
                    missing.add(int(s))
    for m in merged:
        notes.append(f"The {' and '.join(str(x) for x in m)} bp ladder bands are not resolved on this gel; "
                     f"they run together as one band, labelled {'/'.join(str(x) for x in m)}.")
    if missing:
        notes.append("Ladder bands not found on this gel: " + ", ".join(f"{s} bp" for s in sorted(missing, reverse=True)) + ".")
    for r in g["rows"]:
        for ln in r["lanes"]:
            if ln.get("mismatch"):
                notes.append(f"* Row {r['index']}, lane {ln['index']}: {ln['mismatch']}")
    for n in g.get("notes", []):
        notes.append(n)
    if straight:
        ang = max(abs(_row_shear(r)) for r in g["rows"])
        notes.append(f"The lanes on this gel ran at a slant of about {np.degrees(np.arctan(ang)):.0f} degrees. "
                     f"Each row has been straightened with a horizontal shear so every band sits under its own "
                     f"label; nothing else in the image was changed.")
    return notes
