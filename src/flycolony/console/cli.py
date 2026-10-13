"""`colony` command-line interface (spec 013; Phase-0 commands from spec 001 design §7)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from flycolony.config import load_all, project_root

app = typer.Typer(help="The Fly Colony control console.", no_args_is_help=True)
data_app = typer.Typer(help="Source datasets and licenses.", no_args_is_help=True)
template_app = typer.Typer(help="BrainTemplates (connectome packages).", no_args_is_help=True)
registry_app = typer.Typer(help="Parameter Registry.", no_args_is_help=True)
hardware_app = typer.Typer(help="Hardware detection and limits.", no_args_is_help=True)
brain_app = typer.Typer(help="Brain engine validation (spec 002).", no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(template_app, name="template")
app.add_typer(registry_app, name="registry")
app.add_typer(hardware_app, name="hardware")
app.add_typer(brain_app, name="brain")


def _paths() -> dict[str, Path]:
    cfg = load_all()["colony.yaml"]
    root = project_root()
    return {name: (root / value) for name, value in cfg.paths.model_dump().items()}


# --- data ----------------------------------------------------------------------------------


@data_app.command("list")
def data_list() -> None:
    """List datasets, their licenses and whether they have been fetched."""
    from flycolony.connectome.datasets import load_catalog, raw_dir

    for ds_id, ds in sorted(load_catalog().datasets.items()):
        lic = ds.license.name + f" ({ds.license.status})" if ds.license else "MISSING"
        fetched = (raw_dir(ds_id, _paths()["data_raw"]) / "_source.json").exists()
        typer.echo(f"{ds_id:22} {'fetched' if fetched else 'not fetched':12} {lic}")


@data_app.command("fetch")
def data_fetch(
    dataset_ids: list[str] = typer.Argument(None, help="Dataset ids (default: all)."),
    with_optional: bool = typer.Option(
        False, help="Also fetch optional files (e.g. 9.5 GB synapses)."
    ),
) -> None:
    """Download datasets into data/raw/<id>/ and verify their checksums."""
    from flycolony.connectome.datasets import fetch, load_catalog

    catalog = load_catalog()
    for ds_id in dataset_ids or sorted(catalog.datasets):
        typer.echo(ds_id)
        fetch(catalog, ds_id, _paths()["data_raw"], include_optional=with_optional, log=typer.echo)


@data_app.command("licenses")
def data_licenses() -> None:
    """Regenerate data/LICENSES.md from config/datasets.yaml."""
    from flycolony.connectome.datasets import load_catalog, render_licenses_md

    path = project_root() / "data" / "LICENSES.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_licenses_md(load_catalog()), encoding="utf-8", newline="\n")
    typer.echo(f"wrote {path}")


# --- templates -----------------------------------------------------------------------------


@template_app.command("build")
def template_build(
    sex: str = typer.Argument(..., help="female | male"),
    template_id: str | None = typer.Option(None, "--id", help="Default: from colony.yaml."),
) -> None:
    """Build one BrainTemplate from the fetched datasets."""
    from flycolony.connectome.build import build_for_sex

    report = build_for_sex(sex, template_id=template_id, log=typer.echo)
    typer.echo(json.dumps(report, indent=2))


@template_app.command("match")
def template_match(
    female_id: str | None = typer.Option(None, "--female"),
    male_id: str | None = typer.Option(None, "--male"),
) -> None:
    """Cross-dataset type matching, normalization factor and discrepancy report."""
    from flycolony.connectome.matching import build_matching
    from flycolony.connectome.template import load_template
    from flycolony.registry import Registry

    cfg = load_all()["colony.yaml"]
    root = _paths()["templates"]
    female = load_template(root / (female_id or cfg.templates.female))
    male = load_template(root / (male_id or cfg.templates.male))
    summary = build_matching(female, male, Registry.load(), root)
    summary.pop("female_only_examples", None)
    typer.echo(json.dumps(summary, indent=2))


@template_app.command("verify")
def template_verify(path: Path) -> None:
    """Verify a template's checksums against its manifest."""
    from flycolony.connectome.template import verify_template

    manifest = verify_template(path)
    typer.echo(
        f"ok: {manifest['template_id']} ({manifest['counts']['neurons']} neurons, "
        f"{manifest['counts']['edges']} edges)"
    )


# --- registry ------------------------------------------------------------------------------


@registry_app.command("report")
def registry_report() -> None:
    """Share of ASSUMPTION entries per owner spec (CONST-6.3)."""
    from flycolony.registry import Registry

    reg = Registry.load()
    typer.echo(f"registry {reg.content_hash()[:12]}  ({len(reg)} entries)")
    typer.echo(f"{'spec':6} {'entries':>8} {'assumptions':>12} {'share':>7}")
    for row in reg.assumption_report():
        typer.echo(
            f"{row['owner_spec']:6} {row['entries']:>8} {row['assumptions']:>12} "
            f"{row['share']:>7.0%}"
        )


# --- hardware ------------------------------------------------------------------------------


@hardware_app.command("probe")
def hardware_probe() -> None:
    """Detect GPUs, RAM, CPU and disk; print the device and default tier."""
    from flycolony.hardware.probe import probe, resolve

    info = probe({k: v for k, v in _paths().items() if k in ("data_raw", "flies")})
    device, tier = resolve(load_all()["hardware.yaml"], info)
    typer.echo(info.model_dump_json(indent=2))
    typer.echo(f"selected device: {device}   default tier: {tier}")
    typer.echo("Capacity limits come from `colony hardware benchmark` (spec 014 HW-R-011).")


def _device(spec: str | None):
    from flycolony.hardware.probe import resolve, select_device

    if spec:
        return select_device(spec)
    return resolve(load_all()["hardware.yaml"])[0]


def _template(sex: str):
    from flycolony.brain.build import template_path
    from flycolony.connectome.template import load_template

    return load_template(template_path(load_all()["colony.yaml"], sex))


@hardware_app.command("benchmark")
def hardware_benchmark(
    device: str = typer.Option(None, help="auto | cpu | cuda | cuda:N (default: hardware.yaml)"),
    sex: list[str] = typer.Option(["female", "male"], help="Templates to benchmark"),
    batch: list[int] = typer.Option(None, help="Batch sizes (default: 1, 2, 4, ... until a limit)"),
) -> None:
    """Measure VRAM and step cost per fly; cache the capacity profile; print the limits."""
    from flycolony.brain.build import setup_brain
    from flycolony.hardware.capacity import run_benchmark
    from flycolony.hardware.probe import probe
    from flycolony.registry import Registry

    reg = Registry.load()
    cfg = load_all()["colony.yaml"]
    dev = _device(device)
    setups = []
    for s in sex:
        setup = setup_brain(_template(s), dev, cfg, reg)
        typer.echo(f"{setup.template.template_id}: dt={setup.dt} ms ({setup.choice.note})")
        setups.append(setup)
    profile = run_benchmark(setups, probe(), reg, batch_sizes=batch or None)
    for t in profile["templates"]:
        lim = t["limits"]
        typer.echo(f"\n{t['template_id']} FULL  dt={t['dt_ms']} ms")
        for r in t["rows"]:
            typer.echo(
                f"  {r['flies']:4d} flies  {r['ms_per_step']:8.3f} ms/step  RTF/fly {r['rtf_per_fly']:6.3f}"
                f"  fly-s/s {r['fly_seconds_per_second']:7.3f}  mean {r['mean_rate_hz']:5.2f} Hz"
                f"  peak {r['peak_bytes'] / 2**20:8.1f} MiB"
            )
        typer.echo(
            f"  this device: up to {lim['soft_limit']} FULL flies in real time, "
            f"{lim['hard_limit']} max (VRAM). {lim['note']}"
        )
    typer.echo(f"\nprofile {profile['key_hash']} cached under .colony/capacity/")


# --- brain ---------------------------------------------------------------------------------


@brain_app.command("validate")
def brain_validate(
    device: str = typer.Option(None),
    trials: int = typer.Option(None, help="Override the assays' trial count"),
) -> None:
    """Engine vs the Brian2 reference on the validation assays (BRAIN-R-080/081)."""
    from flycolony.brain.assays import load_assays
    from flycolony.brain.validation import publish, validate_reference
    from flycolony.registry import Registry

    tpl = _template("female")
    rec = validate_reference(tpl, _device(device), Registry.load(), load_assays(), trials=trials)
    for name, a in rec["assays"].items():
        ag = a.get("agreement", {})
        typer.echo(
            f"{name:14} r={ag.get('pearson', float('nan')):.4f} top-k={ag.get('top_k_overlap', float('nan')):.2f}"
            f"  {a.get('readout_engine_hz', '')}  {'PASS' if a.get('pass') else 'FAIL'}"
        )
    typer.echo(f"report: {publish(tpl, 'reference', rec)}")
    raise typer.Exit(0 if rec["passed"] else 1)


@brain_app.command("gate")
def brain_gate(
    device: str = typer.Option(None),
    sex: str = typer.Option("female"),
    dt: list[float] = typer.Option(None, help="Candidate dt in ms (default: brain.dt.candidates)"),
    trials: int = typer.Option(None),
) -> None:
    """Timestep gate for the configured production model (BRAIN-R-021)."""
    from flycolony.brain.assays import load_assays
    from flycolony.brain.validation import male_mapping, publish, timestep_gate
    from flycolony.registry import Registry

    reg = Registry.load()
    cfg = load_all()["colony.yaml"]
    bc = cfg.brain
    tpl = _template(sex)
    assays = load_assays()
    mapping = None
    if sex == "male":  # the paper's lists are FlyWire ids: map them as the male assays do
        female = _template("female")
        match = (
            project_root() / cfg.paths.templates / f"match__{female.template_id}__{tpl.template_id}"
        )
        mapping = male_mapping(female, tpl, match, reg, assays)
    recs = timestep_gate(
        tpl, _device(device), reg, assays,
        candidates=dt or list(reg.get("brain.dt.candidates")),
        graded=bc.graded, weights=bc.weights, trials=trials, mapping=mapping,
    )  # fmt: skip
    for rec in recs:
        for name, a in rec["assays"].items():
            ag = a["agreement"]
            typer.echo(
                f"dt={rec['dt_ms']} {name:14} r={ag['pearson']:.4f} top-k={ag['top_k_overlap']:.2f} {'PASS' if a['pass'] else 'FAIL'}"
            )
        typer.echo(
            f"dt={rec['dt_ms']}: {'PASSED' if rec['passed'] else 'FAILED'} -> {publish(tpl, rec['name'], rec)}"
        )


@brain_app.command("male")
def brain_male(device: str = typer.Option(None), trials: int = typer.Option(None)) -> None:
    """Validation assays on the male template and cross-sex comparability (BRAIN-R-082)."""
    from flycolony.brain.assays import load_assays
    from flycolony.brain.validation import male_assays, publish
    from flycolony.registry import Registry

    cfg = load_all()["colony.yaml"]
    female, male = _template("female"), _template("male")
    match = (
        project_root() / cfg.paths.templates / f"match__{female.template_id}__{male.template_id}"
    )
    rec = male_assays(
        female, male, match, _device(device), Registry.load(), load_assays(), trials=trials
    )
    for name, a in rec["assays"].items():
        typer.echo(
            f"{name:14} female {a['readout_female_hz']}  male {a['readout_male_hz']}  "
            f"type-side r={a['type_side_pearson']:.3f}{' (mirrored)' if a['mirrored'] else ''}  {'PASS' if a['pass'] else 'FAIL'}"
        )
    typer.echo(f"report: {publish(male, 'male-assays', rec)}")


if __name__ == "__main__":
    app()
