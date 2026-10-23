"""Fault injection: scripted failures applied to the simulated hardware.

Supported fault types (see docs/ICD.md section 5 for the YAML schema):

gps_dropout    receiver delivers no fixes (drone -> dead reckoning)
gps_noise      receiver noise x ``sigma_scale`` and optional outliers
comms_loss     radio dead in both directions (single drone, list, or "all")
drone_failure  total motor failure (ballistic fall), permanent
packet_loss    extra packet loss probability on every link
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import numpy as np

DISCRETE = ("gps_dropout", "comms_loss", "drone_failure")   # evaluated for detection/recovery


@dataclass
class FaultRecord:
    type: str
    drones: List[int]
    t_on: float
    t_off: float                       # inf when permanent
    params: Dict = field(default_factory=dict)
    applied: bool = False
    cleared: bool = False

    @property
    def discrete(self) -> bool:
        return self.type in DISCRETE

    @property
    def finite(self) -> bool:
        return math.isfinite(self.t_off)


class FaultInjector:
    def __init__(self, cfg: Dict, rng: np.random.Generator):
        n = cfg["n_drones"]
        self.records: List[FaultRecord] = []
        for f in cfg["faults"]:
            d = f.get("drone", "all")
            drones = list(range(n)) if d == "all" else ([int(x) for x in d] if isinstance(d, list) else [int(d)])
            jit = float(f.get("t_jitter", 0.0))
            t_on = float(f["t"]) + (rng.uniform(-jit, jit) if jit > 0 else 0.0)
            dur = f.get("duration")
            t_off = t_on + float(dur) if dur is not None else math.inf
            params = {k: v for k, v in f.items() if k not in ("type", "drone", "t", "duration", "t_jitter")}
            self.records.append(FaultRecord(f["type"], drones, t_on, t_off, params))

    def update(self, t: float, sim) -> None:
        for r in self.records:
            if not r.applied and t >= r.t_on:
                self._apply(r, sim, on=True)
                r.applied = True
            if r.applied and not r.cleared and t >= r.t_off:
                self._apply(r, sim, on=False)
                r.cleared = True

    # --------------------------------------------------------------------
    def _apply(self, r: FaultRecord, sim, on: bool) -> None:
        if r.type == "gps_dropout":
            for i in r.drones:
                sim.drones[i].gps_available = not on
        elif r.type == "gps_noise":
            for i in r.drones:
                sim.drones[i].gps_sigma_scale = float(r.params.get("sigma_scale", 5.0)) if on else 1.0
                sim.drones[i].gps_outlier_prob = float(r.params.get("outlier_prob", 0.0)) if on else 0.0
        elif r.type == "comms_loss":
            for i in r.drones:
                sim.comms.tx_ok[i] = not on
                sim.comms.rx_ok[i] = not on
        elif r.type == "drone_failure":
            if on:
                for i in r.drones:
                    sim.drones[i].failed = True
                    sim.agents[i].fsm.force_failed()
        elif r.type == "packet_loss":
            sim.comms.extra_loss = float(r.params.get("prob", 0.3)) if on else 0.0

    # --------------------------------------------------------------------
    def comms_fault_active(self, t: float, drone_ids: Sequence[int], grace: float = 3.0) -> bool:
        """True if a radio fault involving any of drone_ids was active within the grace window."""
        for r in self.records:
            if r.type != "comms_loss" and r.type != "drone_failure":
                continue
            if not set(r.drones) & set(drone_ids):
                continue
            if r.t_on - 0.01 <= t <= r.t_off + grace:
                return True
        return False
