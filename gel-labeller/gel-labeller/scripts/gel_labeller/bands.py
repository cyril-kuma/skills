"""Find bands in sample lanes.

Each lane profile is corrected with the gap beside the lane at the same
height, which removes horizontal shading across the gel. A rolling baseline
then removes smears. Lanes next to a ladder pick up some of the ladder's
light; that bleed is estimated at the ladder's band positions and removed.
Peak heights are compared with the noise of the row's lanes, so a call means
"stands out from the background of this gel", not an amount of DNA.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from scipy.signal import find_peaks

from .imaging import SATURATED, lane_profile


def _baseline(r: np.ndarray, d: float) -> np.ndarray:
    win = max(15, int(2.5 * d))
    return ndi.gaussian_filter1d(ndi.minimum_filter1d(r, win, mode="nearest"), d / 2)


def corrected_profile(a: np.ndarray, ln: dict, d: float, ys: np.ndarray,
                      ladder_side: str | None = None):
    """Background-corrected lane profile. ladder_side ('left'/'right') says
    which neighbour is a ladder, so that gap is not used as background."""
    x0, y0, b = ln["x0"], ln["y0"], ln["slant"]
    p = lane_profile(a, x0, y0, b, ys, 0.2 * d)
    raw = lane_profile(a, x0, y0, b, ys, 0.05 * d)
    gl = lane_profile(a, x0 - 0.5 * d, y0, b, ys, 0.05 * d)
    gr = lane_profile(a, x0 + 0.5 * d, y0, b, ys, 0.05 * d)
    if ladder_side == "left":
        bg = gr
    elif ladder_side == "right":
        bg = gl
    else:
        bg = (gl + gr) / 2
    r = ndi.gaussian_filter1d(p - bg, 1.5)
    return r - _baseline(r, d), raw


def ladder_profile(a: np.ndarray, ln: dict, d: float, ys: np.ndarray) -> np.ndarray:
    p = lane_profile(a, ln["x0"], ln["y0"], ln["slant"], ys, 0.2 * d)
    r = ndi.gaussian_filter1d(p, 1.5)
    return r - _baseline(r, d)


def remove_bleed(s: np.ndarray, lad: np.ndarray, ys: np.ndarray, band_ys: list[float]) -> tuple[np.ndarray, float]:
    """Subtract a scaled copy of the neighbouring ladder's profile."""
    idx = [int(round(y - ys[0])) for y in band_ys if ys[0] <= y < ys[-1]]
    ratios = [s[i] / lad[i] for i in idx if lad[i] > 5]
    if len(ratios) < 4:
        return s, 0.0
    beta = float(np.clip(np.median(ratios), 0, 1))
    return s - beta * lad, beta


def robust_noise(values: np.ndarray) -> float:
    v = values.ravel()
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) or 1.0


def lateral(a: np.ndarray, ln: dict, d: float, y: float, width: float) -> tuple[float, float, float]:
    """Local excess intensity of a band at the left, centre and right of the
    lane. A real band spans the lane; dust, streaks and ladder bleed do not."""
    dl = max(2 * width, 0.3 * d)
    out = []
    for off in (-0.22, 0.0, 0.22):
        vals = []
        for yy in (y - dl, y, y + dl):
            ys = np.arange(yy - 2, yy + 3, 1.0)
            vals.append(lane_profile(a, ln["x0"] + off * d, ln["y0"], ln["slant"], ys, 0.07 * d).mean())
        out.append(float(vals[1] - (vals[0] + vals[2]) / 2))
    return out[0], out[1], out[2]


def spans_lane(lat: tuple[float, float, float], strict: bool = False) -> bool:
    l, c, r = lat
    side_max, side_min = max(l, r), min(l, r)
    if side_max <= 0 or side_min <= 0:
        return False
    if side_min / side_max < (0.6 if strict else 0.4):
        return False
    if c > 0 and side_min < 0.35 * c:
        return False
    return True


def find_lane_bands(ys, s, raw, noise, d, min_snr=3.0):
    pk, pr = find_peaks(s, prominence=min_snr * noise, width=max(2.0, 0.05 * d))
    out = []
    for i, prom, wid in zip(pk, pr["prominences"], pr["widths"]):
        lo, hi = max(0, int(i - wid)), min(len(s), int(i + wid) + 1)
        out.append(dict(y=float(ys[i]), height=float(s[i]), prominence=float(prom),
                        snr=float(prom / noise), width=float(wid),
                        volume=float(np.clip(s[lo:hi], 0, None).sum()),
                        saturated=bool(raw[max(0, i - 2):i + 3].max() >= SATURATED)))
    return out
