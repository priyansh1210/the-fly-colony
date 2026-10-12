"""Device layer and hardware probe (spec 014 §5, HW-R-001/002/005/010).

This package is the ONLY place allowed to name a device (`"cuda"`, `"cpu"`) or construct a
`torch.device`. Everything else asks `select_device()`. A lint test enforces it (HW-R-002).
"""

from flycolony.hardware.probe import (
    GpuInfo,
    HardwareError,
    HardwareInfo,
    classify_tier,
    probe,
    select_device,
)

__all__ = ["GpuInfo", "HardwareError", "HardwareInfo", "classify_tier", "probe", "select_device"]
