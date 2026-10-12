"""Dataset catalog, license gate, fetching and credential redaction (spec 001 §4.1)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from flycolony.config.loader import load_config
from flycolony.config.schemas import project_root


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class License(_Strict):
    name: str
    url: str
    status: Literal["verified", "assumed"]
    checked: str
    evidence: str
    restrictions: str
    attribution: str


class DataFile(_Strict):
    name: str
    url: str
    size: int | None = None
    md5: str | None = None
    sha256: str | None = None
    optional: bool = False


class Dataset(_Strict):
    title: str
    version: str
    homepage: str
    license: License | None = None
    files: list[DataFile] = Field(min_length=1)


class Catalog(_Strict):
    datasets: dict[str, Dataset]


class LicenseError(RuntimeError):
    """A dataset may not be used because its license entry is missing (CONN-R-003)."""


class FetchError(RuntimeError):
    """A download failed or did not match its published size or checksum."""


def load_catalog(path: Path | None = None) -> Catalog:
    return load_config(Catalog, path or project_root() / "config" / "datasets.yaml")


def require_license(catalog: Catalog, dataset_id: str) -> License:
    """License gate: refuse to build from a dataset without a license entry (CONN-R-003)."""
    ds = catalog.datasets.get(dataset_id)
    if ds is None:
        raise LicenseError(f"dataset {dataset_id!r} is not in the catalog")
    if ds.license is None:
        raise LicenseError(f"dataset {dataset_id!r} has no license entry; refusing to build")
    return ds.license


def render_licenses_md(catalog: Catalog) -> str:
    """Render data/LICENSES.md from the catalog (CONN-R-002)."""
    lines = [
        "# Dataset licenses",
        "",
        "Generated from `config/datasets.yaml` by `colony data licenses`. Do not edit by hand.",
        "",
        "| Dataset | License | Status | Restrictions |",
        "|---|---|---|---|",
    ]
    for ds_id, ds in sorted(catalog.datasets.items()):
        lic = ds.license
        if lic is None:
            lines.append(f"| `{ds_id}` | **MISSING** | builds refused | — |")
        else:
            lines.append(
                f"| `{ds_id}` | [{lic.name}]({lic.url}) | {lic.status} | {lic.restrictions} |"
            )
    for ds_id, ds in sorted(catalog.datasets.items()):
        lines += ["", f"## `{ds_id}`: {ds.title}", "", f"- **Version:** {ds.version}"]
        lines.append(f"- **Source:** {ds.homepage}")
        if ds.license:
            lic = ds.license
            lines += [
                f"- **License:** [{lic.name}]({lic.url}) ({lic.status}, checked {lic.checked})",
                f"- **Evidence:** {lic.evidence}",
                f"- **Restrictions:** {lic.restrictions}",
                f"- **Required attribution:** {lic.attribution}",
            ]
        else:
            lines.append("- **License:** missing. The pipeline refuses to build from this dataset.")
    return "\n".join(lines) + "\n"


# --- credentials (CONN-R-005) --------------------------------------------------------------

CREDENTIAL_ENV_VARS = ("NEUPRINT_APPLICATION_CREDENTIALS", "CODEX_API_TOKEN", "CAVE_TOKEN")
_TOKENISH = re.compile(
    r"(?i)(token|authorization|api[_-]?key)(\s*[:=]\s*|\s+)(bearer\s+)?([^\s,;\"']+)"
)


def redact(text: str) -> str:
    """Remove credential values (from known env vars) and token-like fields from text."""
    for var in CREDENTIAL_ENV_VARS:
        value = os.environ.get(var)
        if value:
            text = text.replace(value, f"<{var}:redacted>")
    return _TOKENISH.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or ''}<redacted>", text)


# --- fetching (CONN-R-001, CONN-R-004) ----------------------------------------------------


def _hashes(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(8 << 20):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def raw_dir(dataset_id: str, root: Path | None = None) -> Path:
    return (root or project_root() / "data" / "raw") / dataset_id


def _check(f: DataFile, path: Path) -> tuple[str, str]:
    size = path.stat().st_size
    if f.size is not None and size != f.size:
        raise FetchError(f"{f.name}: size {size} != published {f.size}")
    md5, sha = _hashes(path)
    if f.md5 and md5 != f.md5:
        raise FetchError(f"{f.name}: md5 {md5} != published {f.md5}")
    if f.sha256 and sha != f.sha256:
        raise FetchError(f"{f.name}: sha256 {sha} != pinned {f.sha256}")
    return md5, sha


RETRIES = 6
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _download(client: httpx.Client, f: DataFile, tmp: Path, log) -> None:
    """Stream a file to `tmp`, retrying transient failures and resuming partial downloads."""
    for attempt in range(1, RETRIES + 1):
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with client.stream("GET", f.url, headers=headers) as resp:
                if resp.status_code in _RETRY_STATUS:
                    raise FetchError(f"HTTP {resp.status_code}")
                if resp.status_code not in (200, 206):
                    raise FetchError(redact(f"{f.name}: HTTP {resp.status_code} from {f.url}"))
                mode = "ab" if resp.status_code == 206 else "wb"  # 200 = server ignored Range
                with tmp.open(mode) as fh:
                    for chunk in resp.iter_bytes(8 << 20):
                        fh.write(chunk)
            return
        except (httpx.TransportError, FetchError) as exc:
            if isinstance(exc, FetchError) and not str(exc).startswith("HTTP "):
                raise
            if attempt == RETRIES:
                raise FetchError(
                    redact(f"{f.name}: giving up after {RETRIES} attempts ({exc})")
                ) from exc
            wait = min(2**attempt, 60)
            log(f"  retry   {f.name} in {wait}s ({exc})")
            time.sleep(wait)


def fetch(
    catalog: Catalog,
    dataset_id: str,
    root: Path | None = None,
    include_optional: bool = False,
    log=print,
) -> Path:
    """Download a dataset into data/raw/<id>/ and write _source.json. Existing verified files are kept."""
    ds = catalog.datasets[dataset_id]
    out = raw_dir(dataset_id, root)
    out.mkdir(parents=True, exist_ok=True)
    record = {"dataset": dataset_id, "version": ds.version, "homepage": ds.homepage, "files": {}}
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=600.0)) as client:
        for f in ds.files:
            if f.optional and not include_optional:
                continue
            dest = out / f.name
            if dest.exists():
                try:
                    md5, sha = _check(f, dest)
                    log(f"  ok      {f.name}")
                    record["files"][f.name] = {
                        "url": f.url,
                        "sha256": sha,
                        "md5": md5,
                        "size": dest.stat().st_size,
                        "reused": True,
                    }
                    continue
                except FetchError as exc:
                    log(f"  stale   {f.name} ({exc}); downloading again")
                    dest.unlink()
            tmp = dest.with_suffix(dest.suffix + ".part")
            log(f"  fetch   {f.name}")
            _download(client, f, tmp, log)
            md5, sha = _check(f, tmp)
            tmp.replace(dest)
            record["files"][f.name] = {
                "url": f.url,
                "sha256": sha,
                "md5": md5,
                "size": dest.stat().st_size,
                "reused": False,
            }
    record["retrieved_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    (out / "_source.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )
    return out


def source_record(dataset_id: str, root: Path | None = None) -> dict:
    """The _source.json of a fetched dataset (raises FileNotFoundError if not fetched)."""
    return json.loads((raw_dir(dataset_id, root) / "_source.json").read_text(encoding="utf-8"))
