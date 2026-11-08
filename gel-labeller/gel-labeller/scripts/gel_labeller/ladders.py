"""Ladder definitions.

Each ladder is a JSON file in the skill's ladders/ folder (or any path given
on the command line) listing band sizes in bp, ng per band for the standard
load, and the bright reference bands used to anchor band assignment.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

LADDER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "ladders")


@dataclass
class Ladder:
    id: str
    name: str
    sizes: list[int]                     # largest first
    ng: dict[int, float]
    reference: list[int]                 # brightest first
    manufacturer: str = ""
    catalogue_numbers: dict = field(default_factory=dict)
    source: str = ""
    catalogue: str | None = None         # the pack in use, if given
    lot: str | None = None

    @property
    def primary(self) -> list[int]:
        """Reference bands with the highest load: used as anchors."""
        top = max(self.ng[s] for s in self.reference)
        return sorted([s for s in self.reference if self.ng[s] >= 0.9 * top], reverse=True)

    def describe(self) -> str:
        parts = [self.name]
        if self.catalogue:
            parts.append(f"cat. {self.catalogue}")
        if self.lot:
            parts.append(f"lot {self.lot}")
        return ", ".join(parts)


def _from_json(d: dict) -> Ladder:
    bands = sorted(d["bands"], key=lambda b: -b["bp"])
    return Ladder(
        id=d["id"], name=d["name"],
        sizes=[int(b["bp"]) for b in bands],
        ng={int(b["bp"]): float(b.get("ng", 0)) for b in bands},
        reference=[int(s) for s in d.get("reference_bands", [])],
        manufacturer=d.get("manufacturer", ""),
        catalogue_numbers=d.get("catalogue_numbers", {}),
        source=d.get("source", ""),
    )


def available() -> list[Ladder]:
    out = []
    for fn in sorted(os.listdir(LADDER_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(LADDER_DIR, fn)) as fh:
                out.append(_from_json(json.load(fh)))
    return out


def load(spec: str, catalogue: str | None = None, lot: str | None = None) -> Ladder:
    """Load a ladder by id, name, alias, catalogue number or JSON path."""
    if os.path.isfile(spec):
        with open(spec) as fh:
            lad = _from_json(json.load(fh))
    else:
        key = spec.strip().lower().replace("_", "-")
        lad = None
        for fn in sorted(os.listdir(LADDER_DIR)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(LADDER_DIR, fn)) as fh:
                d = json.load(fh)
            names = [d["id"], d["name"]] + d.get("aliases", []) + list(d.get("catalogue_numbers", {}))
            if any(key == n.lower().replace("_", "-") for n in names) or \
               any(key.replace(" ", "") == n.lower().replace(" ", "").replace("-", "") for n in names):
                lad = _from_json(d)
                if spec.upper() in d.get("catalogue_numbers", {}) and not catalogue:
                    catalogue = spec.upper()
                break
        if lad is None:
            known = ", ".join(l.id for l in available())
            raise SystemExit(f"Unknown ladder '{spec}'. Known ladders: {known}. "
                             f"Add a JSON file to {LADDER_DIR} for a new one.")
    lad.catalogue = catalogue
    lad.lot = lot
    if len(lad.primary) < 2:
        raise SystemExit(f"Ladder {lad.name} needs at least two equally bright reference bands "
                         f"(reference_bands with the highest ng) to anchor band assignment.")
    return lad
