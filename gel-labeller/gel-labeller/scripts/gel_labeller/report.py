"""Write the results table (CSV and Excel)."""
from __future__ import annotations

import pandas as pd

NO_BAND = "No band"

LANE_COLS = [
    ("gel", "Gel"), ("row", "Row"), ("lane", "Lane"), ("well", "Well"), ("sample", "Sample"),
    ("replicate", "Replicate"), ("target", "Target"), ("type", "Type"), ("call", "Call"),
    ("size_bp", "Size (bp)"), ("snr", "Signal/noise"), ("intensity", "Band intensity (a.u.)"),
    ("other_bands", "Other bands (bp)"), ("low_mw", "Below size cutoff (bp)"),
    ("expected_bp", "Expected (bp)"), ("flags", "Notes"),
]


def lanes_frame(results: dict) -> pd.DataFrame:
    rows = [r for r in results["lanes"] if r["type"] not in ("unloaded",)]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[c[1] for c in LANE_COLS])
    for key, _ in LANE_COLS:
        if key not in df:
            df[key] = None
    df = df[[k for k, _ in LANE_COLS]].rename(columns=dict(LANE_COLS))
    return df


def samples_frame(results: dict) -> pd.DataFrame:
    """One row per sample (all replicates side by side)."""
    groups: dict[tuple, list] = {}
    for r in results["lanes"]:
        if r["type"] not in ("sample", "pc", "nc"):
            continue
        groups.setdefault((r["sample"], r.get("target")), []).append(r)
    out = []
    for (sample, target), rs in groups.items():
        rs = sorted(rs, key=lambda r: str(r.get("replicate") or ""))
        calls = [r["call"] for r in rs]
        sizes = [r["size_value"] for r in rs if r["call"] != NO_BAND and r.get("size_value")]
        if all(c == NO_BAND for c in calls):
            summary = "Not amplified"
        elif all(c == "Band" for c in calls):
            summary = "Amplified"
        elif any(c == "Band" for c in calls):
            summary = "Amplified in some replicates"
        else:
            summary = "Faint only"
        if rs[0]["type"] == "nc":
            summary = "Clean" if all(c == NO_BAND for c in calls) else "Band present: check for contamination"
        row = dict(Sample=sample, Target=target or "", Type=rs[0]["type"], Summary=summary,
                   Replicates=len(rs))
        for i, r in enumerate(rs, 1):
            rep = r.get("replicate") or str(i)
            row[f"R{rep} call"] = r["call"]
            row[f"R{rep} size (bp)"] = r["size_bp"]
            row[f"R{rep} well"] = r.get("well")
        if len(sizes) >= 2 and max(sizes) - min(sizes) > 0.1 * max(sizes):
            row["Notes"] = "Replicate sizes differ by more than 10%."
        out.append(row)
    return pd.DataFrame(out)


def ladders_frame(layout: dict) -> pd.DataFrame:
    rows = []
    for g in layout["gels"]:
        for r in g["rows"]:
            for k, call in r.get("ladders", {}).items():
                ln = r["lanes"][int(k) - 1]
                for s, b in sorted(call["bands"].items(), key=lambda kv: -int(kv[0])):
                    rows.append({"Gel": g["name"], "Row": r["index"], "Lane": int(k), "Well": ln.get("well"),
                                 "Band (bp)": int(s), "y (px)": None if b["y"] is None else round(b["y"], 1),
                                 "Migration (px)": None if b["y"] is None else round(b["y"] - ln["well_y"], 1),
                                 "Status": b["status"]})
    return pd.DataFrame(rows)


def write(results: dict, layout: dict, csv_path: str, xlsx_path: str) -> None:
    lanes = lanes_frame(results)
    lanes.to_csv(csv_path, index=False)
    s = results.get("settings", {})
    lad = layout["ladder"]
    info = pd.DataFrame({"Item": [
        "Tool", "Layout created", "Plate map", "Ladder", "Ladder catalogue no.", "Ladder lot",
        "Size cutoff (bp)", "Band threshold (signal/noise)", "Faint threshold (signal/noise)",
        "Expected sizes", "Size tolerance",
    ], "Value": [
        layout.get("tool"), layout.get("created"), layout.get("plate_map"), lad["name"],
        lad.get("catalogue") or "", lad.get("lot") or "",
        s.get("min_product"), s.get("band_snr"), s.get("faint_snr"),
        ", ".join(f"{k}={v:g}" for k, v in (s.get("expected") or {}).items()),
        f"{100 * s.get('tolerance', 0.1):.0f}%",
    ]})
    review = pd.DataFrame({"Check before trusting the results": layout.get("review") or ["Nothing flagged."]})
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
        samples_frame(results).to_excel(xw, sheet_name="Samples", index=False)
        lanes.to_excel(xw, sheet_name="Lanes", index=False)
        ladders_frame(layout).to_excel(xw, sheet_name="Ladders", index=False)
        review.to_excel(xw, sheet_name="Review", index=False)
        info.to_excel(xw, sheet_name="Settings", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(60, max(8, width + 2))
            for c in ws[1]:
                c.font = c.font.copy(bold=True)
