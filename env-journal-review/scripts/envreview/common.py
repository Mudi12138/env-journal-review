"""Shared helpers: where things live, journal names, the topic taxonomy, run directories."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent                 # scripts/envreview
SKILL = PKG.parent.parent                              # the skill folder
ASSETS = SKILL / "assets"
EDITOR = PKG / "editor"
INDEX_NAME = "env-journal-index-v1"

JOURNAL_ALIASES = {
    "es&t": "environmental_science_technology", "est": "environmental_science_technology",
    "environmental science and technology": "environmental_science_technology",
    "wr": "water_research", "nw": "nature_water", "ns": "nature_sustainability",
    "ncc": "nature_climate_change", "ngeo": "nature_geoscience", "oe": "one_earth",
}


def index_dir() -> Path:
    """The index pack: $ENVREVIEW_INDEX, else ~/.envreview/<pack name>."""
    p = os.environ.get("ENVREVIEW_INDEX")
    return Path(p).expanduser() if p else Path.home() / ".envreview" / INDEX_NAME


def journals() -> dict[str, dict]:
    reg = json.loads((EDITOR / "journal_registry.json").read_text(encoding="utf-8"))
    return {j["journal_id"]: j for j in reg["journals"]}


def resolve_journal(name: str) -> str:
    js = journals()
    key = name.strip().lower()
    if key in js:
        return key
    for jid, j in js.items():
        if j["display_name"].lower() == key:
            return jid
    if key in JOURNAL_ALIASES:
        return JOURNAL_ALIASES[key]
    raise SystemExit(f"unknown journal {name!r}; choose from: "
                     + ", ".join(f"{j['display_name']} ({jid})" for jid, j in js.items()))


_ROW = re.compile(r"^\|\s*([A-J]\d)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|")


def taxonomy() -> dict[str, dict]:
    """code -> {label, covers, not_this} for the 60 subject topics A1..J3."""
    out = {}
    for line in (ASSETS / "taxonomy.md").read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m:
            code, label, covers, not_this = (x.strip() for x in m.groups())
            out[code] = {"label": label, "covers": covers,
                         "not_this": "" if not_this in ("—", "-") else not_this}
    return out


class Run:
    """A run directory holding every intermediate file, so any step can be redone."""

    def __init__(self, path: Path):
        self.dir = Path(path)
        self.state_path = self.dir / "state.json"

    @property
    def state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".part")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.state_path)

    def path(self, *parts: str) -> Path:
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def write_json(self, rel: str, obj) -> Path:
        p = self.path(rel)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    def read_json(self, rel: str):
        return json.loads(self.path(rel).read_text(encoding="utf-8"))
