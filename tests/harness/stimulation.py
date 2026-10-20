"""Open-loop DN stimulation for tests only (spec 005 §5; MOTOR-R-011, -012, CONST-1.4).

`stimulable(batch)` turns a live `BrainBatch` into a `StimulatedBrain`, which can hold chosen
non-sensory neurons (DNs, motor neurons) at a constant depolarisation. The production class has
no such method, and an import contract forbids production code from importing this package, so
no production path can stimulate a DN.

The input enters like the photoreceptor input (002): a per-step synaptic increment
x = V·(1 − e_s)(1 − e_m) / c_m holds a non-spiking unit at +V mV in steady state. With V above
the neuron's threshold, the neuron fires regularly; refractory neurons ignore the input.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import torch

from flycolony.brain.engine import BrainBatch


class StimulatedBrain(BrainBatch):
    """A BrainBatch with a test-only constant depolarising input on chosen neurons."""

    _stim: dict[str, tuple[torch.Tensor, torch.Tensor]]

    def stimulate(self, fly_id: str, neuron_ids: Sequence[int] | np.ndarray, mv) -> None:
        """Hold `neuron_ids` of one fly at +mv (steady state, relative to rest). Replaces the
        fly's previous stimulation; an empty id list clears it."""
        ids = torch.as_tensor(np.asarray(neuron_ids, dtype=np.int64), device=self.device)
        mv = torch.as_tensor(mv, dtype=torch.float32, device=self.device).expand(ids.shape)
        if ids.numel() and bool(self.topo.sensory[ids].any()):
            raise ValueError("stimulate non-sensory neurons only; sensory input comes from 004")
        x = mv * (1 - self.k.e_s) * (1 - self.e_m[ids]) / self.c_m[ids]
        self._stim.pop(fly_id, None)
        if ids.numel():
            self._stim[fly_id] = (ids, x)

    def threshold_mv(self, fly_id: str, neuron_ids) -> torch.Tensor:
        """Spike thresholds relative to rest (mV) of a fly's neurons."""
        return self.theta[self.slot(fly_id), torch.as_tensor(neuron_ids, device=self.device)]

    def step(self):
        if self._stim:
            t = self.step_count
            flat, inc = [], []
            for fid, (ids, x) in self._stim.items():
                flat.append(ids + self.slot(fid) * self.n)
                inc.append(x)
            f, x = torch.cat(flat), torch.cat(inc)
            gv, last, ref = self.g.view(-1), self.last.view(-1), self.ref.view(-1)
            open_ = (t - last[f]) >= ref[f]
            gv[f] = torch.where(open_, gv[f] + x, gv[f])
        return super().step()


def stimulable(batch: BrainBatch) -> StimulatedBrain:
    """Give a live batch the test-only stimulation input (same object, same state)."""
    if not isinstance(batch, StimulatedBrain):
        batch.__class__ = StimulatedBrain
        batch._stim = {}
    return batch
