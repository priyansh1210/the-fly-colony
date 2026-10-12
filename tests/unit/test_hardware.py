"""T-HW-U-001 (probe, tiers, device selection) and the device part of T-HW-U-005."""

from __future__ import annotations

import pytest
import torch

from flycolony.config.schemas import HardwareConfig, TierThresholds
from flycolony.hardware import HardwareError, HardwareInfo, classify_tier, probe, select_device
from flycolony.hardware.probe import GpuInfo, resolve


def fake_info(*vram_gb: float) -> HardwareInfo:
    return HardwareInfo(
        os="test",
        python="3.12",
        torch="x",
        cuda_runtime="12.8" if vram_gb else None,
        driver=None,
        gpus=[
            GpuInfo(
                index=i,
                name=f"GPU{i}",
                vram_total_gb=v,
                vram_free_gb=v,
                compute_capability="8.9",
                multiprocessors=1,
            )
            for i, v in enumerate(vram_gb)
        ],
        ram_total_gb=8,
        cpu_name="cpu",
        cpu_cores_physical=4,
        cpu_cores_logical=8,
        disk_free_gb={},
    )


@pytest.mark.parametrize(
    "vram,tier",
    [
        (4.0, "low"),
        (5.99, "low"),
        (8.0, "mid"),
        (12.0, "high"),
        (20.0, "high"),
        (24.0, "high"),
        (32.0, "ultra"),
        (80.0, "ultra"),
    ],
)
def test_tiers_by_vram(vram, tier):
    assert classify_tier(fake_info(vram), torch.device("cuda", 0), TierThresholds()) == tier


def test_cpu_tier_without_gpu():
    assert classify_tier(fake_info(), torch.device("cpu"), TierThresholds()) == "cpu"


def test_multi_gpu_uses_selected_device():
    info = fake_info(4.0, 24.0)
    assert classify_tier(info, torch.device("cuda", 1), TierThresholds()) == "high"


def test_select_device():
    assert select_device("cpu").type == "cpu"
    assert select_device("auto").type == ("cuda" if torch.cuda.is_available() else "cpu")
    with pytest.raises(HardwareError, match="unknown device"):
        select_device("tpu")
    with pytest.raises(HardwareError):
        select_device("cuda:99")


def test_probe_records_manifest_fields(tmp_path):  # HW-R-005, HW-R-010
    info = probe({"tmp": tmp_path / "does" / "not" / "exist"})
    assert info.torch == torch.__version__
    assert info.ram_total_gb > 0 and info.disk_free_gb["tmp"] > 0
    assert len(info.gpus) == (torch.cuda.device_count() if torch.cuda.is_available() else 0)
    HardwareInfo.model_validate_json(info.model_dump_json())  # serializable for manifests


def test_forced_cpu_and_explicit_tier():
    device, tier = resolve(HardwareConfig(device="cpu"), fake_info(8.0))
    assert device.type == "cpu" and tier == "cpu"
    _, tier = resolve(HardwareConfig(device="cpu", tier="low"), fake_info(8.0))
    assert tier == "low"
