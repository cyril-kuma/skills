"""Find comb rows, wells and lane slant in a gel image."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from scipy.signal import find_peaks

from .imaging import comb_profile, lane_profile

ACF_MIN = 0.7          # periodicity needed along a line to call it a comb
ANGLES = np.arange(-6.0, 6.01, 0.25)


# --------------------------------------------------------------------------- combs
def _acf_period(hp: np.ndarray, lo: int = 12, hi: int = 220) -> tuple[float, float]:
    hp = hp - hp.mean()
    ac = np.correlate(hp, hp, "full")[len(hp) - 1:]
    if ac[0] <= 0:
        return 0.0, 0.0
    ac = ac / ac[0]
    hi = min(hi, len(ac) - 2)
    seg = ac[lo:hi]
    pk, _ = find_peaks(seg)
    if len(pk) == 0 or seg[pk].max() <= 0:
        return 0.0, 0.0
    # first strong peak = fundamental period
    strong = [p for p in pk if seg[p] >= 0.8 * seg[pk].max()]
    i = strong[0] + lo
    y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]
    den = y0 - 2 * y1 + y2
    off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return float(i + off), float(y1)


def _line_score(a, xc, y, slope, xs, half):
    p = comb_profile(a, xc, y, slope, xs, half)
    hp = p - ndi.gaussian_filter1d(p, 25)
    per, acf = _acf_period(hp)
    return acf, float(np.std(hp)), per


def find_combs(a: np.ndarray, box, expected: int | None = None) -> list[dict]:
    """Comb rows as dicts with keys y (at the gel centre), slope, period, acf."""
    x0, y0, x1, y1 = box
    ds = 2
    sub = ndi.gaussian_filter(a, 1.0)[::ds, ::ds]
    X0, Y0, X1, Y1 = x0 // ds, y0 // ds, x1 // ds, y1 // ds
    pad = int(0.03 * (X1 - X0))
    reg = sub[Y0:Y1, X0 + pad:X1 - pad]
    e = np.abs(ndi.sobel(reg, axis=1))
    h, w = e.shape
    cols = np.arange(w)
    xc_sub = w / 2
    profiles = []
    for deg in ANGLES:
        m = np.tan(np.radians(deg))
        sh = np.round(m * (cols - xc_sub)).astype(int)
        rows = np.arange(h)[:, None] + sh[None, :]
        valid = (rows >= 0) & (rows < h)
        E = np.where(valid, e[np.clip(rows, 0, h - 1), cols[None, :]], 0).sum(1)
        E = ndi.gaussian_filter1d(E / np.maximum(valid.sum(1), 1), 1.5)
        profiles.append((deg, E))
    # candidate rows: peaks of the best-angle profile at every angle, merged
    cands = []
    for deg, E in profiles:
        med = np.median(E)
        pk, _ = find_peaks(E, prominence=0.15 * (E.max() - med), distance=max(5, int(0.05 * h)))
        for p in pk:
            cands.append(((Y0 + p) * ds, deg, E[p] / med))
    cands.sort(key=lambda c: -c[2])
    xc = (x0 + x1) / 2
    xs = np.arange(x0, x1, 1.0)
    combs: list[dict] = []
    tried: list[float] = []
    for yc, deg, _ in cands:
        if any(abs(yc - t) < 12 for t in tried):
            continue
        tried.append(yc)
        if any(abs(yc - c["y"]) < 60 for c in combs):
            continue
        best = None
        for dd in np.arange(-1.5, 1.51, 0.25):
            m = np.tan(np.radians(deg + dd))
            for dy in range(-24, 25, 3):
                acf, amp, per = _line_score(a, xc, yc + dy, m, xs, 3)
                if acf >= ACF_MIN and (best is None or amp > best[0]):
                    best = (amp, yc + dy, m, per, acf)
        if best is None:
            continue
        amp, y, m, per, acf = best
        # fine refinement of slope and offset
        for _ in range(2):
            for dm in np.linspace(-0.004, 0.004, 9):
                for dy in np.arange(-3, 3.01, 1.0):
                    acf2, amp2, per2 = _line_score(a, xc, y + dy, m + dm, xs, 3)
                    if acf2 >= ACF_MIN and amp2 > amp:
                        amp, y, m, per, acf = amp2, y + dy, m + dm, per2, acf2
        if any(abs(y - c["y"]) < 60 for c in combs):
            continue
        combs.append(dict(y=float(y), slope=float(m), period=float(per), acf=float(acf),
                          amp=float(amp), xc=float(xc)))
        if expected and len(combs) >= expected:
            break
    combs.sort(key=lambda c: c["y"])
    return combs


# --------------------------------------------------------------------------- wells
def fit_wells(a: np.ndarray, comb: dict, box) -> dict:
    """Locate every well along a comb. Returns well x/y lists and spacing."""
    x0, _, x1, _ = box
    xc, y, m, d = comb["xc"], comb["y"], comb["slope"], comb["period"]
    xs = np.arange(x0, x1, 0.5)
    half = max(2.0, 0.08 * d)
    p = comb_profile(a, xc, y, m, xs, half)
    p = ndi.gaussian_filter1d(p, 0.06 * d / 0.5)
    hp = p - ndi.gaussian_filter1d(p, d / 0.5)

    def at(xq):
        return np.interp(xq, xs, hp, left=0.0, right=0.0)

    best = None
    for dd in np.linspace(0.97 * d, 1.03 * d, 31):
        ks = np.arange(-2, int((x1 - x0) / dd) + 3)
        for ph in np.arange(0, dd, 0.5):
            gx = x0 + ph + ks * dd
            sc = -np.sum(np.minimum(at(gx), 0))
            if best is None or sc > best[0]:
                best = (sc, dd, ph)
    _, dd, ph = best
    ks = np.arange(-2, int((x1 - x0) / dd) + 3)
    gx = x0 + ph + ks * dd
    contrast = (at(gx + dd / 2) + at(gx - dd / 2)) / 2 - at(gx)
    top = np.sort(contrast)[len(contrast) // 2:]
    thr = 0.35 * np.median(top)
    ok = contrast > thr
    # longest contiguous run of wells
    runs, start = [], None
    for i, v in enumerate(ok):
        if v and start is None:
            start = i
        if (not v or i == len(ok) - 1) and start is not None:
            end = i if v else i - 1
            runs.append((start, end))
            start = None
    s, e = max(runs, key=lambda r: r[1] - r[0])
    wells_grid = gx[s:e + 1]
    # per-well refinement, then a straight-line fit (a comb is rigid)
    refined = []
    for g in wells_grid:
        w = (xs > g - dd / 4) & (xs < g + dd / 4)
        i = np.argmin(p[w])
        xw = xs[w]
        pw = p[w]
        if 0 < i < len(pw) - 1:
            den = pw[i - 1] - 2 * pw[i] + pw[i + 1]
            off = 0.5 * (pw[i - 1] - pw[i + 1]) / den if den != 0 else 0
            refined.append(xw[i] + off * 0.5)
        else:
            refined.append(xw[i])
    k = np.arange(len(refined))
    coef = np.polyfit(k, refined, 1)
    resid = np.array(refined) - np.polyval(coef, k)
    keep = np.abs(resid) < max(3.0, 2.5 * np.std(resid))
    coef = np.polyfit(k[keep], np.array(refined)[keep], 1)
    wx = np.polyval(coef, k)
    # vertical centre of each well: darkness-weighted centroid of a vertical
    # profile (wells can show as two dark bars, so no single minimum is used)
    wy = []
    for xw in wx:
        yl = y + m * (xw - xc)
        yy = np.arange(yl - 0.7 * d, yl + 0.7 * d, 0.5)
        col = lane_profile(a, xw, yl, 0.0, yy, half=0.12 * d, step=1.0)
        col = ndi.gaussian_filter1d(col, 0.08 * d / 0.5)
        dark = np.clip(np.percentile(col, 85) - col, 0, None) ** 2
        wy.append(float((dark * yy).sum() / dark.sum()) if dark.sum() > 0 else float(yl))
    wy = np.array(wy)
    cy = np.polyfit(wx, wy, 1)
    resid = wy - np.polyval(cy, wx)
    keep = np.abs(resid) < max(3.0, 2.5 * np.std(resid))
    cy = np.polyfit(wx[keep], wy[keep], 1)
    return dict(n=int(len(wx)), x=[float(v) for v in wx], y=[float(np.polyval(cy, v)) for v in wx],
                spacing=float(coef[0]), slope=float(cy[0]))


# --------------------------------------------------------------------------- lanes
def ladder_score(a: np.ndarray, xw: float, yw: float, slant: float, d: float,
                 y_start: float, y_end: float) -> dict:
    """How ladder-like a lane looks: number of sharp bands and contrast,
    searching a little sideways because lanes need not start exactly under
    their well."""
    best = None
    ys = np.arange(y_start, y_end, 1.0)
    for off in np.arange(-0.3 * d, 0.3001 * d, 0.1 * d):
        p = lane_profile(a, xw + off, yw, slant, ys, 0.15 * d)
        sig = ndi.gaussian_filter1d(p, 1.0)
        d2 = -ndi.gaussian_filter1d(p, max(1.2, d / 30), order=2)
        hp = sig - ndi.gaussian_filter1d(sig, 2 * d)
        _, pr = find_peaks(d2, prominence=0.25)
        npk = int((pr["prominences"] > 0.5).sum())
        s = float(np.std(hp))
        if best is None or s > best["contrast"]:
            best = dict(peaks=npk, contrast=s, offset=float(off))
    return best


def analyse_rows(a: np.ndarray, box, expected_rows: int | None = None) -> list[dict]:
    """Comb rows with wells and a centre line for every lane.

    Each lane line is x = x0 + slant * (y - y0), where (x0, y0) is the point
    level with the well centre (x0 can sit a few pixels off the well when
    lanes bow sideways)."""
    combs = find_combs(a, box, expected_rows)
    rows = []
    for r, comb in enumerate(combs):
        wells = fit_wells(a, comb, box)
        d = wells["spacing"]
        y_end = (combs[r + 1]["y"] - 0.6 * d) if r + 1 < len(combs) else box[3] - 0.15 * d
        y_start = max(wells["y"]) + 0.8 * d
        shear = row_shear(a, wells, y_end)
        scores = [ladder_score(a, x, y, shear, d, y_start, y_end) for x, y in zip(wells["x"], wells["y"])]
        med = float(np.median([s["contrast"] for s in scores])) or 1.0
        lanes = []
        for k, (x, y, sc) in enumerate(zip(wells["x"], wells["y"], scores)):
            looks = sc["peaks"] >= 8 and sc["contrast"] >= 2.5 * med
            lanes.append(dict(index=k + 1, well_x=float(x), well_y=float(y), x0=float(x), y0=float(y),
                              slant=shear, ladder_like=bool(looks),
                              ladder_peaks=sc["peaks"], ladder_contrast=round(sc["contrast"] / med, 2),
                              tracked=False, _off=sc["offset"]))
        # refine bright (ladder-like) lanes by tracking their centre line
        for ln in lanes:
            if not ln["ladder_like"]:
                continue
            b, q = track_lane(a, ln["well_x"] + ln["_off"], ln["well_y"], shear, d, y_start, y_end)
            if q > 0:
                # re-fit x0 so the line passes through the tracked centroids
                ys = np.arange(y_start, y_end, 2.0)
                xs0 = ln["well_x"] + ln["_off"] + shear * (ys - ln["well_y"])
                pts = []
                for yy, xx in zip(ys, xs0):
                    xs = np.arange(xx - 0.5 * d, xx + 0.5 * d, 1.0)
                    row = ndi.gaussian_filter1d(
                        ndi.map_coordinates(a, [np.full_like(xs, yy), xs], order=1, mode="nearest"), 1.5)
                    wv = np.clip(row - np.percentile(row, 20), 0, None)
                    if wv.max() < 8:
                        continue
                    k = int(np.argmax(wv))
                    lo, hi = max(0, k - int(0.3 * d)), min(len(wv), k + int(0.3 * d))
                    pts.append((yy, float((wv[lo:hi] * xs[lo:hi]).sum() / wv[lo:hi].sum()), wv.max()))
                pts = np.array(pts)
                strong = pts[:, 2] >= 0.3 * np.percentile(pts[:, 2], 90)
                pts = pts[strong]
                resid = pts[:, 1] - b * (pts[:, 0] - ln["well_y"])
                ln["x0"] = float(np.average(resid, weights=pts[:, 2]))
                ln["slant"] = b
                ln["tracked"] = True
        # untracked lanes: interpolate offset and slant between tracked lanes
        tr = [ln for ln in lanes if ln["tracked"]]
        for ln in lanes:
            if ln["tracked"]:
                continue
            if not tr:
                continue
            ks = np.array([t["index"] for t in tr])
            offs = np.array([t["x0"] - t["well_x"] for t in tr])
            sls = np.array([t["slant"] for t in tr])
            ln["x0"] = ln["well_x"] + float(np.interp(ln["index"], ks, offs))
            ln["slant"] = float(np.interp(ln["index"], ks, sls))
        for ln in lanes:
            ln.pop("_off", None)
        rows.append(dict(index=r + 1, comb=comb, spacing=float(d), n_wells=wells["n"],
                         comb_slope=wells["slope"], shear=float(shear),
                         y_start=float(y_start), y_end=float(y_end), lanes=lanes))
    return rows


# --------------------------------------------------------------------------- slant
def row_shear(a: np.ndarray, wells: dict, y_end: float) -> float:
    """Single shear (dx/dy) for a row that makes its lanes most vertical."""
    d = wells["spacing"]
    xL, xR = wells["x"][0] - d, wells["x"][-1] + d
    ytop = max(wells["y"]) + 0.8 * d
    ys = np.arange(ytop, y_end, 2.0)
    xs = np.arange(xL, xR, 1.0)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    best = None
    for b in np.arange(-0.25, 0.2501, 0.0025):
        img = ndi.map_coordinates(a, [yy, xx + b * (yy - ytop)], order=1, mode="nearest")
        proj = img.mean(axis=0)
        hp = proj - ndi.gaussian_filter1d(proj, d)
        sc = float(np.sum(np.diff(hp) ** 2))
        if best is None or sc > best[0]:
            best = (sc, b)
    return float(best[1])


def track_lane(a: np.ndarray, xw: float, yw: float, slant0: float, d: float,
               y_start: float, y_end: float) -> tuple[float, float]:
    """Refine a bright lane's centre line by intensity centroids. Returns
    (slant, quality) where quality is the fraction of rows with usable signal."""
    ys = np.arange(y_start, y_end, 2.0)
    pts, wts = [], []
    for y in ys:
        xc = xw + slant0 * (y - yw)
        xs = np.arange(xc - 0.5 * d, xc + 0.5 * d, 1.0)
        row = ndi.map_coordinates(a, [np.full_like(xs, y), xs], order=1, mode="nearest")
        row = ndi.gaussian_filter1d(row, 1.5)
        bg = np.percentile(row, 20)
        wv = np.clip(row - bg, 0, None)
        if wv.max() < 8:
            continue
        k = int(np.argmax(wv))
        lo, hi = max(0, k - int(0.3 * d)), min(len(wv), k + int(0.3 * d))
        ww = wv[lo:hi]
        pts.append((y, float((ww * xs[lo:hi]).sum() / ww.sum())))
        wts.append(float(wv.max()))
    if len(pts) < 10:
        return slant0, 0.0
    pts = np.array(pts)
    wts = np.array(wts)
    strong = wts >= 0.3 * np.percentile(wts, 90)
    if strong.sum() >= 10:
        pts, wts = pts[strong], wts[strong]
    b, c = np.polyfit(pts[:, 0], pts[:, 1], 1, w=wts)
    resid = pts[:, 1] - (b * pts[:, 0] + c)
    keep = np.abs(resid) < max(2.0, 2.5 * np.std(resid))
    if keep.sum() >= 10:
        b, c = np.polyfit(pts[keep, 0], pts[keep, 1], 1, w=wts[keep])
    return float(b), float(len(pts) / len(ys))
