"""Checkpoint images: what was detected, drawn on the gel, for review before
the final figure is trusted."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from .imaging import load_gray
from .render import _font

NO_BAND = "No band"


def _stretch(a: np.ndarray, lo_p=1.0, hi_p=99.5, gamma=0.6) -> np.ndarray:
    lo, hi = np.percentile(a, lo_p), np.percentile(a, hi_p)
    return (np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) ** gamma * 255).astype(np.uint8)


def overlay(g: dict, out_path: str) -> str:
    """Whole gel with comb rows, numbered lanes, lane centre lines and ladder calls."""
    a = load_gray(g["image"], g.get("invert", False))
    x0, y0, x1, y1 = g["box"]
    gel = a[y0:y1, x0:x1]
    lo, hi = np.percentile(gel, 1), np.percentile(gel, 99.7)
    im = Image.fromarray((np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) ** 0.7 * 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(im)
    f = _font("semibold", 18)
    fs = _font("medium", 15)
    for row in g["rows"]:
        dd = row["spacing"]
        for ln in row["lanes"]:
            if ln.get("use_as_ladder"):
                col = (0, 220, 90)
            elif ln.get("mismatch"):
                col = (255, 60, 60)
            elif ln.get("type") == "unloaded":
                col = (120, 120, 120)
            else:
                col = (90, 170, 255)
            x, y = ln["well_x"], ln["well_y"]
            d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=col, width=2)
            y2 = row["y_end"]
            d.line([(ln["x0"] + ln["slant"] * (row["y_start"] - ln["y0"]), row["y_start"]),
                    (ln["x0"] + ln["slant"] * (y2 - ln["y0"]), y2)], fill=col, width=1)
            tag = str(ln["well"]) if ln.get("well") else f"#{ln['index']}"
            d.text((x - fs.getlength(tag) / 2, y - 0.9 * dd), tag, font=fs, fill=col)
        for k, call in row.get("ladders", {}).items():
            ln = row["lanes"][int(k) - 1]
            for s, b in call["bands"].items():
                if b["y"] is None or b["status"] == "merged":
                    continue
                xc = ln["x0"] + ln["slant"] * (b["y"] - ln["y0"])
                col = (0, 220, 90) if b["status"] in ("anchor", "detected") else (255, 200, 0)
                d.line([(xc - 0.45 * dd, b["y"]), (xc + 0.45 * dd, b["y"])], fill=col, width=1)
                d.text((xc + 0.5 * dd, b["y"] - 9), str(s), font=fs, fill=col)
        d.text((g["box"][0] + 5, min(ln["well_y"] for ln in row["lanes"]) - 1.6 * dd),
               f"row {row['index']}: {row['n_wells']} wells", font=f, fill=(255, 255, 255))
    im.save(out_path)
    return out_path


def lane_strips(g: dict, row: dict, out_path: str, calls: list[dict] | None = None) -> str:
    """Every lane of a row cut out along its own centre line and set side by
    side, so slanted lanes read straight. Calls (if given) are marked."""
    a = load_gray(g["image"], g.get("invert", False))
    dd = row["spacing"]
    ys = np.arange(row["y_start"] - 0.4 * dd, row["y_end"], 1.0)
    lanes = [ln for ln in row["lanes"] if ln.get("type") != "unloaded" or ln.get("ladder_like")]
    W = int(round(dd))
    blocks = []
    for ln in lanes:
        xs = ln["x0"] + ln["slant"] * (ys - ln["y0"])
        blocks.append(np.array([ndi.map_coordinates(a, [ys, xs + dx], order=1, mode="nearest")
                                for dx in np.arange(-W / 2, W / 2)]).T)
    img = np.hstack(blocks)
    top = 70
    im = Image.new("RGB", (img.shape[1], img.shape[0] + top), "white")
    im.paste(Image.fromarray(_stretch(img, 1, 99.0)).convert("RGB"), (0, top))
    d = ImageDraw.Draw(im)
    f = _font("semibold", 15)
    fs = _font("medium", 13)
    cm = {(c["row"], c["lane"]): c for c in (calls or []) if c["gel"] == g["name"]}
    for i, ln in enumerate(lanes):
        x = i * W
        d.text((x + 3, 4), str(ln.get("well") or f"#{ln['index']}"), font=f, fill=(30, 30, 30))
        kind = {"ladder": "L", "nc": "NC", "pc": "PC", "empty": "NA", "unloaded": "-"}.get(ln.get("type"), "")
        if kind:
            d.text((x + 3, 24), kind, font=fs, fill=(80, 80, 80))
        c = cm.get((row["index"], ln["index"]))
        if c and c["call"] != NO_BAND and c.get("band_y") is not None:
            yy = c["band_y"] - ys[0] + top
            col = (255, 60, 60) if c["call"] == "Band" else (255, 190, 0)
            d.line([(x + 1, yy), (x + 6, yy)], fill=col, width=3)
            d.line([(x + W - 6, yy), (x + W - 1, yy)], fill=col, width=3)
            d.text((x + 3, 44), f"{c['size_bp']}", font=fs, fill=col)
        d.line([(x, top), (x, im.height)], fill=(60, 60, 60), width=1)
    im.save(out_path)
    return out_path


def ladder_sheet(g: dict, out_path: str) -> str:
    """Each calibrating ladder straightened and magnified with its size calls."""
    a = load_gray(g["image"], g.get("invert", False))
    f = _font("medium", 18)
    tiles = []
    for row in g["rows"]:
        dd = row["spacing"]
        for k, call in row.get("ladders", {}).items():
            ln = row["lanes"][int(k) - 1]
            ys_b = [b["y"] for b in call["bands"].values() if b["y"] is not None]
            if not ys_b:
                continue
            top, bot = int(min(ys_b) - 25), int(max(ys_b) + 35)
            ys = np.arange(top, bot, 1.0)
            xs = ln["x0"] + ln["slant"] * (ys - ln["y0"])
            W = int(0.5 * dd)
            crop = np.array([ndi.map_coordinates(a, [ys, xs + dx], order=1) for dx in range(-W, W + 1)]).T
            z = 3
            t = Image.fromarray(_stretch(crop, 2, 99.5, 0.55)).resize((crop.shape[1] * z, crop.shape[0] * z),
                                                                     Image.BICUBIC).convert("RGB")
            tile = Image.new("RGB", (t.width + 150, t.height + 36), "white")
            tile.paste(t, (0, 36))
            d = ImageDraw.Draw(tile)
            d.text((4, 6), f"row {row['index']} lane {k}", font=f, fill=(0, 0, 0))
            merged = call.get("merged") or []
            for s, b in call["bands"].items():
                if b["y"] is None or b["status"] == "merged":
                    continue
                yy = (b["y"] - top) * z + 36
                col = (200, 0, 0) if b["status"] in ("anchor", "detected") else (0, 90, 220)
                d.line([(t.width - 18, yy), (t.width + 8, yy)], fill=col, width=2)
                txt = "/".join(str(m) for m in merged) if merged and int(s) == merged[0] else str(s)
                d.text((t.width + 12, yy - 11), txt + ("" if b["status"] != "interpolated" else " (i)"),
                       font=f, fill=col)
            tiles.append(tile)
    if not tiles:
        Image.new("RGB", (400, 60), "white").save(out_path)
        return out_path
    W = sum(t.width for t in tiles) + 10 * len(tiles)
    H = max(t.height for t in tiles)
    out = Image.new("RGB", (W, H), (230, 230, 230))
    x = 0
    for t in tiles:
        out.paste(t, (x, 0))
        x += t.width + 10
    out.save(out_path)
    return out_path
