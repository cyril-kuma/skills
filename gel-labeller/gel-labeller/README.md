# gel-labeller

Labels agarose gel images with sample IDs from a plate map, draws ladder size scales, and calls bands (with estimated sizes) into a results table.

`SKILL.md` is the workflow Claude follows. This file is for running the tool by hand.

## Install

Python 3.10 or later.

```bash
pip install -r requirements.txt
export PYTHONPATH=$PWD/scripts
```

## Use

```bash
# 1. find combs, wells, lanes and ladder bands; write checkpoint images
python3 -m gel_labeller detect --images gel1.jpeg gel2.jpeg --plate-map wells.xlsx \
    --ladder BIO-33040 --ladder-lot MW426-B097860 --targets IgGH IgMH IgKK IgLL --out run1

# 2. look at run1/qc/*.png and the printed review list; fix run1/layout.json if needed

# 3. draw the figures and write the results table
python3 -m gel_labeller render --layout run1/layout.json --expected IgKK=650
```

Other commands:

```bash
python3 -m gel_labeller template --out plate_map.xlsx   # empty plate map in the recommended layout
python3 -m gel_labeller ladders                          # ladders the tool knows
python3 -m gel_labeller run ...                          # detect and render without stopping
```

## Plate map

The recommended layout has one row per lane:

| Gel | Row | Lane | Sample | Replicate | Target | Type |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | Ladder | | | ladder |
| 1 | 1 | 2 | B1 | 1 | IgGH | |

Type is optional (sample, ladder, nc, pc, empty) and is worked out from the sample name when left blank. A sheet with only Sample, Replicate and a running Well number also works. The tool then has to infer where each comb row starts and reports every guess for review.

## Outputs

| File | Contents |
|---|---|
| `<gel>_labelled.png` | labelled figure with size scales and notes |
| `results.xlsx` | Samples, Lanes, Ladders, Review and Settings sheets |
| `results.csv` | the Lanes sheet |
| `qc/overlay_<gel>.png` | detected combs, wells, lane lines and ladder bands |
| `qc/ladders_<gel>.png` | each ladder magnified with its size calls |
| `qc/lanes_<gel>_row<N>.png` | lanes cut out along their own lines, with calls marked |
| `layout.json`, `calls.json` | everything needed to redraw the figure |

## Docs

- `references/method.md`: how each step works, the thresholds, adding a ladder
- `references/layout.md`: the fields in `layout.json` and how to correct them

## Test

The test gels are research data and are not in this repository. With a local folder of images, plate map and truth files:

```bash
GEL_FIXTURES=/path/to/fixtures python3 tests/test_gels.py
```
