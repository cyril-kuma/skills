"""Command line: python -m gel_labeller <command> ...

  detect    images + plate map -> layout.json and checkpoint images
  render    layout.json -> labelled figures, band calls, results table
  run       detect then render (no pause for review)
  template  write an empty plate map in the recommended layout
  ladders   list the ladders the tool knows
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import __version__, ladders, pipeline, platemap, qc, render, report

NO_BAND = "No band"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def _parse_pairs(items, cast=str):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"Expected KEY=VALUE, got '{it}'.")
        k, v = it.split("=", 1)
        out[k.strip()] = cast(v.strip())
    return out


def _save_layout(layout: dict, path: str) -> None:
    with open(path, "w") as fh:
        json.dump(layout, fh, indent=1, default=lambda o: o if not hasattr(o, "item") else o.item())


def _write_qc(layout: dict, out: str, calls=None) -> list[str]:
    qdir = os.path.join(out, "qc")
    os.makedirs(qdir, exist_ok=True)
    paths = []
    for g in layout["gels"]:
        s = _slug(g["name"])
        paths.append(qc.overlay(g, os.path.join(qdir, f"overlay_{s}.png")))
        paths.append(qc.ladder_sheet(g, os.path.join(qdir, f"ladders_{s}.png")))
        for row in g["rows"]:
            paths.append(qc.lane_strips(g, row, os.path.join(qdir, f"lanes_{s}_row{row['index']}.png"), calls))
    return paths


def cmd_detect(a) -> dict:
    os.makedirs(a.out, exist_ok=True)
    overrides = {int(k): v for k, v in _parse_pairs(a.set_well).items()}
    layout = pipeline.detect(a.images, a.plate_map, a.ladder, names=a.names, rows=a.rows, invert=a.invert,
                             targets=a.targets, overrides=overrides, sheet=a.sheet,
                             catalogue=a.ladder_cat, lot=a.ladder_lot)
    path = os.path.join(a.out, "layout.json")
    _save_layout(layout, path)
    _write_qc(layout, a.out)
    print(f"\nLayout written to {path}")
    print(f"Checkpoint images in {os.path.join(a.out, 'qc')}")
    _print_review(layout)
    return layout


def _print_review(layout):
    if layout.get("review"):
        print("\nCheck these before trusting the figure:")
        for m in layout["review"]:
            print("  - " + m)
    else:
        print("\nNothing flagged for review.")


def cmd_render(a, layout=None):
    if layout is None:
        with open(a.layout) as fh:
            layout = json.load(fh)
    out = a.out or os.path.dirname(os.path.abspath(a.layout))
    os.makedirs(out, exist_ok=True)
    if a.recall_ladders:
        pipeline.recall_ladders(layout)
        _save_layout(layout, os.path.join(out, "layout.json"))
    expected = _parse_pairs(a.expected, float)
    min_product = a.min_product
    if min_product is None:
        min_product = pipeline.DEFAULTS["min_product"]
        if expected:
            min_product = min(min_product, 0.5 * min(expected.values()))
    res = pipeline.analyse(layout, min_product=min_product, band_snr=a.band_snr, faint_snr=a.faint_snr,
                           expected=expected, tolerance=a.tolerance)
    figs = []
    for g in layout["gels"]:
        p = os.path.join(out, f"{_slug(g['name'])}_labelled.png")
        render.render_gel(g, layout, p, calls=res["lanes"], straighten=a.straighten, mark_bands=a.mark_bands)
        figs.append(p)
    _write_qc(layout, out, res["lanes"])
    csv_p, xlsx_p = os.path.join(out, "results.csv"), os.path.join(out, "results.xlsx")
    report.write(res, layout, csv_p, xlsx_p)
    with open(os.path.join(out, "calls.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print("Figures:")
    for p in figs:
        print("  " + p)
    print(f"Results: {xlsx_p}\n         {csv_p}")
    n = {"Band": 0, "Faint": 0, NO_BAND: 0}
    for r in res["lanes"]:
        if r["type"] in ("sample", "pc"):
            n[r["call"]] = n.get(r["call"], 0) + 1
    print(f"Sample lanes: {n['Band']} band, {n['Faint']} faint, {n[NO_BAND]} no band.")
    ncs = [r for r in res["lanes"] if r["type"] == "nc" and r["call"] != NO_BAND]
    if ncs:
        print("Negative controls with a band: " + ", ".join(f"{r['label']} (well {r['well']})" for r in ncs))
    _print_review(layout)


def cmd_template(a):
    platemap.write_template(a.out)
    print(f"Template written to {a.out}")


def cmd_ladders(a):
    for l in ladders.available():
        cats = ", ".join(l.catalogue_numbers) or "-"
        print(f"{l.id:24s} {l.name} ({len(l.sizes)} bands, {l.sizes[-1]}-{l.sizes[0]} bp; "
              f"reference {', '.join(map(str, l.reference))} bp; cat. {cats})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="gel_labeller", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def detect_args(sp):
        sp.add_argument("--images", nargs="+", required=True, help="gel images in plate-map order")
        sp.add_argument("--plate-map", required=True, help="xlsx/csv plate map")
        sp.add_argument("--sheet", default=None, help="sheet name in the plate map (default: first)")
        sp.add_argument("--ladder", default="hyperladder-50bp", help="ladder id, name, catalogue no. or JSON")
        sp.add_argument("--ladder-cat", default=None, help="catalogue number of the pack used")
        sp.add_argument("--ladder-lot", default=None, help="lot number of the pack used")
        sp.add_argument("--targets", nargs="*", default=None,
                        help="target names found inside sample IDs, e.g. IgGH IgMH IgKK IgLL")
        sp.add_argument("--set-well", nargs="*", default=None,
                        help="correct plate-map wells, e.g. 70=NC_H 71=NC_K")
        sp.add_argument("--names", nargs="*", default=None, help="gel names (default Gel 1, Gel 2 ...)")
        sp.add_argument("--rows", nargs="*", type=int, default=None, help="comb rows per gel, if known")
        sp.add_argument("--invert", action="store_true", help="image shows dark bands on a light background")

    def render_args(sp, need_layout=True):
        if need_layout:
            sp.add_argument("--layout", required=True)
        sp.add_argument("--min-product", type=float, default=None,
                        help="smallest size counted as a product (default 200 bp, or half the "
                             "smallest expected size)")
        sp.add_argument("--band-snr", type=float, default=pipeline.DEFAULTS["band_snr"])
        sp.add_argument("--faint-snr", type=float, default=pipeline.DEFAULTS["faint_snr"])
        sp.add_argument("--expected", nargs="*", default=None, help="expected sizes, e.g. IgKK=650")
        sp.add_argument("--tolerance", type=float, default=pipeline.DEFAULTS["tolerance"])
        sp.add_argument("--straighten", choices=["auto", "on", "off"], default="auto")
        sp.add_argument("--mark-bands", action="store_true", help="mark called bands on the figure")
        sp.add_argument("--recall-ladders", action="store_true",
                        help="re-call ladder bands from the (edited) lane geometry")

    sp = sub.add_parser("detect")
    detect_args(sp)
    sp.add_argument("--out", required=True)
    sp = sub.add_parser("render")
    render_args(sp)
    sp.add_argument("--out", default=None)
    sp = sub.add_parser("run")
    detect_args(sp)
    render_args(sp, need_layout=False)
    sp.add_argument("--out", required=True)
    sp = sub.add_parser("template")
    sp.add_argument("--out", default="plate_map_template.xlsx")
    sub.add_parser("ladders")

    a = p.parse_args(argv)
    if a.cmd == "detect":
        cmd_detect(a)
    elif a.cmd == "render":
        cmd_render(a)
    elif a.cmd == "run":
        layout = cmd_detect(a)
        a.layout = os.path.join(a.out, "layout.json")
        cmd_render(a, layout)
    elif a.cmd == "template":
        cmd_template(a)
    elif a.cmd == "ladders":
        cmd_ladders(a)


if __name__ == "__main__":
    main(sys.argv[1:])
