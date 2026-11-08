# How the tool works

This is the reasoning behind each step, so a result that looks wrong can be traced to the step that produced it.

## 1. Gel, combs and wells (`detect.py`)

The gel is the largest bright region of the image (Otsu threshold on a smoothed copy). Comb rows are found by projecting horizontal-gradient energy along slightly tilted lines (−6° to +6°): a comb is the only feature that gives a strong, sharply periodic signal across the gel. A candidate row is kept only if the intensity profile along it repeats with an autocorrelation of at least 0.7.

Along each comb, the well spacing comes from the autocorrelation peak, and a regular grid is fitted to the dark wells. The wells kept are the longest unbroken run of grid points where the well is darker than the gaps either side. Their x positions are refitted as a straight line, since a comb is rigid. A well's vertical centre is the darkness-weighted centroid, because wells often show as two dark bars.

## 2. Lane lines

A single shear per row is chosen to make the lanes as vertical as possible (the sharpest column projection). Each lane is scored for how ladder-like it looks: the number of sharp bands and the contrast relative to the other lanes in the row. Ladder-like lanes are tracked down the gel by intensity centroids, and the fit uses only rows with strong signal. Their offset from the well and their slant are then interpolated across the row for every other lane. On a gel whose lanes bow sideways, lanes do not start exactly under their wells, which is why each lane stores its own `x0`.

## 3. Plate map to lanes (`pipeline.map_lanes`)

With the full layout (Gel, Row, Lane), each lane is looked up directly.

With running well numbers, wells are dealt out across rows in order. A row may start a few wells later than the running count suggests, but only by skipping wells the plate map lists as NA, and only when that lines the plate-map ladders up with the ladder-like lanes. Any skip is reported for review. Then every lane is checked:

- the plate map says ladder but the lane has no ladder pattern: the lane is labelled `Ladder*` and not used for sizing
- the lane looks like a ladder and the plate map says NA: it is used as a ladder and labelled `Ladder*`
- the lane looks like a ladder and the plate map names a sample: the sample keeps its label with an asterisk, and the lane is not used for sizing

All three go to the review list.

## 4. Ladder bands (`ladder_fit.py`)

Candidates are peaks of the negative second derivative of the lane profile, which separates faint bands sitting on the shoulder of a bright one. The two brightest peaks anchor the assignment. They must be the ladder's primary reference bands (equal top load in the ladder JSON). Further reference bands (2000 bp on HyperLadder 50bp) are placed from the strongest candidates in the window where they must fall.

Between two anchors, every order-preserving assignment of candidates to the expected bands is tried. The winner is the one giving the smoothest curve (a quadratic in log bp, also fitted through bands already placed on the next segment) while using clear peaks and leaving few strong peaks unexplained. This beats assuming bands are evenly spaced in log bp, which on these gels was off by up to 10 px between 1000 and 300 bp. Beyond the outer anchors, the tool walks outward one band at a time.

Smallest bands: if they are not found, the tool checks whether the last band found is broader than the one above it. The decision is made once per gel by majority over its ladders, so every ladder on a gel is labelled the same way.

## 5. Sizes

Each ladder becomes a calibration from migration distance (band y minus that lane's well y) to log bp, by monotone (PCHIP) interpolation. A sample lane is sized by blending the ladders on either side of it in proportion to its position between them, which absorbs gel tilt and smiling. Sizes outside the ladder range are extrapolated and flagged.

## 6. Sample bands (`bands.py`, `pipeline.analyse`)

Each lane profile has the gap beside the lane subtracted (removes horizontal shading), then a rolling-minimum baseline (removes smear). In a lane next to a ladder, the gap on the ladder side is not used, and a scaled copy of the ladder profile is removed. The scale is the median ratio at the ladder's band positions. Peaks are scored against the noise of all non-ladder lanes in the row (median absolute deviation, scaled to an SD).

A peak becomes a band only if it spans the lane: left, centre and right must all be brighter than just above and below it, with the sides balanced. This drops dust, streaks from damaged wells and ladder bleed. It is also dropped if it is weak and level with a band of the neighbouring ladder, which is glare from that band.

| Call | Rule (defaults) |
|---|---|
| Band | signal/noise ≥ 8 and no taller than 0.6 lane widths |
| Faint | signal/noise ≥ 5, or a strong but diffuse peak |
| No band | nothing that passes the checks above the size cutoff |

Features taller than one lane width are treated as smear, not bands. Bands below the size cutoff (default 200 bp, or half the smallest expected size) are listed separately as possible primer dimer and do not count as amplification.

These thresholds were set on two HyperLadder 50bp gels (Ig heavy/light chain PCR, November 2026) where every lane was checked by eye. Expect to revisit them for very different images, such as a much brighter imager or a different stain.

## 7. Output

- `<gel>_labelled.png`: the figure. Gels whose lanes slant by more than about 2° are straightened with a horizontal shear, and a note says so.
- `results.xlsx`: Samples (replicates side by side), Lanes, Ladders, Review, Settings. `results.csv` is the Lanes sheet.
- `qc/`: overlay, ladder sheet and lane strips for the checkpoint.
- `calls.json`, `layout.json`: everything needed to redraw the figure.

## Adding a ladder

Copy `ladders/hyperladder-50bp.json`, list the bands (bp and ng for the standard load) and set `reference_bands` with the brightest first. At least two must share the highest ng; those anchor the assignment. Add catalogue numbers and aliases so `--ladder` can find it.
