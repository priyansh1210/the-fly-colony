"""YAML loading through pydantic schemas, with file:line error reports (CONN-R-070)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


class ConfigError(ValueError):
    """A config file failed to parse or validate. The message lists file:line for each problem."""


def _line_map(node: yaml.Node, path: tuple[Any, ...] = (), out: dict | None = None) -> dict:
    """Map every value path (as used in pydantic error locations) to its 1-based line."""
    out = {} if out is None else out
    out[path] = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = key_node.value
            out[(*path, key)] = key_node.start_mark.line + 1
            _line_map(value_node, (*path, key), out)
    elif isinstance(node, yaml.SequenceNode):
        for i, item in enumerate(node.value):
            _line_map(item, (*path, i), out)
    return out


def _line_for(loc: tuple[Any, ...], lines: dict) -> int:
    """Longest-prefix match of a pydantic error location onto the YAML line map."""
    for n in range(len(loc), -1, -1):
        if loc[:n] in lines:
            return lines[loc[:n]]
    return 1


def load_yaml(path: Path) -> tuple[Any, dict]:
    """Return (data, line_map) for a YAML file."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        node = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    return data, (_line_map(node) if node is not None else {})


def validate[M: BaseModel](model: type[M], data: Any, lines: dict, path: Path | str) -> M:
    """Validate data against a schema, converting errors to file:line messages."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        msgs = []
        for err in exc.errors():
            loc = tuple(err["loc"])
            # Unknown keys are reported at the key itself.
            where = ".".join(str(p) for p in loc) or "<root>"
            msgs.append(f"{path}:{_line_for(loc, lines)}: {where}: {err['msg']}")
        raise ConfigError("\n".join(msgs)) from None


def load_config[M: BaseModel](model: type[M], path: Path | str) -> M:
    """Load one YAML file into a pydantic model (unknown keys and bad values rejected)."""
    data, lines = load_yaml(Path(path))
    return validate(model, data if data is not None else {}, lines, path)


def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8 safe. Used for snapshots and hashes."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj: Any) -> str:
    """SHA-256 of the canonical JSON of an object (CONN-R-071, CONN-R-084)."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
