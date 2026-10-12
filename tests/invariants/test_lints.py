"""T-CONN-I-003 (no magic numbers), T-HW-U-005 (device lint) and the import-linter contracts."""

from __future__ import annotations

import textwrap

import pytest
from tools import lint


def test_model_packages_have_no_magic_numbers():
    assert lint.magic_numbers(lint.model_files()) == []


def test_no_hard_coded_devices_outside_hardware():
    assert lint.devices(lint.non_hardware_files()) == []


@pytest.fixture
def probe_file():
    p = lint.SRC / "_lint_probe_tmp.py"
    yield p
    p.unlink(missing_ok=True)


def test_magic_number_lint_catches_literals(probe_file):
    probe_file.write_text(
        textwrap.dedent("""\
        def step(v, dt: float = 0.25):
            tau = 20.0
            ok = 3.0  # registry-ok: test fixture
            x = v[3]
            return v * 0.5 - 1 + tau * dt - 45
        """),
        encoding="utf-8",
    )
    hits = lint.magic_numbers([probe_file])
    values = sorted(h.split("literal ")[1].split(" ")[0] for h in hits)
    assert values == ["0.25", "20.0", "45"]


def test_device_lint_catches_devices(probe_file):
    probe_file.write_text(
        textwrap.dedent("""\
        import torch
        a = torch.zeros(3, device="cuda")
        b = torch.device("cpu")
        c = "cuda:1"  # device-ok: test fixture
        d = "a cuda string"
        """),
        encoding="utf-8",
    )
    hits = lint.devices([probe_file])
    assert len(hits) == 3  # "cuda", torch.device(...), "cpu"


def test_import_contracts():  # CONST-2 (engine never imports the Watcher), CONST-1.4
    assert lint.import_contracts() == []


def test_import_contract_checker_catches_violations():
    p = lint.SRC / "brain" / "_lint_probe_tmp.py"
    p.write_text(
        "from flycolony.watcher import x\nfrom ..console import cli\nimport tests.conftest\n",
        encoding="utf-8",
    )
    try:
        hits = lint.import_contracts()
    finally:
        p.unlink()
    assert len([h for h in hits if "_lint_probe_tmp" in h]) >= 3
