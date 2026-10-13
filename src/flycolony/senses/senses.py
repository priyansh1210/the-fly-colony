"""SenseBatch: world + body → sensory-neuron rates and photoreceptor input (spec 004).

Each senses step reads only the fly's own body state and the world at its sensor positions
(SENSE-R-001), computes every channel's receptor response, and writes one dense rate tensor
[N, n_sensory] (Hz) for `BrainBatch.set_senses`. Vision (vision.py) runs on its own period and
fills the photoreceptor input.

Transduction (all parameters in config/params/senses.yaml):
- taste: Hill function of the tastant in the drop at each labellum half, × the catalogued hunger
  gain routes (sugar, bitter), with first-order adaptation toward a fraction of the onset response;
- smell: DoOR tuning (config/senses/door_tuning.yaml) × a Hill function of each odorant at each
  antenna (palp glomeruli sample at the palps), with adaptation;
- Johnston's organ C/E: rectified Hill function of the arista deflection from the air velocity
  relative to the head plus gravity, opposite polarity for JO-C and JO-E types;
- thermo: phasic hot/cold responses to the rate of change of air temperature at the arista;
  hygro: tonic dry/moist responses to relative humidity.
Every channel has a spontaneous rate; undriven channels (no established ligand) fire at it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
import yaml

from flycolony.body.body import AIRBORNE, BodyBatch
from flycolony.brain.modulation import RouteCatalog, load_routes
from flycolony.config import project_root
from flycolony.registry import Registry
from flycolony.senses.layout import SensoryLayout
from flycolony.world.entities import TASTANTS
from flycolony.world.world import WorldGroup

SUCROSE, BITTER, SALT = (TASTANTS.index(t) for t in ("sucrose", "bitter", "salt"))
DIM = 3  # registry-ok: 3D vectors


def hill(x: torch.Tensor, half: float, n: float) -> torch.Tensor:
    x = x.clamp_min(0)
    xn = x**n
    return xn / (xn + half**n)


@dataclass
class ChannelParams:
    spont: float
    max_rate: float
    half: float
    hill_n: float
    adapt_tau_s: float
    adapt_frac: float  # steady-state response as a fraction of onset (1 = no adaptation)

    @classmethod
    def from_registry(cls, reg: Registry, prefix: str) -> ChannelParams:
        g = lambda k: float(reg.get(f"{prefix}.{k}"))  # noqa: E731
        return cls(
            g("spont_hz"), g("max_hz"), g("half"), g("hill_n"), g("adapt_tau_s"), g("adapt_frac")
        )


class SenseBatch:
    """Sensory transduction for the N flies of a body batch sharing one template layout."""

    def __init__(
        self,
        layout: SensoryLayout,
        reg: Registry,
        device: torch.device,
        routes: RouteCatalog | None = None,
    ):
        self.layout, self.reg, self.device = layout, reg, device
        self.routes = routes or load_routes()
        f32 = torch.float32
        chans = list(layout.channels.values())
        self.chan_names = [c.name for c in chans]
        # Per sensory neuron: channel index and side, for the [N, C, 2] → [N, n] gather.
        ch = np.zeros(layout.n_sensory, dtype=np.int64)
        side = np.zeros(layout.n_sensory, dtype=np.int64)
        for i, c in enumerate(chans):
            ch[c.start : c.stop] = i
            side[c.start : c.stop] = c.side
        self.neuron_chan = torch.from_numpy(ch).to(device)
        self.neuron_side = torch.from_numpy(side).to(device)
        # Channel parameters (None = undriven, spontaneous only).
        self.params: dict[str, ChannelParams | None] = {}
        for c in chans:
            key = c.spec.get("params")
            self.params[c.name] = ChannelParams.from_registry(reg, key) if key else None
        spont_default = float(reg.get("senses.undriven.spont_hz"))
        self.spont = torch.tensor(
            [p.spont if p else spont_default for p in (self.params[n] for n in self.chan_names)],
            dtype=f32,
            device=device,
        )
        # Smell: tuning matrix [n_glom_channels, n_odor] in odor-species order.
        tun = yaml.safe_load(
            (project_root() / "config" / "senses" / "door_tuning.yaml").read_text(encoding="utf-8")
        )
        odors = list(reg.get("world.odor.species"))
        self.smell_idx = [i for i, c in enumerate(chans) if c.sense == "smell"]
        mat = np.zeros((len(self.smell_idx), len(odors)), dtype=np.float32)
        base = np.zeros(len(self.smell_idx), dtype=np.float32)
        palp = np.zeros(len(self.smell_idx), dtype=bool)
        for k, i in enumerate(self.smell_idx):
            glom = chans[i].spec["glomerulus"]
            palp[k] = chans[i].spec["palp"]
            base[k] = tun["spontaneous"].get(glom, 0.0)
            for o, e in tun["glomeruli"].get(glom, {}).items():
                mat[k, odors.index(o)] = e["response"]
        # DoOR responses are relative to spontaneous activity: drive = response − SFR.
        self.tuning = torch.from_numpy(mat - base[:, None]).to(device)
        self.palp = torch.from_numpy(palp).to(device)
        self.taste_idx = {c.name: i for i, c in enumerate(chans) if c.sense == "taste"}
        self.thermo_idx = {c.name: i for i, c in enumerate(chans) if c.sense == "thermo"}
        jo = layout.channels.get("jo_ce")
        self.jo = jo
        if jo is not None:
            pol = [
                1.0 if t.startswith("JO-C") else -1.0 if t.startswith("JO-E") else 0.0
                for t in jo.cell_type
            ]
            self.jo_polarity = torch.tensor(pol, dtype=f32, device=device)
            self.jo_side = torch.from_numpy(jo.side).to(device)
        g = lambda k: float(reg.get(k))  # noqa: E731
        self.labellum_half_width = g("senses.taste.labellum_half_width_mm")
        self.palp_drop = g("senses.smell.palp_below_head_mm")
        self.arista_angle = g("senses.jo.arista_angle_rad")
        self.jo_gravity_gain = g("senses.jo.gravity_equivalent_mm_s")
        self.odor_half = g("senses.smell.odor_half")
        self.odor_n = g("senses.smell.odor_hill_n")
        self.water_half_osm = g("senses.taste.water.half_osmolality")
        self.salt_low_max = g("senses.taste.low_salt.max_concentration")
        self.thermo_gain = g("senses.thermo.gain_hz_per_c_s")
        self.thermo_tau = g("senses.thermo.tau_s")
        self.hygro_gain = g("senses.hygro.gain_hz_per_rh")
        self.n = 0
        self._alloc(0)

    def _alloc(self, n: int) -> None:
        c = len(self.chan_names)
        self.adapt = torch.zeros(n, c, 2, dtype=torch.float32, device=self.device)
        self.prev_temp = torch.full((n, 2), float("nan"), dtype=torch.float32, device=self.device)
        self.phasic = torch.zeros(n, 2, dtype=torch.float32, device=self.device)

    def resize(self, n: int) -> None:
        """Match the body batch size (new flies start unadapted)."""
        if n == self.n:
            return
        old = (self.adapt, self.prev_temp, self.phasic)
        self._alloc(n)
        k = min(n, self.n)
        self.adapt[:k], self.prev_temp[:k], self.phasic[:k] = (t[:k] for t in old)
        self.n = n

    # --- one senses step -------------------------------------------------------------------------

    def step(
        self,
        world: WorldGroup,
        body: BodyBatch,
        dt: float,
        intero: dict[str, torch.Tensor] | None = None,
    ) -> torch.Tensor:
        """Sensory rates [N, n_sensory] (Hz). `intero` holds route sources per fly (006)."""
        self.resize(body.n)
        n, c = body.n, len(self.chan_names)
        drive = torch.zeros(n, c, 2, dtype=torch.float32, device=self.device)
        sites = body.sites()
        self._taste(world, body, sites, drive, intero or {})
        self._smell(world, body, sites, drive)
        self._thermo(world, body, sites, drive, dt)
        rates = self._adapt_and_rate(drive, dt)
        out = rates[:, self.neuron_chan, self.neuron_side]
        if self.jo is not None:
            out[:, self.jo.start : self.jo.stop] = self._jo(world, body, sites)
        return out

    def _taste(self, world, body, sites, drive, intero) -> None:
        comp = world.composition()  # [W, K, T]
        lft = body.left
        conc = []
        for _s, sign in ((0, 1.0), (1, -1.0)):  # left / right labellum half
            p = sites["labellum"] + lft * (sign * self.labellum_half_width)
            k = world.patches.contains(body.world, p)
            c = comp[body.world, k.clamp_min(0)] * (k >= 0).unsqueeze(-1)
            conc.append((c.float(), (k >= 0).float()))
        gains = self._route_gains(intero, body.n)
        for side, (c, wet) in enumerate(conc):
            for name, i in self.taste_idx.items():
                p = self.params[name]
                if p is None:
                    continue
                if name == "sugar":
                    x = hill(c[:, SUCROSE], p.half, p.hill_n)
                elif name == "bitter":
                    x = hill(c[:, BITTER], p.half, p.hill_n)
                elif name == "water":  # ppk28: on liquid contact, inhibited by osmolality
                    osm = c[:, SUCROSE] + c[:, BITTER] + 2 * c[:, SALT]
                    x = wet * self.water_half_osm / (self.water_half_osm + osm)
                elif name == "low_salt":
                    x = hill(c[:, SALT].clamp_max(self.salt_low_max), p.half, p.hill_n)
                elif name == "high_salt":
                    x = hill(c[:, SALT], p.half, p.hill_n)
                else:
                    continue
                drive[:, i, side] = x * gains.get(name, 1.0)

    def _route_gains(self, intero: dict[str, torch.Tensor], n: int) -> dict[str, torch.Tensor]:
        """Sensory-layer route gains (SENSE-R-032): only catalogued sense_channel routes."""
        out = {}
        for r in self.routes.routes:
            ch = r.target.sense_channel
            if ch is None or r.source not in intero:
                continue
            v = intero[r.source].to(self.device, torch.float32)
            if r.transfer.kind == "linear":
                g = r.transfer.gain * v + r.transfer.offset
            else:
                g = r.transfer.max / (1 + torch.exp(-(v - r.transfer.half) / r.transfer.slope))
            out[ch] = g.clamp_min(0)
        return out

    def _smell(self, world, body, sites, drive) -> None:
        if not self.smell_idx:
            return
        palp_pos = sites["head"] - body.up * self.palp_drop
        samples = [world.odor_at(body.world, sites[k]).float() for k in ("antenna_l", "antenna_r")]
        palp = world.odor_at(body.world, palp_pos).float()
        idx = torch.tensor(self.smell_idx, device=self.device)
        for side, conc in enumerate(samples):
            act = hill(conc, self.odor_half, self.odor_n)  # [N, O]
            pal = hill(palp, self.odor_half, self.odor_n)
            x = act @ self.tuning.T  # [N, G]
            xp = pal @ self.tuning.T
            x = torch.where(self.palp.unsqueeze(0), xp, x)
            drive[:, idx, side] = x

    def _thermo(self, world, body, sites, drive, dt) -> None:
        temps, hums = [], []
        for k in ("antenna_l", "antenna_r"):
            t, h = world.air_at(body.world, sites[k])
            temps.append(t.float())
            hums.append(h.float())
        temp = torch.stack(temps, -1)  # [N, 2]
        hum = torch.stack(hums, -1)
        prev = torch.where(torch.isnan(self.prev_temp), temp, self.prev_temp)
        rate = (temp - prev) / dt  # °C/s
        a = float(np.exp(-dt / self.thermo_tau))
        self.phasic = self.phasic * a + rate * (1 - a)
        self.prev_temp = temp
        for name, i in self.thermo_idx.items():
            kind = next(c["kind"] for c in self._thermo_specs() if c["channel"] == name)
            if kind == "phasic_up":
                drive[:, i] = (self.phasic * self.thermo_gain).clamp_min(0)
            elif kind == "phasic_down":
                drive[:, i] = (-self.phasic * self.thermo_gain).clamp_min(0)
            elif kind == "tonic_dry":
                drive[:, i] = (1 - hum) * self.hygro_gain
            elif kind == "tonic_moist":
                drive[:, i] = hum * self.hygro_gain

    def _thermo_specs(self) -> list[dict]:
        return [c.spec for c in self.layout.channels.values() if c.sense == "thermo"]

    def _adapt_and_rate(self, drive: torch.Tensor, dt: float) -> torch.Tensor:
        """Rates [N, C, 2] = spont + max · (drive − adaptation), adaptation tracks the drive."""
        rates = self.spont.view(1, -1, 1).expand_as(drive).clone()
        for i, name in enumerate(self.chan_names):
            p = self.params[name]
            if p is None or self.layout.channels[name].sense == "mechano":
                continue
            d = drive[:, i]
            a = float(np.exp(-dt / p.adapt_tau_s))
            target = d * (1 - p.adapt_frac)
            self.adapt[:, i] = self.adapt[:, i] * a + target * (1 - a)
            rates[:, i] = (p.spont + p.max_rate * (d - self.adapt[:, i])).clamp(0, p.max_rate)
        return rates

    def _jo(self, world, body, sites) -> torch.Tensor:
        """JO-C/E rates per neuron from arista deflection (wind + self-motion + gravity)."""
        p = self.params["jo_ce"]
        head = sites["head"]
        air = world.wind_at(body.world, head)
        own = torch.where(
            (body.mode == AIRBORNE).unsqueeze(-1), body.vel, body.fwd * body.speed.unsqueeze(-1)
        )
        v_rel = air - own  # air velocity relative to the head (mm/s)
        g = torch.tensor([0.0, 0.0, -1.0], dtype=v_rel.dtype, device=self.device)
        defl = []
        for sign in (1.0, -1.0):  # left, right arista: forward-outward axes (mirror images)
            ax = body.fwd * np.cos(self.arista_angle) + body.left * (
                sign * np.sin(self.arista_angle)
            )
            defl.append((v_rel * ax).sum(-1) + self.jo_gravity_gain * (g * ax).sum(-1))
        d = torch.stack(defl, -1).float()  # [N, 2]
        per = d[:, self.jo_side] * self.jo_polarity  # [N, n_jo]
        x = hill(per, p.half, p.hill_n)
        rate = p.spont + p.max_rate * x
        return torch.where(self.jo_polarity == 0, torch.full_like(rate, p.spont), rate)
