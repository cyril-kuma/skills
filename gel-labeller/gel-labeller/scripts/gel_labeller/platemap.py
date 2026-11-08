"""Read a plate map (which sample went into which well).

Two layouts are accepted.

Full layout (recommended), one row per loaded lane:
    Gel | Row | Lane | Sample | Replicate | Target | Type
Gel is 1, 2, ... in the order the images are given (or the image file name),
Row counts comb rows from the top, Lane counts wells from the left.

Running-number layout (the older sheet):
    Sample | Replicate | Well
Wells are numbered 1, 2, 3 ... across every comb row of every gel in order.
Where a gel row starts is then inferred from the number of wells found on
each comb, which can be wrong, so every lane is checked against the image.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pandas as pd

EMPTY_WORDS = {"", "na", "n/a", "nan", "none", "empty", "blank", "-", "--", "x"}
LADDER_RE = re.compile(r"^(ladder|marker|mw|dna ladder|l|m)$|ladder|marker", re.I)
NC_RE = re.compile(r"^(nc|ntc|neg|negative|blank control|water)([_\- ]|$)|^nc", re.I)
PC_RE = re.compile(r"^(pc|pos|positive)([_\- ]|$)", re.I)

COLUMN_ALIASES = {
    "sample": ["sample", "sample id", "sampleid", "sample_id", "name", "sample name", "id"],
    "replicate": ["replicate", "rep", "replicate number"],
    "well": ["well", "well number", "well no", "well_no", "position", "lane number"],
    "gel": ["gel", "gel number", "gel id", "image"],
    "row": ["row", "comb", "comb row", "tier"],
    "lane": ["lane", "lane number", "lane no", "well in row", "position in row"],
    "target": ["target", "gene", "assay", "group", "primer", "primers"],
    "type": ["type", "lane type", "kind", "role"],
}


@dataclass
class Entry:
    sample: str
    type: str                  # sample | ladder | nc | pc | empty
    replicate: str | None = None
    target: str | None = None
    well: int | None = None
    gel: str | None = None
    row: int | None = None
    lane: int | None = None

    @property
    def label(self) -> str:
        if self.type == "ladder":
            return "Ladder"
        if self.type == "empty":
            return "NA"
        if self.replicate not in (None, ""):
            return f"{self.sample}_R{self.replicate}"
        return self.sample


def _norm_cols(df: pd.DataFrame) -> dict[str, str]:
    found = {}
    lower = {str(c).strip().lower(): c for c in df.columns}
    for key, names in COLUMN_ALIASES.items():
        for n in names:
            if n in lower:
                found[key] = lower[n]
                break
    return found


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if re.fullmatch(r"-?\d+\.0", s):
        s = s[:-2]
    return s


def classify(sample: str, type_hint: str = "") -> str:
    t = type_hint.strip().lower()
    if t:
        if t.startswith("lad") or t.startswith("mark"):
            return "ladder"
        if t in ("nc", "ntc", "negative", "neg", "negative control"):
            return "nc"
        if t in ("pc", "positive", "pos", "positive control"):
            return "pc"
        if t in ("empty", "na", "blank", "none"):
            return "empty"
        return "sample"
    s = sample.strip()
    if s.lower() in EMPTY_WORDS:
        return "empty"
    if LADDER_RE.search(s):
        return "ladder"
    if NC_RE.match(s):
        return "nc"
    if PC_RE.match(s):
        return "pc"
    return "sample"


def infer_target(sample: str, targets: list[str] | None) -> str | None:
    if not targets:
        return None
    hits = [t for t in targets if t.lower() in sample.lower()]
    return max(hits, key=len) if hits else None


def read(path: str, sheet: str | int | None = None, targets: list[str] | None = None,
         overrides: dict[int, str] | None = None) -> tuple[list[Entry], str]:
    """Return (entries, layout) where layout is 'full' or 'running'."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".tsv", ".txt"):
        df = pd.read_csv(path, sep=None, engine="python", dtype=str)
    else:
        df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, dtype=str)
    df = df.dropna(how="all")
    cols = _norm_cols(df)
    if "sample" not in cols:
        raise SystemExit(f"Plate map {path} needs a Sample column. Found: {list(df.columns)}")
    full = all(k in cols for k in ("gel", "row", "lane"))
    if not full and "well" not in cols:
        raise SystemExit("Plate map needs either Gel, Row and Lane columns, or a running Well column.")
    entries = []
    for _, r in df.iterrows():
        sample = _clean(r[cols["sample"]])
        rep = _clean(r[cols["replicate"]]) if "replicate" in cols else ""
        typ = classify(sample, _clean(r[cols["type"]]) if "type" in cols else "")
        tgt = _clean(r[cols["target"]]) if "target" in cols else ""
        e = Entry(sample=sample if typ != "empty" else "NA", type=typ,
                  replicate=rep or None,
                  target=tgt or (infer_target(sample, targets) if typ in ("sample", "pc") else None))
        if full:
            gel = _clean(r[cols["gel"]])
            row, lane = _clean(r[cols["row"]]), _clean(r[cols["lane"]])
            if not (gel and row and lane):
                continue
            e.gel, e.row, e.lane = gel, int(float(row)), int(float(lane))
            if "well" in cols and _clean(r[cols["well"]]):
                e.well = int(float(_clean(r[cols["well"]])))
        else:
            w = _clean(r[cols["well"]])
            if not w:
                continue
            e.well = int(float(w))
        entries.append(e)
    if overrides:
        by_well = {e.well: e for e in entries if e.well is not None}
        for well, name in overrides.items():
            typ = classify(name)
            if well in by_well:
                e = by_well[well]
                e.sample, e.type = name, typ
                e.target = infer_target(name, targets) if typ in ("sample", "pc") else None
            else:
                entries.append(Entry(sample=name, type=typ, well=well))
    if not full:
        entries.sort(key=lambda e: e.well)
    return entries, ("full" if full else "running")


def write_template(path: str) -> None:
    rows = []
    for gel in (1,):
        for row in (1, 2):
            for lane in range(1, 25):
                if lane in (1, 24):
                    rows.append(dict(Gel=gel, Row=row, Lane=lane, Sample="Ladder", Replicate="",
                                     Target="", Type="ladder"))
                else:
                    rows.append(dict(Gel=gel, Row=row, Lane=lane, Sample="", Replicate="",
                                     Target="", Type=""))
    df = pd.DataFrame(rows, columns=["Gel", "Row", "Lane", "Sample", "Replicate", "Target", "Type"])
    notes = pd.DataFrame({"How to fill this in": [
        "One row per lane. Gel = 1, 2, ... in the order the images are given.",
        "Row = comb row counted from the top of the gel. Lane = well counted from the left, starting at 1.",
        "Sample: sample ID, or Ladder, or NA for an empty well.",
        "Replicate: 1, 2, ... (optional). The figure shows Sample_R1, Sample_R2.",
        "Target: the PCR target or primer set (optional). Lanes are coloured by target.",
        "Type (optional): sample, ladder, nc, pc or empty. Left blank, it is worked out from the sample name.",
        "Leave unloaded wells out or mark them NA.",
    ]})
    with pd.ExcelWriter(path) as xw:
        df.to_excel(xw, sheet_name="Plate map", index=False)
        notes.to_excel(xw, sheet_name="Notes", index=False)
