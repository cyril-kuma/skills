"""Regression test against hand-checked gels.

The gel images are research data and are not kept in this repository. Put a
folder with the images, the plate map, truth.json and truth_ladders.json
somewhere and point GEL_FIXTURES at it:

    GEL_FIXTURES=/path/to/fixtures python tests/test_gels.py

truth.json lists the expected wells per comb row, the first well of each row,
the lanes with clear and faint bands, and the negative controls.
truth_ladders.json holds hand-checked ladder band positions (y, pixels).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from gel_labeller import pipeline  # noqa: E402

FIX = os.environ.get("GEL_FIXTURES")
LADDER_TOL = 6.0      # px, bands found in the profile
INTERP_TOL = 10.0     # px, faint bands placed by interpolation


def run():
    if not FIX or not os.path.isdir(FIX):
        print("GEL_FIXTURES not set; skipping.")
        return 0
    truth = json.load(open(os.path.join(FIX, "truth.json")))
    lad_truth = json.load(open(os.path.join(FIX, "truth_ladders.json")))
    a = truth["args"]
    layout = pipeline.detect([os.path.join(FIX, p) for p in a["images"]], os.path.join(FIX, a["plate_map"]),
                             a["ladder"], targets=a["targets"],
                             overrides={int(k): v for k, v in a["set_well"].items()}, log=lambda *_: None)
    fails = []
    # combs and wells
    got = [[r["n_wells"] for r in g["rows"]] for g in layout["gels"]]
    if got != truth["wells_per_row"]:
        fails.append(f"wells per row {got} != {truth['wells_per_row']}")
    first = [[next((ln["well"] for ln in r["lanes"] if ln.get("well")), None) for r in g["rows"]]
             for g in layout["gels"]]
    if first != truth["first_well_of_row"]:
        fails.append(f"first well per row {first} != {truth['first_well_of_row']}")
    stars = [ln.get("well") for g in layout["gels"] for r in g["rows"] for ln in r["lanes"]
             if ln.get("label") == "Ladder*"]
    if stars != [truth["ladder_star_well"]]:
        fails.append(f"Ladder* wells {stars}")
    # ladder positions
    worst = 0.0
    for key, (gi, ri, li) in truth["ladder_keys"].items():
        call = layout["gels"][gi - 1]["rows"][ri - 1]["ladders"].get(str(li))
        if call is None:
            fails.append(f"no ladder call for {key}")
            continue
        for s, y in lad_truth[key].items():
            b = call["bands"].get(int(s)) or call["bands"].get(s)
            if b is None or b["y"] is None:
                fails.append(f"{key} {s} bp missing")
                continue
            err = abs(b["y"] - y)
            worst = max(worst, err)
            tol = INTERP_TOL if b["status"] == "interpolated" else LADDER_TOL
            if err > tol:
                fails.append(f"{key} {s} bp ({b['status']}) off by {err:.1f} px")
    # band calls
    res = pipeline.analyse(layout)
    by_well = {r["well"]: r for r in res["lanes"] if r.get("well")}
    for w in truth["band_wells"]:
        if by_well[w]["call"] != "Band":
            fails.append(f"well {w}: expected Band, got {by_well[w]['call']}")
    for w in truth["faint_wells"]:
        if by_well[w]["call"] != "Faint":
            fails.append(f"well {w}: expected Faint, got {by_well[w]['call']}")
    expected_any = set(truth["band_wells"]) | set(truth["faint_wells"])
    for w, r in by_well.items():
        if r["type"] in ("sample", "nc") and w not in expected_any and r["call"] != pipeline.NO_BAND:
            fails.append(f"well {w}: unexpected {r['call']} at {r['size_bp']} bp")
    print(f"worst ladder band error: {worst:.1f} px")
    if fails:
        print("FAILED:\n  " + "\n  ".join(fails))
        return 1
    print("All checks passed.")
    return 0


def test_gels():
    assert run() == 0


if __name__ == "__main__":
    sys.exit(run())
