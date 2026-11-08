---
name: gel-labeller
description: Labels agarose gel images with sample IDs from a plate map, adds ladder size scales, and calls bands with sizes into a results table. Use whenever Stephen shares gel photos with a well or plate sheet, or asks to label, annotate, size or score a gel, even if he doesn't name this skill.
---

# Gel labeller

The tool reads gel images and a plate map. It produces a labelled figure for each gel and a results table that says which samples amplified and at roughly what size. The code lives in Stephen's skills repository, so every run uses the same version and the same settings. Runs are split into two steps with a check in between, because what can go wrong on a gel (a reflection that looks like a lane, a plate map that doesn't match what was loaded) is easy to see in a picture and hard to catch in code.

## What to ask for

You need the gel images in loading order. Raw TIFF from the imager is better than JPEG, though JPEG works. You also need the plate map: the recommended layout has one row per lane with Gel, Row, Lane, Sample, Replicate, Target and Type columns (template in `templates/plate_map_template.xlsx`). The older layout with only Sample, Replicate and a running Well number also works, but it has to guess where each comb row starts. With that layout, give every gel of the run in one command and in loading order, since the numbering runs across gels.

Stephen's current ladder is HyperLadder 50bp (Meridian Bioscience/Bioline), catalogue BIO-33040, lot MW426-B097860 (label expiry August 2023; checked November 2026). Use these unless he says the pack has changed. Pass the catalogue and lot numbers so they're printed on the figure. Other ladders need a JSON file in `ladders/` (see `references/method.md`).

These are optional but worth asking about once:
- target names when they're embedded in sample IDs (for example `IgGH IgMH IgKK IgLL`), so lanes are coloured by target
- expected product sizes per target, so the table can say whether each band is the right size
- corrections to the plate map (for example "wells 70 to 72 are NC_H, NC_K, NC_L")

Don't hold the work up for the optional items. Run without them and mention what they would add.

## Get the tool

```bash
git clone --depth 1 https://github.com/cyril-kuma/my_skills.git
# if gel-labeller/ is not on main yet:
# git clone --depth 1 --branch gel-labeller https://github.com/cyril-kuma/my_skills.git
cd my_skills/gel-labeller
python3 -c "import numpy, scipy, PIL, pandas, openpyxl" || pip install -r requirements.txt  # add --break-system-packages in the cloud workspace
export PYTHONPATH=$PWD/scripts
```

Work on copies of the uploads. Never write over the original images.

## Step 1: detect

```bash
python3 -m gel_labeller detect \
  --images gel1.jpeg gel2.jpeg --plate-map wells.xlsx \
  --ladder BIO-33040 --ladder-lot MW426-B097860 \
  --targets IgGH IgMH IgKK IgLL \
  --set-well 70=NC_H 71=NC_K 72=NC_L \
  --out run1
```

This writes `run1/layout.json` and checkpoint images in `run1/qc/`, then prints a review list. A run on two gels takes about 30 seconds.

## Step 2: check before rendering

Open the checkpoint images with Read and go through this list. Don't skip it, even when the review list is empty.

1. `overlay_<gel>.png`: one "row N: K wells" line per comb, and K matches the comb in the photo. Every lane line runs down the middle of its lane, including on slanted gels. Ladder lanes are green, mismatches red.
2. `ladders_<gel>.png`: every size label sits on a band. Labels marked "(i)" were interpolated; they are fine when the band is faint, but look again if many are. The two brightest bands must be the reference bands (1000 and 300 bp for HyperLadder 50bp).
3. The review list printed by `detect` (also in `layout.json`). Each item is a place where the plate map and the image disagree or the tool had to guess. Typical ones: a row that starts later than the running well count suggests, a ladder in a well the sheet lists as NA, or a lane that looks like a ladder but is listed as a sample.

Anything that changes which sample sits in which lane needs Stephen's confirmation. Ask him with the evidence (which well, what the image shows) and don't relabel lanes on your own judgment. Cosmetic fixes and clear detection errors you can correct yourself. How to edit `layout.json` is in `references/layout.md`. For plate-map errors, re-running `detect` with a corrected sheet or `--set-well` is cleaner than editing many lanes by hand.

## Step 3: render

```bash
python3 -m gel_labeller render --layout run1/layout.json [--expected IgKK=650] [--mark-bands]
```

This writes `<gel>_labelled.png` for each gel, `results.xlsx` (sheets Samples, Lanes, Ladders, Review, Settings), `results.csv` and updated lane strips in `qc/`.

Open `qc/lanes_<gel>_row<N>.png` and compare the marked calls with the strips: red marks are Band, amber are Faint. Then open each figure and check that labels, size scales and notes are right. Use `--mark-bands` when Stephen wants the calls shown on the figure itself.

`run` does detect and render in one go. Use it only for a quick look; the checkpoint is what makes the output trustworthy.

## How calls are made

| Call | Meaning |
|---|---|
| Band | a compact band at least 8× the row's background noise, spanning the lane |
| Faint | weaker (5× to 8×) or diffuse; real signal, but treat it as weak evidence |
| No band | nothing above the size cutoff passes the checks |

The size cutoff is 200 bp by default (half the smallest expected size when expected sizes are given). Anything smaller is listed separately as possible primer dimer and doesn't count as amplification. Spots that don't span the lane (dust, a streak from a damaged well, glare from the neighbouring ladder) are ignored and noted. A band in a negative control is flagged as possible contamination. Sizes are read against the ladders on both sides of the lane, so they're approximate: expect ±5 to 10% on a 1.5% gel, and more for faint bands. The thresholds come from two gels checked lane by lane (November 2026). They can be changed with `--band-snr`, `--faint-snr` and `--min-product`; `references/method.md` explains each step.

## Rules

- Never alter the original images. Straightening a slanted gel is the only geometric change, and the figure notes say when it was done.
- Every mismatch between plate map and gel stays visible: an asterisk on the label and a note under the figure, until Stephen confirms the fix.
- Report what the image supports. Don't upgrade Faint to Band in prose, and don't call a lane clean when the table says Faint.
- If the tool fails on a new kind of image, say what failed and fix it in the repository code so the next run benefits. Don't patch around it with one-off scripts.

## Handing back

Send the labelled figures and `results.xlsx`. In the message, say how many samples amplified and which were faint, whether every negative control is clean, and anything from the review list that Stephen still needs to confirm. Leave the full lane-by-lane list in the table. Write the message in Stephen's style (the humanizer skill).
