"""Per-fly counter-based random numbers (BRAIN-R-013, -054, -055).

Each random number is a pure function of (fly key, stream, step, neuron): a 32-bit integer hash,
evaluated with int64 tensor ops so it gives the same bits on every device. Nothing depends on
batch size, batch order or the other flies, and there is no generator state to checkpoint beyond
the fly key and the step counter.

The hash is a 32-bit integer finaliser (two multiply-xorshift rounds) whose multipliers are below
2**31, so every product fits in int64 without overflow.
"""

from __future__ import annotations

import torch

_MASK32 = 0xFFFFFFFF  # registry-ok: 32-bit mask
_M1 = 0x21F0AAAD  # registry-ok: hash constant (hash-prospector 2-round finaliser)
_M2 = 0x735A2D97  # registry-ok: hash constant
_S1, _S2, _S3 = 16, 15, 15  # registry-ok: hash shift amounts
_GOLDEN = 0x9E3779B9  # registry-ok: 2**32 / golden ratio, decorrelates consecutive counters
_U24 = float(1 << 24)  # registry-ok: 24 mantissa bits -> uniform in (0, 1)
_HIGH = 32  # registry-ok: split a 64-bit step counter into two 32-bit words

# Stream ids: one independent sequence per use.
STREAM_DRIVE = 1
STREAM_NOISE = 2
STREAM_NOISE_INIT = 3  # registry-ok: stream id
STREAM_SENSE = 4  # registry-ok: stream id


def hash32(x: torch.Tensor) -> torch.Tensor:
    """Hash int64 values in [0, 2**32) to int64 values in [0, 2**32)."""
    x = x & _MASK32
    x = x ^ (x >> _S1)
    x = (x * _M1) & _MASK32
    x = x ^ (x >> _S2)
    x = (x * _M2) & _MASK32
    return x ^ (x >> _S3)


def hash_int(x: int) -> int:
    """Python-int version of `hash32`, for per-fly and per-step keys."""
    x &= _MASK32
    x ^= x >> _S1
    x = (x * _M1) & _MASK32
    x ^= x >> _S2
    x = (x * _M2) & _MASK32
    return x ^ (x >> _S3)


def fly_key(seed: int) -> int:
    """32-bit key for a fly from its (arbitrary-size, non-negative) seed."""
    key = 0
    while True:
        key = hash_int(key ^ hash_int((seed & _MASK32) + _GOLDEN))
        seed >>= _HIGH
        if seed == 0:
            return key


def step_keys(keys: torch.Tensor, stream: int, step: int | torch.Tensor) -> torch.Tensor:
    """Key per (fly, stream, step). `keys` and `step` broadcast against each other."""
    step = torch.as_tensor(step, dtype=torch.int64, device=keys.device)
    k = hash32(keys ^ hash_int(stream * _GOLDEN))
    k = hash32(k ^ (step & _MASK32))
    return hash32(k + hash32((step >> _HIGH) + _GOLDEN))


def neuron_salt(n: int, device: torch.device) -> torch.Tensor:
    """Per-neuron salt: int64 [n]."""
    return hash32(torch.arange(n, dtype=torch.int64, device=device) * _GOLDEN + 1)


def uniform(step_key: torch.Tensor, salt: torch.Tensor) -> torch.Tensor:
    """Uniform float64 in (0, 1) for paired (per-event fly step key, per-event neuron salt)."""
    x = hash32(hash32(step_key ^ salt) + _GOLDEN)
    return ((x >> (_HIGH - 24)).to(torch.float64) + 0.5) / _U24  # registry-ok: 24-bit fraction
