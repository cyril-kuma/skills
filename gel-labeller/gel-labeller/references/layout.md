# layout.json: what is in it and how to correct it

`detect` writes `layout.json` next to the checkpoint images. `render` reads it back, so any correction made here carries through to the figure and the results table. Coordinates are pixels of the original image, x to the right and y downwards.

## Top level

| Key | Meaning |
|---|---|
| `plate_map`, `plate_map_layout` | the sheet used and whether it was the full (Gel/Row/Lane) or running-number layout |
| `ladder` | ladder id, name, catalogue number and lot printed on the figure |
| `targets`, `overrides` | target names and plate-map corrections given on the command line |
| `gels` | one entry per image |
| `review` | messages to resolve before trusting the figure |

## Per gel

`name`, `image`, `invert`, `size` (w, h), `box` (gel bounding box), `notes` (extra lines printed under the figure) and `rows`.

## Per comb row

| Key | Meaning |
|---|---|
| `index` | 1 = top comb |
| `spacing` | well-to-well distance; most other tolerances scale with it |
| `n_wells` | wells found on the comb |
| `shear` | overall lane slant (dx per dy) for the row |
| `y_start`, `y_end` | the stretch of lane analysed for bands |
| `lanes` | one entry per well, left to right |
| `ladders` | band calls for each ladder lane, keyed by lane index |

## Per lane

| Key | Meaning | Safe to edit |
|---|---|---|
| `index` | position on the comb, 1 = leftmost | no |
| `well_x`, `well_y` | centre of the well | yes, if a well was misplaced |
| `x0`, `y0`, `slant` | lane centre line: x = x0 + slant × (y − y0) | yes, if the line misses the lane |
| `ladder_like` | the image looks like a ladder here | no (measured) |
| `use_as_ladder` | this lane calibrates sizes | yes |
| `well`, `sample`, `replicate`, `target`, `type`, `label` | plate-map assignment; `type` is sample, ladder, nc, pc, empty or unloaded | yes |
| `mismatch` | text printed with an asterisk under the figure | yes (set to null once resolved) |

After moving a ladder lane (`x0`, `slant`) or switching `use_as_ladder`, run `render --recall-ladders` so its bands are found again along the new line.

## Ladder calls

`ladders["<lane index>"]["bands"]["<bp>"]` holds `y` and `status`:

- `anchor`: one of the bright reference bands the assignment is built on
- `detected`: a band found in the profile
- `interpolated`: no clear band; the position is interpolated between neighbours (shown as "(i)" on the ladder checkpoint sheet)
- `merged`: ran together with the band above it (labelled e.g. 100/50)
- `missing`: not found; no label is drawn

To fix a wrong ladder label, change its `y` (read it off the ladder checkpoint sheet, which is magnified 3×: divide the offset by 3) and set `status` to `detected`. Do not use `--recall-ladders` afterwards, or the edit is overwritten.

## Common corrections

- A sample is in the wrong lane: change `well`, `sample`, `replicate`, `target`, `type` and `label` on the lanes involved. Prefer fixing the plate map and re-running `detect` when more than a couple of lanes move.
- A comb row was missed or a false one found: re-run `detect` with `--rows` giving the number of comb rows per gel.
- The plate map has a typo in a well: re-run `detect` with `--set-well WELL=NAME`.
