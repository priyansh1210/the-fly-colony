"""Hardware probe, device selection and tier classification."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import psutil
import torch
from pydantic import BaseModel, ConfigDict

from flycolony.config.schemas import HardwareConfig, TierThresholds

Tier = Literal["cpu", "low", "mid", "high", "ultra"]
GIB = 1024**3


class HardwareError(RuntimeError):
    """The requested device is not available."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GpuInfo(_Frozen):
    index: int
    name: str
    vram_total_gb: float
    vram_free_gb: float | None
    compute_capability: str
    multiprocessors: int


class HardwareInfo(_Frozen):
    """Recorded in every run manifest and checkpoint (HW-R-005)."""

    os: str
    python: str
    torch: str
    cuda_runtime: str | None
    driver: str | None
    gpus: list[GpuInfo]
    ram_total_gb: float
    cpu_name: str
    cpu_cores_physical: int | None
    cpu_cores_logical: int | None
    disk_free_gb: dict[str, float]


def _driver_version() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = (
            subprocess.run(
                [exe, "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )
        return out[0].strip() if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def _gpus() -> list[GpuInfo]:
    if not torch.cuda.is_available():
        return []
    out = []
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        try:
            free, _total = torch.cuda.mem_get_info(i)
            free_gb: float | None = round(free / GIB, 2)
        except RuntimeError:
            free_gb = None
        out.append(
            GpuInfo(
                index=i,
                name=p.name,
                vram_total_gb=round(p.total_memory / GIB, 2),
                vram_free_gb=free_gb,
                compute_capability=f"{p.major}.{p.minor}",
                multiprocessors=p.multi_processor_count,
            )
        )
    return out


def probe(paths: dict[str, Path] | None = None) -> HardwareInfo:
    """Detect GPUs, RAM, CPU and free disk at the given paths (HW-R-010)."""
    disk = {}
    for label, path in (paths or {}).items():
        p = Path(path)
        while not p.exists() and p != p.parent:
            p = p.parent
        disk[label] = round(shutil.disk_usage(p).free / GIB, 1)
    return HardwareInfo(
        os=f"{platform.system()} {platform.release()} ({platform.version()})",
        python=platform.python_version(),
        torch=torch.__version__,
        cuda_runtime=torch.version.cuda,
        driver=_driver_version(),
        gpus=_gpus(),
        ram_total_gb=round(psutil.virtual_memory().total / GIB, 1),
        cpu_name=platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        cpu_cores_physical=psutil.cpu_count(logical=False),
        cpu_cores_logical=psutil.cpu_count(logical=True),
        disk_free_gb=disk,
    )


def select_device(spec: str = "auto") -> torch.device:
    """The single entry point for device placement (HW-R-002).

    `auto` picks the first CUDA device if one is usable, else the CPU.
    """
    spec = spec.strip().lower()
    if spec == "auto":
        return torch.device("cuda", 0) if torch.cuda.is_available() else torch.device("cpu")
    if spec == "cpu":
        return torch.device("cpu")
    if spec.startswith("cuda"):
        if not torch.cuda.is_available():
            raise HardwareError(f"device {spec!r} requested but no CUDA device is available")
        index = int(spec.split(":", 1)[1]) if ":" in spec else 0
        if index >= torch.cuda.device_count():
            raise HardwareError(
                f"device {spec!r} requested but only {torch.cuda.device_count()} CUDA device(s) exist"
            )
        return torch.device("cuda", index)
    raise HardwareError(f"unknown device {spec!r}; use auto, cpu, cuda or cuda:N")


def classify_tier(info: HardwareInfo, device: torch.device, thresholds: TierThresholds) -> Tier:
    """Default tier from the VRAM of the selected device (spec 014 §5.4)."""
    if device.type != "cuda":
        return "cpu"
    gpu = next(g for g in info.gpus if g.index == (device.index or 0))
    vram = gpu.vram_total_gb
    if vram < thresholds.low_below_gb:
        return "low"
    if vram < thresholds.mid_below_gb:
        return "mid"
    if vram <= thresholds.high_up_to_gb:
        return "high"
    return "ultra"


def resolve(config: HardwareConfig, info: HardwareInfo | None = None) -> tuple[torch.device, Tier]:
    """Device and tier for a hardware config (`tier: auto` -> classified from VRAM)."""
    info = info or probe()
    device = select_device(config.device)
    tier = classify_tier(info, device, config.tiers) if config.tier == "auto" else config.tier
    return device, tier
