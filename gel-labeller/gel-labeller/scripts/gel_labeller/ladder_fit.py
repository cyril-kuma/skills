"""Assign ladder band sizes along a ladder lane, and build a size calibration.

Method
1. Find candidate bands in the lane profile (peaks of the negative second
   derivative, which also picks up faint bands sitting on a shoulder). A
   candidate must show up in both the left and right halves of the lane,
   which rejects dust specks.
2. Anchor on the two brightest bands, which must be the ladder's primary
   reference bands (for HyperLadder 50bp: 1000 and 300 bp, 100 ng each).
3. Place any other reference band (2000 bp for HyperLadder 50bp) from the
   strong candidates in the window where it must fall.
4. Between consecutive anchors, try every order-preserving assignment of
   candidates to the expected bands and keep the one that gives the
   smoothest size curve (quadratic in log bp) using clear peaks.
5. Beyond the outermost anchors, walk outward one band at a time.
6. If the smallest bands are not found and the last band found is broad,
   they are reported as merged with it (for example "100/50").
"""
from __future__ import annotations

import itertools

import numpy as np
from scipy import ndimage as ndi
from scipy.interpolate import PchipInterpolator
from scipy.signal import find_peaks

from .imaging import lane_profile, plateau_centre
from .ladders import Ladder


def _d2(prof, d):
    return -ndi.gaussian_filter1d(prof, max(1.2, d / 32), order=2)


def _candidates(a, lane, ys, d):
    x0, y0, b = lane["x0"], lane["y0"], lane["slant"]
    narrow = lane_profile(a, x0, y0, b, ys, half=0.1 * d)
    wide = lane_profile(a, x0, y0, b, ys, half=0.18 * d)
    prof = (narrow + wide) / 2
    d2 = _d2(prof, d)
    pk, pr = find_peaks(d2, prominence=0.05, distance=max(3, int(d / 18)))
    return prof, [(float(ys[i]), float(p)) for i, p in zip(pk, pr["prominences"])]


def _fwhm(ys, sig, y, reach=40):
    """Width at half height above the higher of the two flanking minima."""
    i = int(np.argmin(np.abs(ys - y)))
    lo_s, hi_s = max(0, i - 4), min(len(sig), i + 5)
    i = lo_s + int(np.argmax(sig[lo_s:hi_s]))
    lo_m = i
    while lo_m > max(0, i - reach) and sig[lo_m - 1] <= sig[lo_m]:
        lo_m -= 1
    hi_m = i
    while hi_m < min(len(sig) - 1, i + reach) and sig[hi_m + 1] <= sig[hi_m]:
        hi_m += 1
    # step off the shoulder: keep descending through tiny bumps
    base = max(sig[lo_m], sig[hi_m])
    if sig[i] <= base:
        return 0.0
    half = base + (sig[i] - base) / 2
    lo = i
    while lo > 0 and sig[lo] > half:
        lo -= 1
    hi = i
    while hi < len(sig) - 1 and sig[hi] > half:
        hi += 1
    return float(ys[hi] - ys[lo])


def _assign_segment(cands, slots, ends, gap, pnorm, context=()):
    """Assign candidates (y, prom) to slots [(size, logbp)] between two fixed
    end points [(logbp, y), (logbp, y)], favouring a smooth curve. `context`
    adds already-placed bands just outside the segment to the curve fit."""
    n = len(slots)
    sig = max(1.5, 0.12 * gap)
    best = (-1e18, {})
    for k in range(min(n, len(cands)), max(0, n - 2) - 1, -1):
        for sub in itertools.combinations(range(len(cands)), k):
            for tgt in itertools.combinations(range(n), k):
                pts = list(ends) + list(context) + [(slots[j][1], cands[i][0]) for i, j in zip(sub, tgt)]
                xs = np.array([p[0] for p in pts])
                yv = np.array([p[1] for p in pts])
                deg = 2 if len(pts) >= 4 else 1
                coef = np.polyfit(xs, yv, deg)
                res = yv - np.polyval(coef, xs)
                sc = sum(np.log(cands[i][1] / pnorm) for i in sub)
                sc -= float(np.sum((res / sig) ** 2))
                sc -= 3.0 * (n - k)
                sc -= sum(max(0.0, np.log(cands[i][1] / pnorm / 0.3))
                          for i in range(len(cands)) if i not in sub)
                if sc > best[0]:
                    best = (sc, {slots[j][0]: cands[i][0] for i, j in zip(sub, tgt)})
    return best[1]


def call_ladder(a: np.ndarray, lane: dict, ladder: Ladder, d: float,
                y_start: float, y_end: float) -> dict:
    """Return {'bands': {bp: {'y':..,'status':..}}, 'flags': [...], 'merged': [...]}."""
    ys = np.arange(y_start, y_end, 1.0)
    prof, cands = _candidates(a, lane, ys, d)
    sig = ndi.gaussian_filter1d(prof, 1.0)
    flags: list[str] = []
    sizes = ladder.sizes
    lsz = {s: float(np.log10(s)) for s in sizes}
    top_proms = sorted([c[1] for c in cands], reverse=True)[:len(sizes)]
    pnorm = float(np.median(top_proms)) if top_proms else 1.0

    # ---- primary anchors: the brightest peaks
    span = float(sig.max() - np.percentile(sig, 5))
    pk, _ = find_peaks(sig, prominence=0.05 * span, distance=max(4, int(d / 6)))
    prim = ladder.primary                     # e.g. [1000, 300]
    need = len(prim)
    order = sorted(pk, key=lambda i: -sig[i])[:need + 2]
    best = None
    for combo in itertools.combinations(order, need):
        combo = sorted(combo)
        pos_ = [plateau_centre(ys, sig, i) for i in combo]
        if any(pos_[j + 1][0] - pos_[j][0] < d / 2 for j in range(need - 1)):
            continue
        err = 0
        for j in range(need - 1):
            exp_n = len([s for s in sizes if prim[j + 1] < s < prim[j]])
            got_n = len([c for c in cands if pos_[j][2] + 2 < c[0] < pos_[j + 1][1] - 2
                         and c[1] > 0.3 * pnorm])
            err += abs(got_n - exp_n)
        bright = sum(sig[i] for i in combo)
        key = (max(0, err - 2), -bright, err)
        if best is None or key < best[0]:
            best = (key, pos_)
    if best is None:
        return dict(bands={int(s): dict(y=None, status="missing") for s in sizes},
                    flags=["No ladder pattern found: could not find the reference bands."], merged=[])
    if best[0][2] > 2:
        flags.append(f"Reference bands uncertain: band count between them is off by {best[0][2]}.")
    extent = {s: (p[1], p[2]) for s, p in zip(prim, best[1])}
    pos = {s: p[0] for s, p in zip(prim, best[1])}
    status = {s: "anchor" for s in prim}

    # ---- secondary reference bands (brighter than their neighbours)
    span_log = lsz[prim[0]] - lsz[prim[-1]]
    for s in ladder.reference:
        if s in pos:
            continue
        # log-linear extrapolation from the primary anchors
        pred = pos[prim[0]] - (lsz[s] - lsz[prim[0]]) / span_log * (pos[prim[-1]] - pos[prim[0]])
        half_win = 0.6 * abs(pred - (pos[prim[0]] if s > prim[0] else pos[prim[-1]]))
        win = [c for c in cands if abs(c[0] - pred) <= max(half_win, 0.3 * d)
               and all(abs(c[0] - pos[k]) > 0.15 * d for k in pos)]
        if not win:
            continue
        vmax = max(c[1] for c in win)
        strong = [c for c in win if c[1] >= 0.45 * vmax]
        if s == max(sizes):
            c = min(strong, key=lambda c: c[0])        # largest band = topmost strong peak
        elif s == min(sizes):
            c = max(strong, key=lambda c: c[0])
        else:
            c = max(strong, key=lambda c: c[1])
        pos[s], status[s] = c[0], "anchor"
        extent[s] = (c[0] - 2, c[0] + 2)

    # ---- segments between consecutive anchors; the segment between the
    # primary anchors first, then outward using its bands as context
    anchors = sorted(pos, reverse=True)
    segs = list(zip(anchors, anchors[1:]))
    segs.sort(key=lambda hl: 0 if (hl[0] in prim and hl[1] in prim) else 1)
    for hi_s, lo_s in segs:
        inner = [s for s in sizes if lo_s < s < hi_s]
        if not inner:
            continue
        ya, yb = pos[hi_s], pos[lo_s]
        gap = (yb - ya) / (len(inner) + 1)
        lo_edge = extent[hi_s][1] + 2
        hi_edge = extent[lo_s][0] - 2
        cc = [c for c in cands if lo_edge < c[0] < hi_edge and c[1] >= 0.15 * pnorm]
        done = [s for s in pos if status[s] == "detected"]
        if lo_s in prim and hi_s not in prim:      # segment above the primary pair
            ctx = sorted([s for s in done if s < lo_s], reverse=True)[:3]
        elif hi_s in prim and lo_s not in prim:    # segment below it
            ctx = sorted([s for s in done if s > hi_s])[:3]
        else:
            ctx = []
        got = _assign_segment(cc, [(s, lsz[s]) for s in inner],
                              [(lsz[hi_s], ya), (lsz[lo_s], yb)], gap, pnorm,
                              context=[(lsz[s], pos[s]) for s in ctx])
        for s in inner:
            if s in got:
                pos[s], status[s] = got[s], "detected"
    # fill gaps inside the anchored range by interpolation
    known = sorted(pos, reverse=True)
    for s in sizes:
        if s in pos or s > known[0] or s < known[-1]:
            continue
        big = min(k for k in pos if k > s)
        small = max(k for k in pos if k < s)
        t = (lsz[big] - lsz[s]) / (lsz[big] - lsz[small])
        pos[s] = pos[big] + t * (pos[small] - pos[big])
        status[s] = "interpolated"
    used = [c[1] for c in cands if any(abs(c[0] - pos[s]) < 1.5 for s in pos)]
    min_prom = max(0.25 * (float(np.median(used)) if used else pnorm), 0.4 * pnorm)

    # ---- walk outward
    def walk(direction):
        rest = ([s for s in sizes if s > max(pos)][::-1] if direction == "up"
                else [s for s in sizes if s < min(pos)])
        for s in rest:
            known = sorted(pos, key=lambda k: pos[k])
            near = known[:3] if direction == "up" else known[-3:]
            slope, icpt = np.polyfit([lsz[k] for k in near], [pos[k] for k in near], 1)
            pred = slope * lsz[s] + icpt
            last = pos[near[0]] if direction == "up" else pos[near[-1]]
            gap = abs(pred - last)
            if direction == "up":
                lo_w, hi_w = last - 1.3 * gap, last - 0.3 * gap
            else:
                lo_w, hi_w = last + 0.3 * gap, last + 1.3 * gap
            cc = [c for c in cands if lo_w <= c[0] <= hi_w and c[1] >= min_prom]
            if not cc:
                return s
            sig_ = max(2.0, 0.5 * gap)
            c = max(cc, key=lambda c: np.log(c[1] / pnorm) - ((c[0] - pred) / sig_) ** 2)
            pos[s], status[s] = c[0], "detected"
        return None

    walk("up")
    first_missing_low = walk("down")
    merged: list[int] = []
    if first_missing_low is not None:
        smallest = min(pos)
        prev = min(k for k in pos if k > smallest)
        w_last = _fwhm(ys, sig, pos[smallest])
        w_prev = _fwhm(ys, sig, pos[prev])
        missing = [s for s in sizes if s < smallest]
        if w_last > 1.35 * w_prev:
            merged = [smallest] + missing
            for s in missing:
                pos[s], status[s] = pos[smallest], "merged"
        else:
            for s in missing:
                status[s] = "missing"
    for s in sizes:
        status.setdefault(s, "missing")
    missing = [s for s in sizes if status[s] == "missing"]
    if missing:
        flags.append("Not found: " + ", ".join(f"{s} bp" for s in missing) + ".")
    ordered = [pos[s] for s in sizes if s in pos and status[s] != "merged"]
    if any(b <= a_ for a_, b in zip(ordered, ordered[1:])):
        flags.append("Band order is not monotonic; check this ladder by eye.")
    interp = [s for s in sizes if status[s] == "interpolated"]
    if interp:
        flags.append("Placed by interpolation (no clear band): " + ", ".join(f"{s} bp" for s in interp) + ".")
    bands = {int(s): dict(y=(float(pos[s]) if s in pos else None), status=status[s]) for s in sizes}
    return dict(bands=bands, flags=flags, merged=[int(m) for m in merged])


class Calibration:
    """Migration distance (from the well) to size, from one ladder lane."""

    def __init__(self, ladder_call: dict, y_well: float):
        pts = sorted([(b["y"] - y_well, np.log10(int(s))) for s, b in ladder_call["bands"].items()
                      if b["y"] is not None and b["status"] in ("anchor", "detected", "interpolated")])
        m = np.array([p[0] for p in pts])
        l = np.array([p[1] for p in pts])
        keep = np.concatenate([[True], np.diff(m) > 0.5])
        m, l = m[keep], l[keep]
        self.m_min, self.m_max = float(m.min()), float(m.max())
        self.f = PchipInterpolator(m, l, extrapolate=False)
        self.lo = np.polyfit(m[:3], l[:3], 1)
        self.hi = np.polyfit(m[-3:], l[-3:], 1)

    def log_bp(self, mig: float) -> float:
        if mig < self.m_min:
            return float(np.polyval(self.lo, mig))
        if mig > self.m_max:
            return float(np.polyval(self.hi, mig))
        return float(self.f(mig))

    def in_range(self, mig: float) -> bool:
        return self.m_min <= mig <= self.m_max
