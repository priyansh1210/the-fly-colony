"""BrainTemplate build, storage, verification and loading (spec 001 §4.2, §4.6, §4.7)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import psutil
import pyarrow.parquet as pq
from safetensors.numpy import load_file, save_file

from flycolony.config.schemas import project_root
from flycolony.connectome.inputs import (
    CONNECTION_SCHEMA,
    NEURON_SCHEMA,
    NEUROPIL_SCHEMA,
    BuildInputs,
    conform,
)
from flycolony.connectome.iomap import IoMap, resolve_iomap
from flycolony.connectome.typegraph import build_type_graph
from flycolony.registry import Registry

PIPELINE_SCHEMA_VERSION = 1
GIB = 1024**3

# Registry parameters the builder reads (checked up front, CONN-R-082).
REGISTRY_IDS = {
    "conn.min_synapses",
    "conn.sign.acetylcholine",
    "conn.sign.gaba",
    "conn.sign.glutamate",
    "conn.sign.dopamine",
    "conn.sign.serotonin",
    "conn.sign.octopamine",
    "conn.sign.unknown",
    "conn.sign_exceptions",
    "conn.graded_cell_types",
    "conn.build.max_rss_gb",
}

FLAG_RULES = {  # flag -> super_class values (design §5.1 step 3)
    "is_sensory": ("sensory", "sensory_ascending"),
    "is_descending": ("descending",),
    "is_ascending": ("ascending", "sensory_ascending"),
    "is_motor": ("motor",),
    "is_neurosecretory": ("endocrine",),
}
AMINES = ("dopamine", "serotonin", "octopamine")


class TemplateError(RuntimeError):
    """The build failed a requirement (counts, references, license, memory)."""


class TemplateIntegrityError(RuntimeError):
    """A stored template does not match its manifest (CONN-R-051)."""


# --- helpers -------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def pipeline_version() -> str:
    """Commit of the code that built an artifact, with `-dirty` if pipeline inputs are uncommitted.

    `git describe --dirty` ignores untracked files, so new, uncommitted code would otherwise be
    recorded as the last commit. Here any change (tracked or untracked) under src/, config/,
    tools/ or pyproject.toml marks the version dirty.
    """
    root = project_root()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "src", "config", "tools", "pyproject.toml"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return f"{commit}-dirty" if status else commit


def write_parquet(df: pl.DataFrame, path: Path) -> None:
    """Deterministic Parquet: fixed codec, level and row-group size (CONN-R-052)."""
    pq.write_table(
        df.to_arrow(),
        path,
        compression="zstd",
        compression_level=3,
        row_group_size=1 << 20,
        use_dictionary=True,
        write_statistics=True,
    )


class PeakRss:
    """Samples this process's RSS in a background thread (CONN-R-053)."""

    def __init__(self, interval: float = 0.1):
        self.interval, self.peak, self._stop = interval, 0, threading.Event()
        self._proc = psutil.Process()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self._proc.memory_info().rss)
            self._stop.wait(self.interval)

    def __enter__(self) -> PeakRss:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, self._proc.memory_info().rss)

    @property
    def peak_gb(self) -> float:
        return self.peak / GIB


# --- build steps ---------------------------------------------------------------------------


def _sign_table(reg: Registry) -> dict[str, int]:
    table = {
        nt: int(reg.get(f"conn.sign.{nt}"))
        for nt in ("acetylcholine", "gaba", "glutamate", "dopamine", "serotonin", "octopamine")
    }
    return table


def _exceptions(reg: Registry) -> dict[str, int]:
    out = {}
    for item in reg.get("conn.sign_exceptions"):
        cell_type, _, sign = str(item).partition("=")
        if sign.strip() not in ("-1", "0", "1"):
            raise TemplateError(f"conn.sign_exceptions entry {item!r} must look like 'TYPE=-1|0|1'")
        out[cell_type.strip()] = int(sign)
    return out


def build_neuron_table(inputs: BuildInputs, reg: Registry) -> pl.DataFrame:
    """Neuron table with dense ids, sign, model flag and class flags (CONN-R-010, -012, -013).

    Sign precedence: registry exception > reference model (optional `sign_ref` input column,
    CONN-OQ-03) > transmitter rule. The winning rule is stored in `sign_source`.
    """
    has_ref = "sign_ref" in inputs.neurons.collect_schema().names()
    schema = {
        **NEURON_SCHEMA,
        **{name: pl.String for name in inputs.extra_neuron_columns},
        **({"sign_ref": pl.Int8} if has_ref else {}),
    }
    neurons = conform(inputs.neurons, schema).collect(engine="streaming")
    if not has_ref:
        neurons = neurons.with_columns(pl.lit(None, dtype=pl.Int8).alias("sign_ref"))
    dupes = neurons["source_id"].is_duplicated().sum()
    if dupes:
        raise TemplateError(f"{dupes} duplicate source ids in the neuron list")
    neurons = (
        neurons.sort("source_id")
        .with_row_index("neuron_id")
        .with_columns(pl.col("neuron_id").cast(pl.Int32))
    )

    signs = _sign_table(reg)
    exceptions = _exceptions(reg)
    unknown = int(reg.get("conn.sign.unknown"))
    graded = set(reg.get("conn.graded_cell_types"))

    is_exception = pl.col("cell_type").is_in(list(exceptions)).fill_null(False)
    sign_expr = (
        pl.when(is_exception)
        .then(pl.col("cell_type").replace_strict(exceptions, default=None, return_dtype=pl.Int8))
        .when(pl.col("sign_ref").is_not_null())
        .then(pl.col("sign_ref"))
        .otherwise(pl.col("nt_pred").replace_strict(signs, default=unknown, return_dtype=pl.Int8))
    )
    source_expr = (
        pl.when(is_exception)
        .then(pl.lit("exception"))
        .when(pl.col("sign_ref").is_not_null())
        .then(pl.lit("reference"))
        .otherwise(pl.lit("transmitter"))
    )
    flags = [
        pl.col("super_class").is_in(list(values)).fill_null(False).alias(flag)
        for flag, values in FLAG_RULES.items()
    ]
    return neurons.with_columns(
        sign_expr.alias("sign"),
        source_expr.alias("sign_source"),
        pl.when(pl.col("cell_type").is_in(list(graded)))
        .then(pl.lit("graded"))
        .otherwise(pl.lit("spiking"))
        .alias("model"),
        pl.col("nt_pred").is_in(list(AMINES)).fill_null(False).alias("is_modulatory"),
        *flags,
    ).drop("sign_ref")


def build_edges(
    inputs: BuildInputs, neurons: pl.DataFrame, reg: Registry
) -> tuple[dict[str, np.ndarray], dict]:
    """CSR edges + transposed index (CONN-R-011). Pairs outside the neuron set are dropped."""
    min_syn = int(reg.get("conn.min_synapses"))
    ids = neurons.select(pl.col("source_id"), pl.col("neuron_id"), pl.col("sign")).lazy()
    pairs = (
        conform(inputs.connections, CONNECTION_SCHEMA)
        .group_by("pre", "post")
        .agg(pl.col("syn_count").sum())
        .join(
            ids.rename({"source_id": "pre", "neuron_id": "pre_id", "sign": "pre_sign"}),
            on="pre",
            how="inner",
        )
        .join(
            ids.select(pl.col("source_id").alias("post"), pl.col("neuron_id").alias("post_id")),
            on="post",
            how="inner",
        )
    )
    # One streaming pass; the threshold is applied afterwards so both counts are reported.
    kept = (
        pairs.select(
            pl.col("pre_id"), pl.col("post_id"), pl.col("syn_count").cast(pl.Int32), "pre_sign"
        )
        .sort("pre_id", "post_id")
        .collect(engine="streaming")
    )
    n_before, syn_before = kept.height, int(kept["syn_count"].sum() or 0)
    kept = kept.filter(pl.col("syn_count") >= min_syn)
    n = neurons.height
    pre = kept["pre_id"].to_numpy().astype(np.int32)
    post = kept["post_id"].to_numpy().astype(np.int32)
    syn = kept["syn_count"].to_numpy().astype(np.int32)
    weight = (syn * kept["pre_sign"].to_numpy()).astype(np.float32)
    del kept

    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(pre, minlength=n), out=indptr[1:])
    # Transposed index: edges sorted by (post, pre); t_perm maps each to its CSR edge index.
    t_perm = np.lexsort((pre, post)).astype(np.int64)
    t_indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(post, minlength=n), out=t_indptr[1:])
    tensors = {
        "indptr": indptr,
        "indices": post,
        "syn_count": syn,
        "weight": weight,
        "t_indptr": t_indptr,
        "t_indices": pre[t_perm],
        "t_perm": t_perm,
    }
    stats = {
        "pairs_before_threshold": n_before,
        "synapses_before_threshold": syn_before,
        "edges": len(post),
        "synapses": int(syn.sum(dtype=np.int64)),
        "min_synapses": min_syn,
    }
    return tensors, stats


def build_neuropil_fractions(
    inputs: BuildInputs, neurons: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Per (neuron, neuropil) input/output fractions and the primary neuropil (CONN-R-014)."""
    ids = neurons.select("source_id", "neuron_id").lazy()
    counts = (
        conform(inputs.neuropils, NEUROPIL_SCHEMA)
        .group_by("source_id", "neuropil")
        .agg(pl.col("pre").sum(), pl.col("post").sum())
        .join(ids, on="source_id", how="inner")
        .collect(engine="streaming")
    )
    fractions = counts.with_columns(
        (pl.col("pre") / pl.col("pre").sum().over("neuron_id")).cast(pl.Float32).alias("pre_frac"),
        (pl.col("post") / pl.col("post").sum().over("neuron_id"))
        .cast(pl.Float32)
        .alias("post_frac"),
    ).with_columns(pl.col("pre_frac").fill_nan(0.0), pl.col("post_frac").fill_nan(0.0))
    fractions = fractions.select(
        "neuron_id",
        "neuropil",
        pl.col("pre").alias("pre_count"),
        pl.col("post").alias("post_count"),
        "pre_frac",
        "post_frac",
    ).sort("neuron_id", "neuropil")
    primary = (
        fractions.with_columns((pl.col("pre_count") + pl.col("post_count")).alias("total"))
        .sort(["neuron_id", "total", "neuropil"], descending=[False, True, False])
        .group_by("neuron_id", maintain_order=True)
        .first()
        .select("neuron_id", pl.col("neuropil").alias("primary_neuropil"))
    )
    return fractions, primary


def neuron_level_flags(
    neurons: pl.DataFrame, fractions: pl.DataFrame, inputs: BuildInputs
) -> pl.DataFrame:
    """Flags for the 014 neuron-level sets: MB, CX (majority of synapses there) and I/O neurons."""

    def share(rois: tuple[str, ...], name: str) -> pl.DataFrame:
        return (
            fractions.with_columns((pl.col("pre_count") + pl.col("post_count")).alias("t"))
            .group_by("neuron_id")
            .agg(
                (
                    pl.col("t").filter(pl.col("neuropil").is_in(list(rois))).sum()
                    / pl.col("t").sum()
                ).alias(name)
            )
        )

    out = neurons.join(share(inputs.mb_neuropils, "mb_share"), on="neuron_id", how="left").join(
        share(inputs.cx_neuropils, "cx_share"), on="neuron_id", how="left"
    )
    return out.with_columns(
        (pl.col("mb_share").fill_null(0.0).fill_nan(0.0) > 0.5).alias("in_mb"),
        (pl.col("cx_share").fill_null(0.0).fill_nan(0.0) > 0.5).alias("in_cx"),
        (pl.col("is_sensory") | pl.col("is_descending") | pl.col("is_motor")).alias("is_io"),
    ).drop("mb_share", "cx_share")


# --- top level -----------------------------------------------------------------------------

OUTPUT_FILES = (
    "neurons.parquet",
    "neuropil_fractions.parquet",
    "edges.safetensors",
    "modulatory.parquet",
    "type_nodes.parquet",
    "type_edges.parquet",
    "type_membership.parquet",
    "iomap.json",
)


def build_template(
    inputs: BuildInputs,
    registry: Registry,
    template_id: str,
    out_root: Path,
    iomap: IoMap | None = None,
    expected: dict | None = None,
) -> dict:
    """Build one BrainTemplate into out_root/<template_id>/ and return the build report.

    `expected` = {"neurons": int, "synapses": int, "tolerance": float}; a mismatch fails the build
    (CONN-R-060). Published templates are immutable: an existing directory is never overwritten.
    """
    registry.require(REGISTRY_IDS)
    out = Path(out_root) / template_id
    if out.exists():
        raise TemplateError(
            f"{out} already exists; templates are immutable (CONN-R-054). Use a new template id."
        )
    t0 = time.perf_counter()
    with PeakRss() as rss:
        neurons = build_neuron_table(inputs, registry)
        tensors, edge_stats = build_edges(inputs, neurons, registry)
        fractions, primary = build_neuropil_fractions(inputs, neurons)
        neurons = neurons.join(primary, on="neuron_id", how="left").sort("neuron_id")
        neurons = neuron_level_flags(neurons, fractions, inputs)
        modulatory = _modulatory(neurons, inputs.peptides)
        neurons = neurons.with_columns(
            pl.col("neuron_id").is_in(modulatory["neuron_id"].implode()).alias("is_modulatory")
        )
        type_nodes, type_edges, membership = build_type_graph(neurons, tensors)
        resolved = (
            resolve_iomap(iomap, neurons) if iomap is not None else {"entries": [], "coverage": {}}
        )

        counts = {
            "neurons": neurons.height,
            **edge_stats,
            "graded": int((neurons["model"] == "graded").sum()),
            "type_nodes": type_nodes.height,
            "type_edges": type_edges.height,
        }
        for flag in (*FLAG_RULES, "is_modulatory", "in_mb", "in_cx"):
            counts[flag] = int(neurons[flag].sum())
        peptidergic = modulatory.filter(~pl.col("substance").is_in(list(AMINES)))
        counts["peptidergic_neurons"] = peptidergic["neuron_id"].n_unique()
        counts["peptides"] = peptidergic["substance"].n_unique()
        _validate_counts(counts, expected)

        tmp = out.with_name(out.name + ".building")
        if tmp.exists():
            for p in tmp.iterdir():
                p.unlink()
        tmp.mkdir(parents=True, exist_ok=True)
        write_parquet(neurons, tmp / "neurons.parquet")
        write_parquet(fractions, tmp / "neuropil_fractions.parquet")
        save_file(tensors, str(tmp / "edges.safetensors"), metadata={"format": "csr+transpose"})
        write_parquet(modulatory, tmp / "modulatory.parquet")
        write_parquet(type_nodes, tmp / "type_nodes.parquet")
        write_parquet(type_edges, tmp / "type_edges.parquet")
        write_parquet(membership, tmp / "type_membership.parquet")
        (tmp / "iomap.json").write_text(_json(resolved), encoding="utf-8", newline="\n")

        params = {pid: registry.get(pid) for pid in sorted(REGISTRY_IDS)}
        manifest = {
            "template_id": template_id,
            "sex": inputs.sex,
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "pipeline_version": pipeline_version(),
            "inputs": inputs.provenance,
            "parameters": params,
            "registry_hash": registry.content_hash(),
            "notes": inputs.notes,
            "counts": counts,
            "outputs": {
                name: {"sha256": sha256_file(tmp / name), "bytes": (tmp / name).stat().st_size}
                for name in OUTPUT_FILES
            },
        }
        (tmp / "manifest.json").write_text(_json(manifest), encoding="utf-8", newline="\n")

    # Publish only if the build stayed within the memory cap (CONN-R-053).
    max_rss = float(registry.get("conn.build.max_rss_gb"))
    over = rss.peak_gb > max_rss
    if over:
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
    else:
        tmp.rename(out)
    report = {
        "published": not over,
        "template_id": template_id,
        "path": str(out),
        "counts": counts,
        "coverage": resolved.get("coverage", {}),
        "peak_rss_gb": round(rss.peak_gb, 3),
        "max_rss_gb": max_rss,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    Path(str(out) + ".report.json").write_text(_json(report), encoding="utf-8", newline="\n")
    if over:
        raise TemplateError(
            f"peak RSS {rss.peak_gb:.2f} GiB exceeded conn.build.max_rss_gb={max_rss}"
        )
    return report


def _modulatory(neurons: pl.DataFrame, peptides: pl.LazyFrame | None) -> pl.DataFrame:
    """Aminergic neurons from transmitter predictions + cited peptidergic neurons (CONN-R-015).

    Every row carries `source_ref`: the transmitter prediction for amines, and the publication(s)
    behind each peptide assignment. Peptide rows for neurons outside the template are dropped.
    """
    amine = neurons.filter(pl.col("nt_pred").is_in(list(AMINES))).select(
        "neuron_id",
        pl.col("nt_pred").cast(pl.String).alias("substance"),
        pl.lit("transmitter prediction (nt_pred)").alias("source_ref"),
    )
    frames = [amine]
    if peptides is not None:
        pep = (
            peptides.select(
                pl.col("source_id").cast(pl.Int64),
                pl.col("substance").cast(pl.String),
                pl.col("source_ref").cast(pl.String),
            )
            .collect()
            .join(neurons.select("source_id", "neuron_id"), on="source_id", how="inner")
            .select("neuron_id", "substance", "source_ref")
        )
        frames.append(pep)
    return (
        pl.concat(frames)
        .unique(["neuron_id", "substance", "source_ref"])
        .sort("substance", "neuron_id", "source_ref")
    )


def _validate_counts(counts: dict, expected: dict | None) -> None:
    if not expected:
        return
    problems = []
    if "neurons" in expected and counts["neurons"] != expected["neurons"]:
        problems.append(f"neurons {counts['neurons']} != expected {expected['neurons']}")
    if "synapses" in expected:
        tol = expected.get("tolerance", 0.0)
        rel = abs(counts["synapses"] - expected["synapses"]) / expected["synapses"]
        if rel > tol:
            problems.append(
                f"synapses {counts['synapses']} differ from {expected['synapses']} "
                f"by {rel:.2%} > {tol:.2%}"
            )
    if problems:
        raise TemplateError("count validation failed (CONN-R-060): " + "; ".join(problems))


def _json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --- loading and verification (CONN-R-051) -------------------------------------------------


@dataclass(frozen=True)
class BrainTemplate:
    path: Path
    manifest: dict
    neurons: pl.DataFrame
    edges: dict[str, np.ndarray]

    @property
    def template_id(self) -> str:
        return self.manifest["template_id"]

    @property
    def n_neurons(self) -> int:
        return self.neurons.height


def verify_template(path: Path) -> dict:
    """Re-hash every output file against the manifest; raise on any mismatch."""
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        raise TemplateIntegrityError(f"{path}: no manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = []
    for name, meta in sorted(manifest["outputs"].items()):
        f = path / name
        if not f.exists():
            problems.append(f"missing {name}")
        elif sha256_file(f) != meta["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    if problems:
        raise TemplateIntegrityError(f"{path}: refusing to load: " + "; ".join(problems))
    return manifest


def load_template(path: Path) -> BrainTemplate:
    """Load a verified template. Any tampering raises TemplateIntegrityError (CONN-AC-03)."""
    manifest = verify_template(path)
    return BrainTemplate(
        path=Path(path),
        manifest=manifest,
        neurons=pl.read_parquet(Path(path) / "neurons.parquet"),
        edges=load_file(str(Path(path) / "edges.safetensors")),
    )
