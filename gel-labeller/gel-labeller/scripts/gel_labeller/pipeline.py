"""Detect step (image -> layout.json) and analysis step (layout -> calls)."""
from __future__ import annotations

import datetime as _dt
import os

import numpy as np

from . import __version__, ladders as ladders_mod, platemap
from .bands import (corrected_profile, find_lane_bands, ladder_profile, lateral, remove_bleed,
                    robust_noise, spans_lane)
from .detect import analyse_rows
from .imaging import gel_box, load_gray
from .ladder_fit import Calibration, call_ladder


# --------------------------------------------------------------------------- mapping
def _lane_set(lane: dict, e: platemap.Entry | None) -> None:
    if e is None:
        lane.update(well=None, sample="", label="", type="unloaded", target=None, replicate=None)
        return
    lane.update(well=e.well, sample=e.sample, label=e.label, type=e.type,
                target=e.target, replicate=e.replicate)


def _row_agreement(lanes, ents) -> float:
    sc = 0.0
    for ln, e in zip(lanes, ents):
        if e is None:
            sc -= 1.0 if ln["ladder_like"] else 0.0
            continue
        if e.type == "ladder":
            sc += 2.0 if ln["ladder_like"] else -2.0
        elif ln["ladder_like"]:
            sc -= 0.5 if e.type == "empty" else 2.0
    return sc


def map_lanes(gels: list[dict], entries: list[platemap.Entry], kind: str) -> list[str]:
    review: list[str] = []
    if kind == "full":
        idx = {}
        for e in entries:
            idx[(str(e.gel).strip().lower(), e.row, e.lane)] = e
        for g in gels:
            keys = {str(g["index"]), g["name"].lower(), os.path.splitext(os.path.basename(g["image"]))[0].lower()}
            for row in g["rows"]:
                for ln in row["lanes"]:
                    e = next((idx[(k, row["index"], ln["index"])] for k in keys
                              if (k, row["index"], ln["index"]) in idx), None)
                    _lane_set(ln, e)
        n_rows = {(str(e.gel).strip().lower(), e.row) for e in entries}
        found = {(k, r["index"]) for g in gels for r in g["rows"]
                 for k in {str(g["index"]), g["name"].lower()}}
        missing = [f"gel {gr[0]} row {gr[1]}" for gr in n_rows if gr not in found]
        if missing:
            review.append("The plate map lists lanes for " + ", ".join(sorted(missing)) +
                          ", but no such comb row was found in the image.")
        return review
    # running well numbers: fill rows in order, letting a row skip leading
    # empty wells when that makes the ladders line up with ladder-like lanes
    p = 0
    for g in gels:
        for row in g["rows"]:
            lanes = row["lanes"]
            best = None
            for skip in range(0, 4):
                if any(entries[q].type != "empty" for q in range(p, min(p + skip, len(entries)))):
                    break
                ents = [entries[p + skip + k] if p + skip + k < len(entries) else None
                        for k in range(len(lanes))]
                sc = _row_agreement(lanes, ents)
                if best is None or sc > best[0]:
                    best = (sc, skip, ents)
            sc, skip, ents = best
            if skip:
                skipped = [str(entries[q].well) for q in range(p, p + skip)]
                review.append(f"{g['name']} row {row['index']}: started at well {entries[p + skip].well} "
                              f"rather than {entries[p].well} so the ladders line up; well(s) "
                              f"{', '.join(skipped)} (NA in the plate map) have no lane. Confirm this.")
                g.setdefault("notes", []).append(
                    f"Well{'s' if skip > 1 else ''} {', '.join(skipped)} (NA in the plate map) "
                    f"{'have' if skip > 1 else 'has'} no lane on this gel.")
            for ln, e in zip(lanes, ents):
                _lane_set(ln, e)
            p += skip + sum(1 for e in ents if e is not None)
    if p < len(entries):
        left = [str(e.well) for e in entries[p:]]
        review.append("Plate map wells not placed on any gel: " + ", ".join(left) + ".")
    return review


def check_ladders(gels: list[dict]) -> list[str]:
    """Compare plate-map ladders with ladder-like lanes; decide which lanes
    calibrate sizes and mark mismatches with an asterisk."""
    review = []
    for g in gels:
        for row in g["rows"]:
            for ln in row["lanes"]:
                where = f"{g['name']} row {row['index']} lane {ln['index']}" + \
                        (f" (well {ln['well']})" if ln.get("well") else "")
                ln["use_as_ladder"] = False
                ln["mismatch"] = None
                if ln["type"] == "ladder" and ln["ladder_like"]:
                    ln["use_as_ladder"] = True
                elif ln["type"] == "ladder":
                    ln["mismatch"] = "The plate map says ladder, but no ladder pattern was found in this lane."
                    ln["label"] = "Ladder*"
                    review.append(f"{where}: plate map says ladder but the lane does not look like one.")
                elif ln["ladder_like"] and ln["type"] in ("empty", "unloaded"):
                    was = "NA" if ln["type"] == "empty" else "not loaded"
                    ln["use_as_ladder"] = True
                    ln["mismatch"] = (f"A ladder is visible in this lane, but the plate map lists "
                                      f"{'well ' + str(ln['well']) if ln.get('well') else 'this position'} "
                                      f"as {was}.")
                    ln["label"], ln["type"] = "Ladder*", "ladder"
                    review.append(f"{where}: a ladder ran here, but the plate map has it as {was}. "
                                  f"It is used as a ladder and labelled Ladder*. Confirm this.")
                elif ln["ladder_like"]:
                    ln["mismatch"] = "This lane looks like a ladder, but the plate map lists a sample here."
                    ln["label"] = ln["label"] + "*"
                    review.append(f"{where}: lane looks like a ladder but the plate map says "
                                  f"{ln['sample']}. Check the plate map or the lane order.")
    return review


# --------------------------------------------------------------------------- detect
def detect(images: list[str], plate_map: str, ladder_spec: str, names: list[str] | None = None,
           rows: list[int] | None = None, invert: bool = False, targets: list[str] | None = None,
           overrides: dict[int, str] | None = None, sheet=None, catalogue=None, lot=None,
           log=print) -> dict:
    lad = ladders_mod.load(ladder_spec, catalogue, lot)
    entries, kind = platemap.read(plate_map, sheet, targets, overrides)
    gels = []
    for gi, path in enumerate(images):
        name = names[gi] if names and gi < len(names) else f"Gel {gi + 1}"
        log(f"[{name}] reading {os.path.basename(path)}")
        a = load_gray(path, invert)
        box = gel_box(a)
        exp = rows[gi] if rows and gi < len(rows) else None
        if exp is None and kind == "full":
            mine = {e.row for e in entries if str(e.gel).strip().lower() in
                    (str(gi + 1), name.lower(), os.path.splitext(os.path.basename(path))[0].lower())}
            exp = max(mine) if mine else None
        rws = analyse_rows(a, box, exp)
        log(f"[{name}] {len(rws)} comb row(s): " +
            ", ".join(f"row {r['index']} {r['n_wells']} wells" for r in rws))
        gels.append(dict(index=gi + 1, name=name, image=os.path.abspath(path), invert=invert,
                         size=[int(a.shape[1]), int(a.shape[0])], box=[int(v) for v in box], rows=rws))
    review = map_lanes(gels, entries, kind)
    review += check_ladders(gels)
    review += _call_all_ladders(gels, lad)
    return dict(
        version=1, tool=f"gel-labeller {__version__}",
        created=_dt.datetime.now().isoformat(timespec="seconds"),
        plate_map=os.path.abspath(plate_map), plate_map_layout=kind,
        ladder=dict(id=lad.id, name=lad.name, catalogue=lad.catalogue, lot=lad.lot),
        targets=targets or [], overrides={str(k): v for k, v in (overrides or {}).items()},
        gels=gels, review=review)


def _call_all_ladders(gels: list[dict], lad) -> list[str]:
    review = []
    for g in gels:
        a = load_gray(g["image"], g.get("invert", False))
        merged_votes = []
        for row in g["rows"]:
            row["ladders"] = {}
            for ln in row["lanes"]:
                if not ln.get("use_as_ladder"):
                    continue
                call = call_ladder(a, ln, lad, row["spacing"], row["y_start"], row["y_end"])
                row["ladders"][str(ln["index"])] = call
                merged_votes.append(bool(call["merged"]))
                for f in call["flags"]:
                    if f.startswith("No ladder") or f.startswith("Reference") or "monotonic" in f:
                        review.append(f"{g['name']} row {row['index']} lane {ln['index']}: {f}")
            if not row["ladders"]:
                review.append(f"{g['name']} row {row['index']}: no usable ladder in this row; sizes "
                              f"will come from another row of the same gel.")
        # one decision per gel on whether the smallest ladder bands ran together
        if merged_votes:
            merge = sum(merged_votes) > len(merged_votes) / 2
            for row in g["rows"]:
                for call in row["ladders"].values():
                    _set_merge(call, lad, merge)
    return review


def recall_ladders(layout: dict) -> None:
    """Re-call ladder bands after the lane geometry in layout.json was edited."""
    lad = ladders_mod.load(layout["ladder"]["id"], layout["ladder"].get("catalogue"),
                           layout["ladder"].get("lot"))
    layout["review"] = [m for m in layout.get("review", []) if "ladder" not in m.lower()] + \
        _call_all_ladders(layout["gels"], lad)


def _set_merge(call: dict, lad, merge: bool) -> None:
    bands = call["bands"]
    found = [s for s in lad.sizes if bands[s]["status"] in ("anchor", "detected", "interpolated")]
    if not found:
        return
    smallest = min(found)
    below = [s for s in lad.sizes if s < smallest]
    if merge and below:
        for s in below:
            bands[s] = dict(y=bands[smallest]["y"], status="merged")
        call["merged"] = [smallest] + below
    else:
        for s in below:
            if bands[s]["status"] == "merged":
                bands[s] = dict(y=None, status="missing")
        call["merged"] = []
    call["flags"] = [f for f in call["flags"] if not f.startswith("Not found")]
    missing = [s for s in lad.sizes if bands[s]["status"] == "missing"]
    if missing:
        call["flags"].append("Not found: " + ", ".join(f"{s} bp" for s in missing) + ".")


# --------------------------------------------------------------------------- analyse
def _int_keys(call: dict) -> dict:
    return dict(call, bands={int(k): v for k, v in call["bands"].items()})


def row_calibrations(g: dict) -> dict[int, list[tuple[int, Calibration]]]:
    out = {}
    for row in g["rows"]:
        cals = []
        for k, call in row.get("ladders", {}).items():
            ln = row["lanes"][int(k) - 1]
            try:
                cals.append((int(k), Calibration(_int_keys(call), ln["well_y"])))
            except Exception:
                continue
        out[row["index"]] = sorted(cals, key=lambda c: c[0])
    return out


def size_at(cals: list[tuple[int, Calibration]], lane_index: int, mig: float) -> tuple[float | None, bool]:
    if not cals:
        return None, False
    if len(cals) == 1:
        c = cals[0][1]
        return 10 ** c.log_bp(mig), c.in_range(mig)
    left = [c for c in cals if c[0] <= lane_index]
    right = [c for c in cals if c[0] >= lane_index]
    kl, cl = (left[-1] if left else cals[0])
    kr, cr = (right[0] if right else cals[-1])
    if kl == kr:
        return 10 ** cl.log_bp(mig), cl.in_range(mig)
    f = (lane_index - kl) / (kr - kl)
    lb = (1 - f) * cl.log_bp(mig) + f * cr.log_bp(mig)
    return 10 ** lb, cl.in_range(mig) or cr.in_range(mig)


NO_BAND = "No band"

DEFAULTS = dict(min_product=200.0, band_snr=8.0, faint_snr=5.0, tolerance=0.1)


def analyse(layout: dict, min_product: float = DEFAULTS["min_product"],
            band_snr: float = DEFAULTS["band_snr"], faint_snr: float = DEFAULTS["faint_snr"],
            expected: dict[str, float] | None = None, tolerance: float = DEFAULTS["tolerance"]) -> dict:
    """Band calls for every non-ladder lane. Returns a dict with 'lanes' rows.

    A peak counts as a band only if it spans the lane (left, centre and right
    all brighter than just above and below it). It is called 'Band' when its
    height is at least band_snr times the row noise and it is compact
    (no taller than 0.6 lane widths), 'Faint' when it reaches faint_snr or
    is more diffuse. Features taller than one lane width are treated as
    smear, not bands."""
    lad = ladders_mod.load(layout["ladder"]["id"], layout["ladder"].get("catalogue"),
                           layout["ladder"].get("lot"))
    results = []
    for g in layout["gels"]:
        a = load_gray(g["image"], g.get("invert", False))
        cals_by_row = row_calibrations(g)
        for row in g["rows"]:
            d = row["spacing"]
            ys = np.arange(row["y_start"], row["y_end"], 1.0)
            cals = cals_by_row.get(row["index"]) or []
            borrowed = None
            if not cals:
                others = [(abs(r - row["index"]), r) for r, c in cals_by_row.items() if c]
                if others:
                    borrowed = min(others)[1]
                    cals = cals_by_row[borrowed]
            lad_lanes = {ln["index"]: ln for ln in row["lanes"] if ln.get("use_as_ladder")}
            lad_prof = {k: ladder_profile(a, ln, d, ys) for k, ln in lad_lanes.items()}
            profiles = {}
            for ln in row["lanes"]:
                if ln.get("use_as_ladder"):
                    continue
                side = "left" if (ln["index"] - 1) in lad_lanes else ("right" if (ln["index"] + 1) in lad_lanes else None)
                s, raw = corrected_profile(a, ln, d, ys, side)
                beta = 0.0
                lad_bands = []
                if side:
                    k = ln["index"] - 1 if side == "left" else ln["index"] + 1
                    call = row["ladders"].get(str(k))
                    if call:
                        band_ys = [b["y"] for b in call["bands"].values()
                                   if b["y"] is not None and b["status"] in ("anchor", "detected")]
                        s, beta = remove_bleed(s, lad_prof[k], ys, band_ys)
                        lad_bands = [(y, float(np.interp(y, ys, lad_prof[k]))) for y in band_ys]
                profiles[ln["index"]] = (s, raw, beta, side, lad_bands)
            if not profiles:
                continue
            noise = robust_noise(np.concatenate([v[0] for v in profiles.values()]))
            for ln in row["lanes"]:
                if ln["index"] not in profiles:
                    continue
                s, raw, beta, side, lad_bands = profiles[ln["index"]]
                found = find_lane_bands(ys, s, raw, noise, d, min_snr=faint_snr)
                bands, ignored = [], []
                for b in found:
                    mig = b["y"] - ln["well_y"]
                    bp, inr = size_at(cals, ln["index"], mig)
                    b["bp"] = None if bp is None else float(bp)
                    b["in_range"] = inr
                    if b["width"] > 1.0 * d:
                        continue                      # smear or background, not a band
                    b["lateral"] = lateral(a, ln, d, b["y"], b["width"])
                    if not spans_lane(b["lateral"], strict=bool(side)):
                        ignored.append(b)
                        continue
                    # weak peak level with a band of the neighbouring ladder:
                    # bleed or glare from that band
                    if any(abs(b["y"] - ly) <= 0.3 * d and b["prominence"] < 0.1 * lh
                           for ly, lh in lad_bands):
                        ignored.append(b)
                        continue
                    b["grade"] = "band" if (b["snr"] >= band_snr and b["width"] <= 0.6 * d) else "faint"
                    bands.append(b)
                results.append(_lane_result(g, row, ln, bands, ignored, noise, beta, side, borrowed,
                                            min_product, band_snr, expected, tolerance, lad))
    return dict(lanes=results, settings=dict(min_product=min_product, band_snr=band_snr,
                                             faint_snr=faint_snr, tolerance=tolerance,
                                             expected=expected or {}))


def _fmt_bp(bp, inr, lad):
    if bp is None:
        return "?"
    if not inr:
        return f">{lad.sizes[0]}" if bp > lad.sizes[0] else f"<{lad.sizes[-1] if lad.sizes else 50}"
    return f"{int(round(bp, -1 if bp >= 100 else 0))}"


def _lane_result(g, row, ln, bands, ignored, noise, beta, side, borrowed, min_product, band_snr,
                 expected, tolerance, lad):
    prod = [b for b in bands if b["bp"] is not None and b["bp"] >= min_product]
    low = [b for b in bands if b["bp"] is not None and b["bp"] < min_product]
    main = max(prod, key=lambda b: (b["grade"] == "band", b["snr"])) if prod else None
    exp = (expected or {}).get(ln.get("target") or "") if expected else None
    if exp:
        hits = [b for b in prod if abs(b["bp"] - exp) <= tolerance * exp]
        if hits:
            main = max(hits, key=lambda b: (b["grade"] == "band", b["snr"]))
    call = NO_BAND if main is None else ("Band" if main["grade"] == "band" else "Faint")
    flags = []
    big_ignored = [b for b in ignored if b["snr"] >= band_snr and b["bp"] and b["bp"] >= min_product]
    if big_ignored:
        flags.append("Ignored a spot that does not span the lane (dust, a streak or ladder bleed) at " +
                     ", ".join(_fmt_bp(b["bp"], b["in_range"], lad) + " bp" for b in big_ignored) + ".")
    if ln["type"] == "nc" and call != NO_BAND:
        flags.append("Band in negative control: check for contamination.")
    if main is not None and call != NO_BAND and not main["in_range"]:
        flags.append("Main band is outside the ladder range; size is extrapolated.")
    if main is not None and main["saturated"]:
        flags.append("Main band is saturated; intensity is underestimated.")
    if exp and call != NO_BAND:
        if abs(main["bp"] - exp) > tolerance * exp:
            flags.append(f"Main band ({main['bp']:.0f} bp) is not the expected size ({exp:.0f} bp).")
    if side and beta > 0.02:
        flags.append(f"Next to a ladder: {beta * 100:.0f}% ladder bleed removed.")
    if borrowed:
        flags.append(f"Sized with the ladder from row {borrowed}.")
    if ln.get("mismatch"):
        flags.append(ln["mismatch"])
    others = [b for b in prod if b is not main]
    return dict(
        gel=g["name"], row=row["index"], lane=ln["index"], well=ln.get("well"),
        sample=ln.get("sample", ""), replicate=ln.get("replicate"), target=ln.get("target"),
        type=ln.get("type"), label=ln.get("label"),
        call=call if ln.get("type") not in ("empty", "unloaded") or call != NO_BAND else NO_BAND,
        size_bp=(_fmt_bp(main["bp"], main["in_range"], lad) if main and call != NO_BAND else ""),
        size_value=(round(main["bp"]) if main and call != NO_BAND and main["bp"] else None),
        snr=(round(main["snr"], 1) if main else None),
        intensity=(round(main["volume"], 1) if main and call != NO_BAND else None),
        other_bands="; ".join(_fmt_bp(b["bp"], b["in_range"], lad) + f" ({b['grade']})"
                              for b in sorted(others, key=lambda b: -b["bp"])),
        low_mw="; ".join(_fmt_bp(b["bp"], b["in_range"], lad) + f" ({b['grade']})" for b in low),
        expected_bp=exp,
        flags=" ".join(flags),
        band_y=(round(main["y"], 1) if main and call != NO_BAND else None),
        noise=round(noise, 2),
    )
