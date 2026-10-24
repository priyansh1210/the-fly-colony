"""Per-fly central rates around the calibrated kick (bistability check), two seed sets."""
from dataclasses import replace
import numpy as np, torch
from flycolony.brain.build import setup_brain, template_path
from flycolony.brain.engine import BrainBatch, FlyBrainSpec
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.registry import Registry

dev = torch.device("cuda")
cfg = load_all()["colony.yaml"]
reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female"))
setup = setup_brain(t, dev, cfg, reg)
nr = t.neurons
sp = setup.topo.spiking.cpu().numpy()
central = (nr["super_class"] == "central").fill_null(False).to_numpy().astype(bool) & sp
for w in (0.60, 0.64, 0.68, 0.70):
    for base in (7000, 9100):
        b = BrainBatch(setup.topo, replace(setup.params, noise_w=w), setup.dt,
                       plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
        Modulation(t, load_receptors(), load_routes()).attach(b)
        for i in range(8):
            b.add(FlyBrainSpec(f"n{i}", base + i))
        list(b.run(round(500 / setup.dt)))
        c = torch.zeros(b.batch_size * b.n, dtype=torch.int64, device=dev)
        b.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
        list(b.run(round(2000 / setup.dt)))
        r = (c.view(b.batch_size, b.n).double() / 2.0).cpu().numpy()[:, central].mean(1)
        print(f"w={w:.2f} seeds {base}+: per-fly central mean Hz", np.round(r, 2), flush=True)
        del b
