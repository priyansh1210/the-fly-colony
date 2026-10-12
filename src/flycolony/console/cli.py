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
app.add_typer(data_app, name="data")
app.add_typer(template_app, name="template")
app.add_typer(registry_app, name="registry")
app.add_typer(hardware_app, name="hardware")


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
    typer.echo(
        "Capacity limits come from `colony hardware benchmark` (Phase 1, spec 014 HW-R-011)."
    )


if __name__ == "__main__":
    app()
