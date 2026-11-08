"""Image loading and sampling helpers.

All coordinates are full-resolution pixels of the original image, x to the
right and y downwards. Intensities are floats on a 0-255 scale.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

SATURATED = 253.5


def load_gray(path: str, invert: bool = False) -> np.ndarray:
    im = Image.open(path)
    if im.mode.startswith("I;16") or im.mode in ("I", "F"):
        a = np.asarray(im, dtype=np.float64)
        top = 65535.0 if a.max() > 255 else 255.0
        a = a / top * 255.0
    else:
        a = np.asarray(im.convert("L"), dtype=np.float64)
    if invert:
        a = 255.0 - a
    return a


def otsu(values: np.ndarray) -> float:
    v = values[np.isfinite(values)].ravel()
    hist, edges = np.histogram(v, bins=256)
    mids = (edges[:-1] + edges[1:]) / 2
    w = np.cumsum(hist)
    mu = np.cumsum(hist * mids)
    total = w[-1]
    w1 = total - w
    with np.errstate(divide="ignore", invalid="ignore"):
        m0 = mu / w
        m1 = (mu[-1] - mu) / w1
        between = w * w1 * (m0 - m1) ** 2
    between[~np.isfinite(between)] = 0
    return float(mids[np.argmax(between)])


def gel_box(a: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box (x0, y0, x1, y1) of the gel: the largest bright region."""
    s = ndi.gaussian_filter(a, 6)
    mask = s > otsu(s)
    lab, n = ndi.label(mask)
    if n == 0:
        h, w = a.shape
        return 0, 0, w, h
    sizes = ndi.sum(mask, lab, range(1, n + 1))
    keep = lab == (int(np.argmax(sizes)) + 1)
    rows = np.where(keep.mean(axis=1) > 0.3)[0]
    cols = np.where(keep.mean(axis=0) > 0.3)[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def lane_profile(a: np.ndarray, x0: float, y0: float, slant: float,
                 ys: np.ndarray, half: float, step: float = 1.0) -> np.ndarray:
    """Mean intensity across a lane of half-width `half`, sampled at rows `ys`.
    The lane centre is x = x0 + slant * (y - y0)."""
    xs = x0 + slant * (ys - y0)
    offs = np.arange(-half, half + 1e-9, step)
    acc = [ndi.map_coordinates(a, [ys, xs + d], order=1, mode="nearest") for d in offs]
    return np.mean(acc, axis=0)


def comb_profile(a: np.ndarray, x0: float, y0: float, slope: float,
                 xs: np.ndarray, half: float) -> np.ndarray:
    """Mean intensity across a horizontal band along y = y0 + slope * (x - x0)."""
    ys = y0 + slope * (xs - x0)
    offs = np.arange(-half, half + 1e-9, 1.0)
    acc = [ndi.map_coordinates(a, [ys + d, xs], order=1, mode="nearest") for d in offs]
    return np.mean(acc, axis=0)


def plateau_centre(ys: np.ndarray, sig: np.ndarray, i: int, tol: float = 3.0) -> tuple[float, float, float]:
    """Centre and edges of a peak, treating a saturated (flat) top as one band."""
    top = sig[i]
    lo = hi = i
    while lo > 0 and sig[lo - 1] >= top - tol:
        lo -= 1
    while hi < len(sig) - 1 and sig[hi + 1] >= top - tol:
        hi += 1
    return (float(ys[lo]) + float(ys[hi])) / 2, float(ys[lo]), float(ys[hi])
