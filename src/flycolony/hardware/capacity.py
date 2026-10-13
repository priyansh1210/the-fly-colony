"""Capacity benchmark and per-device fly limits (spec 014 §5: HW-R-011, -012; BRAIN-R-083).

The benchmark runs spontaneous activity (production model: background noise, neuromodulation,
plastic sets) for growing batch sizes and fits

    wall time per brain step  = a + b * flies           (seconds)
    device memory             = fixed + per_fly * flies (bytes)

From the fit:
- hard limit = flies that fit in VRAM minus the reserve (`hw.vram_reserve_frac`);
- soft limit = flies that keep RTF >= `hw.rtf_target`, i.e. a + b*B <= dt / target.

Only FULL fidelity exists in Phase 1; HYBRID and COARSE are added to the profile when 014
implements them. World costs (physics, vision) are zero until 003/004 exist and are reported so.
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import torch

from flycolony.brain.build import BrainSetup
from flycolony.brain.engine import FlyBrainSpec
from flycolony.config import project_root
from flycolony.hardware.probe import HardwareInfo
from flycolony.registry import Registry

KERNEL_PATH = "pure-pytorch"


def _sync(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _mem(device: torch.device) -> int:
    return torch.cuda.memory_allocated(device) if device.type == "cuda" else 0


def device_key(info: HardwareInfo, device: torch.device, templates: list[str]) -> dict:
    """Everything whose change forces a new benchmark (HW-R-011)."""
    if device.type == "cuda":
        gpu = next(g for g in info.gpus if g.index == (device.index or 0))
        name, vram = gpu.name, gpu.vram_total_gb
    else:
        name, vram = info.cpu_name, info.ram_total_gb
    return {
        "device_type": device.type,
        "device_name": name,
        "memory_total_gb": vram,
        "driver": info.driver,
        "cuda_runtime": info.cuda_runtime,
        "torch": info.torch,
        "kernel_path": KERNEL_PATH,
        "templates": sorted(templates),
        "os": platform.system(),
    }


def key_hash(key: dict) -> str:
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def profile_path(key: dict) -> Path:
    return project_root() / ".colony" / "capacity" / f"{key_hash(key)}.json"


def benchmark_template(
    setup: BrainSetup, reg: Registry, *, batch_sizes: list[int] | None = None
) -> dict:
    """Measure step time and memory per batch size for one template at FULL fidelity."""
    dev = setup.topo.device
    warm = int(reg.get("hw.bench.warmup_steps"))
    timed = int(reg.get("hw.bench.timed_steps"))
    max_wall = float(reg.get("hw.bench.max_wall_s"))
    sizes = batch_sizes or [1, 2, 4, 8, 16, 32, 64, 128, 256]
    rows = []
    for b in sizes:
        if dev.type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(dev)
        budget = _budget(dev, reg)
        if budget and rows and b * rows[-1]["reserved_bytes"] / rows[-1]["flies"] > budget:
            break  # would oversubscribe VRAM (WDDM then pages to system RAM: timings meaningless)
        base = _mem(dev)
        base_reserved = torch.cuda.memory_reserved(dev) if dev.type == "cuda" else 0
        batch = setup.new_batch()
        for i in range(b):
            batch.add(FlyBrainSpec(f"bench{i}", 1000 + i))
        batch.run(warm)
        _sync(dev)
        spikes = [0]

        def count(_b, _t, s, spikes=spikes):
            spikes[0] += int(s.numel())

        batch.taps.append(count)
        t0 = time.perf_counter()
        batch.run(timed)
        _sync(dev)
        wall = time.perf_counter() - t0
        peak = torch.cuda.max_memory_allocated(dev) - base if dev.type == "cuda" else 0
        # The caching allocator holds more than it hands out: budget on what it reserved.
        reserved = torch.cuda.max_memory_reserved(dev) - base_reserved if dev.type == "cuda" else 0
        step_s = wall / timed
        rows.append(
            {
                "flies": b,
                "ms_per_step": step_s * 1e3,  # registry-ok: s -> ms
                "rtf_per_fly": (setup.dt / 1e3) / step_s,  # registry-ok: ms -> s
                "fly_seconds_per_second": b * (setup.dt / 1e3) / step_s,  # registry-ok: ms -> s
                "mean_rate_hz": spikes[0]
                / (b * setup.topo.n * timed * setup.dt / 1e3),  # registry-ok: ms -> s
                "peak_bytes": int(peak),
                "reserved_bytes": int(reserved),
                "over_budget": bool(budget and reserved > budget),
            }
        )
        del batch
        if wall > max_wall or (budget and reserved > budget):
            break
    return _fit(rows, setup)


def _budget(dev: torch.device, reg: Registry) -> int:
    """VRAM a batch may still use: free memory now (other topologies and processes already
    subtracted) minus the reserve fraction of the total."""
    if dev.type != "cuda":
        return 0
    free, total = torch.cuda.mem_get_info(dev)
    return max(1, int(free - total * float(reg.get("hw.vram_reserve_frac"))))


def _fit(rows: list[dict], setup: BrainSetup) -> dict:
    """Linear fits over the rows that fit in memory (an over-budget row is reported, not fitted)."""
    ok = [r for r in rows if not r.get("over_budget")] or rows[:1]
    flies = np.array([r["flies"] for r in ok], dtype=np.float64)
    step = np.array([r["ms_per_step"] for r in ok]) / 1e3  # registry-ok: ms -> s
    # VRAM limits use what the caching allocator reserves, which exceeds what it hands out.
    mem = np.array([r.get("reserved_bytes", r["peak_bytes"]) for r in ok], dtype=np.float64)
    if len(ok) >= 2:
        b, a = np.polyfit(flies, step, 1)
        per_fly_mem, fixed_mem = np.polyfit(flies, mem, 1) if mem.any() else (0.0, 0.0)
    else:
        a, b, per_fly_mem, fixed_mem = float(step[0]), 0.0, float(mem[0]), 0.0
    return {
        "template_id": setup.template.template_id,
        "fidelity": "FULL",
        "dt_ms": setup.dt,
        "dt_note": setup.choice.note,
        "graded": setup.topo.graded_edges is not None,
        "topology_bytes": setup.topo.nbytes(),
        "rows": rows,
        "fit": {
            "step_fixed_s": float(max(a, 0.0)),  # a negative intercept is a bad fit, not free time
            "step_per_fly_s": float(max(b, 0.0)),
            "mem_fixed_bytes": float(fixed_mem) + setup.topo.nbytes(),
            "mem_per_fly_bytes": float(max(per_fly_mem, 0.0)),
        },
    }


def limits(template_profile: dict, reg: Registry, vram_total_bytes: int | None) -> dict:
    """Hard (VRAM) and soft (RTF) limits for one template at FULL fidelity (HW-R-012)."""
    f = template_profile["fit"]
    dt_s = template_profile["dt_ms"] / 1e3  # registry-ok: ms -> s
    target = float(reg.get("hw.rtf_target"))
    if vram_total_bytes:
        budget = vram_total_bytes * (1 - float(reg.get("hw.vram_reserve_frac")))
        per = max(f["mem_per_fly_bytes"], 1.0)
        hard = int(max(0.0, (budget - f["mem_fixed_bytes"]) // per))
    else:
        hard = None  # CPU: bounded by RAM, reported separately
    allowed = dt_s / target - f["step_fixed_s"]
    if allowed <= 0:
        soft = 0
    elif f["step_per_fly_s"] <= 0:
        soft = hard
    else:
        soft = int(allowed / f["step_per_fly_s"] + 1e-9)  # tolerate float rounding at exact fits
    if hard is not None and soft is not None:
        soft = min(soft, hard)
    best_single = dt_s / (f["step_fixed_s"] + f["step_per_fly_s"])
    return {
        "hard_limit": hard,
        "soft_limit": soft,
        "rtf_target": target,
        "rtf_one_fly": best_single,
        "note": (
            "Below the RTF target even with one fly: every fly day is stretched (PERF-R-006)."
            if soft == 0
            else ""
        ),
    }


def run_benchmark(
    setups: list[BrainSetup], info: HardwareInfo, reg: Registry, *, batch_sizes=None
) -> dict:
    dev = setups[0].topo.device
    key = device_key(info, dev, [s.template.template_id for s in setups])
    vram = torch.cuda.get_device_properties(dev).total_memory if dev.type == "cuda" else None
    templates = []
    for s in setups:
        prof = benchmark_template(s, reg, batch_sizes=batch_sizes)
        prof["limits"] = limits(prof, reg, vram)
        templates.append(prof)
    profile = {
        "kind": "capacity-profile",
        "key": key,
        "key_hash": key_hash(key),
        "world_fixed_cost": "none yet (physics, vision and senses arrive in Phase 2)",
        "fidelities_available": ["FULL"],
        "templates": templates,
        "registry": {
            "hw.vram_reserve_frac": float(reg.get("hw.vram_reserve_frac")),
            "hw.rtf_target": float(reg.get("hw.rtf_target")),
        },
    }
    path = profile_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8", newline="\n")
    return profile


def load_profile(info: HardwareInfo, device: torch.device, templates: list[str]) -> dict | None:
    """The cached profile for this exact device/software/template combination, if any."""
    path = profile_path(device_key(info, device, templates))
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
