"""Parameter Registry: the single source of every model parameter (spec 001 §4.9, CONST-6)."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from flycolony.config.loader import ConfigError, content_hash, load_yaml, validate
from flycolony.config.schemas import project_root

Value = float | int | str | bool | list[float] | list[int] | list[str]

_SCOPE = re.compile(r"^(global|sex:(female|male)|cell_type:[^\s]+|class:[^\s]+)$")
_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    authors: str
    year: int
    doi: str | None = None
    url: str | None = None
    where: str | None = None  # figure, table, or file/line


class Assumption(_Strict):
    rationale: str
    owner: str


class Calibration(_Strict):
    run_id: str
    date: str
    objective: str


class Entry(_Strict):
    id: str
    value: Value
    units: str
    valid_range: tuple[float, float] | None = None
    scope: str = "global"
    source: Source | None = None
    assumption: Assumption | None = None
    owner_spec: str | None = None
    calibrated: Calibration | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> Entry:
        if not _ID.match(self.id):
            raise ValueError(f"id {self.id!r} must be dotted lower_snake, e.g. brain.lif.v_thresh")
        if (self.source is None) == (self.assumption is None):
            raise ValueError("exactly one of 'source' or 'assumption' is required (CONN-R-080)")
        if not _SCOPE.match(self.scope):
            raise ValueError(
                f"scope {self.scope!r} must be global, sex:<female|male>, cell_type:<X> or class:<Y>"
            )
        if self.valid_range is not None:
            lo, hi = self.valid_range
            if lo > hi:
                raise ValueError("valid_range must be [low, high]")
            if not in_range(self.value, self.valid_range):
                raise ValueError(
                    f"value {self.value!r} outside valid_range {list(self.valid_range)}"
                )
        return self

    @property
    def is_assumption(self) -> bool:
        return self.assumption is not None


class RegistryFile(_Strict):
    entries: list[Entry] = Field(default_factory=list)


def in_range(value: Any, rng: tuple[float, float]) -> bool:
    lo, hi = rng
    values = value if isinstance(value, list) else [value]
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int | float):
            return False
        if not lo <= v <= hi:
            return False
    return True


class RegistryError(RuntimeError):
    """A parameter is missing, out of range, or a change breaks the registry rules."""


class Registry:
    """An immutable view of the registry. Use `apply_calibration` to derive a changed copy."""

    def __init__(self, entries: list[Entry]):
        by_id: dict[str, Entry] = {}
        dupes = []
        for e in entries:
            if e.id in by_id:
                dupes.append(e.id)
            by_id[e.id] = e
        if dupes:
            raise RegistryError(f"duplicate registry ids: {sorted(set(dupes))}")
        self._by_id = dict(sorted(by_id.items()))

    # --- loading ---------------------------------------------------------------------------

    @classmethod
    def load(cls, directory: Path | None = None) -> Registry:
        """Load every *.yaml under config/params/ that has a top-level `entries` list."""
        directory = directory or project_root() / "config" / "params"
        entries: list[Entry] = []
        for path in sorted(Path(directory).glob("*.yaml")):
            data, lines = load_yaml(path)
            if not isinstance(data, dict) or "entries" not in data:
                continue
            entries.extend(validate(RegistryFile, data, lines, path).entries)
        return cls(entries)

    # --- lookup ----------------------------------------------------------------------------

    def __contains__(self, pid: str) -> bool:
        return pid in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def entries(self) -> list[Entry]:
        return list(self._by_id.values())

    def entry(self, pid: str) -> Entry:
        try:
            return self._by_id[pid]
        except KeyError:
            raise RegistryError(f"parameter {pid!r} is not in the registry") from None

    def get(self, pid: str) -> Any:
        return self.entry(pid).value

    def require(self, ids: list[str] | set[str]) -> None:
        """Refuse to start if any referenced parameter is missing or out of range (CONN-R-082)."""
        problems = []
        for pid in sorted(ids):
            e = self._by_id.get(pid)
            if e is None:
                problems.append(f"missing: {pid}")
            elif e.valid_range is not None and not in_range(e.value, e.valid_range):
                problems.append(f"out of range: {pid} = {e.value!r} not in {list(e.valid_range)}")
        if problems:
            raise RegistryError("registry check failed:\n  " + "\n  ".join(problems))

    # --- versioning and reporting ----------------------------------------------------------

    def content_hash(self) -> str:
        """Version of the registry = hash of its sorted entries (CONN-R-084)."""
        return content_hash([e.model_dump(mode="json") for e in self.entries()])

    def assumption_report(self) -> list[dict]:
        """Count and share of ASSUMPTION entries per owner spec (CONN-R-083, CONST-6.3)."""
        total: Counter[str] = Counter()
        assumed: Counter[str] = Counter()
        for e in self.entries():
            spec = e.owner_spec or "unowned"
            total[spec] += 1
            assumed[spec] += e.is_assumption
        return [
            {
                "owner_spec": s,
                "entries": total[s],
                "assumptions": assumed[s],
                "share": assumed[s] / total[s],
            }
            for s in sorted(total)
        ]

    def dump_yaml(self) -> str:
        data = {"entries": [e.model_dump(mode="json", exclude_none=True) for e in self.entries()]}
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def apply_calibration(
    registry: Registry,
    changes: dict[str, Value],
    run_id: str,
    objective: str,
    on: date | None = None,
) -> Registry:
    """Return a new registry with calibrated values (CONN-R-085, CONST-1.3).

    Every scope the registry can express applies to all flies alike, so calibration is global
    by construction. Unknown ids and out-of-range values are refused, and every changed entry
    records the run id, date and objective.
    """
    if not run_id or not objective:
        raise RegistryError("a calibration needs a run_id and an objective")
    stamp = Calibration(run_id=run_id, date=(on or date.today()).isoformat(), objective=objective)
    new = {e.id: e for e in registry.entries()}
    for pid, value in sorted(changes.items()):
        if pid not in new:
            raise RegistryError(f"calibration refers to unknown parameter {pid!r}")
        old = new[pid]
        try:
            new[pid] = Entry.model_validate(
                {**old.model_dump(), "value": value, "calibrated": stamp.model_dump()}
            )
        except Exception as exc:  # pydantic ValidationError -> registry rule violation
            raise RegistryError(f"calibration of {pid} rejected: {exc}") from None
    return Registry(list(new.values()))


__all__ = [
    "ConfigError",
    "Entry",
    "Registry",
    "RegistryError",
    "apply_calibration",
]
