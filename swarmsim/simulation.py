"""Simulation engine: wires drones, agents, radio, faults and records ground truth."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .agent import Agent, Event
from .comms import CommsNetwork
from .config import deep_merge, validate_config, DEFAULTS
from .controllers import make_controller
from .drone import Drone, Environment
from .faults import FaultInjector, FaultRecord
from .formation import formation_offsets, rot
from .supervisor import FAILED, FORMATION


@dataclass
class Trace:
    """Ground-truth time series of one trial (all arrays indexed by step)."""
    dt: float
    n: int
    t: np.ndarray
    pos: np.ndarray            # (T, n, 3) true positions
    est_pos: np.ndarray        # (T, n, 3) estimated positions
    mode: np.ndarray           # (T, n) supervisor modes
    airborne: np.ndarray       # (T, n) bool
    participant: np.ndarray    # (T, n) bool: FORMATION & airborne
    battery: np.ndarray        # (T, n)
    peers: np.ndarray          # (T, n) healthy peers currently heard
    form_err: np.ndarray       # (T,) shape error of participants (nan if <2)
    consistent: np.ndarray     # (T,) all participants agree on membership
    min_sep: np.ndarray        # (T,) smallest 3-D distance between airborne drones
    ref_dist_final: np.ndarray  # (T,) truth reference point distance to final waypoint
    breach: np.ndarray         # (T,) any airborne drone outside geofence
    avoid: np.ndarray          # (T, n) avoidance repulsion active
    steps: int = 0


@dataclass
class SimResult:
    cfg: Dict
    seed: int
    trace: Trace
    events: List[Event]
    faults: List[FaultRecord]
    t_complete: Optional[float]
    comms_sent: int
    comms_dropped: int
    wind_steady: float
    fsm_traces: Optional[List[list]] = None
    false_peer_loss: int = 0
    explained_peer_loss: int = 0


class Simulation:
    def __init__(self, cfg: Dict, seed: int = 0, trace_fsm: bool = False):
        validate_config(cfg)
        self.cfg = cfg
        self.seed = seed
        n = cfg["n_drones"]
        self.n = n
        ss = np.random.SeedSequence(seed)
        r_env, r_sens, r_comm, r_fault, r_init, r_agent = [np.random.default_rng(s) for s in ss.spawn(6)]
        self.env = Environment(cfg, n, r_env)
        self.comms = CommsNetwork(n, cfg, r_comm)
        self.faults = FaultInjector(cfg, r_fault)

        wps = cfg["mission"]["waypoints"]
        start = np.array([0.0, 0.0])
        d0 = np.array(wps[0], dtype=float) - start
        h0 = math.atan2(d0[1], d0[0]) if np.hypot(*d0) > 1e-9 else 0.0
        offs = formation_offsets(cfg["formation"], n, cfg["spacing"])
        sens_rngs = [np.random.default_rng(s) for s in r_sens.bit_generator._seed_seq.spawn(n)]
        agent_rngs = [np.random.default_rng(s) for s in r_agent.bit_generator._seed_seq.spawn(n)]
        self.drones: List[Drone] = []
        self.agents: List[Agent] = []
        for i in range(n):
            p = np.zeros(3)
            p[:2] = start + rot(h0, offs[i]) + r_init.normal(0.0, 1.0, 2)
            p[2] = cfg["altitude"] + r_init.normal(0.0, 0.3)
            dr = Drone(i, p, cfg, sens_rngs[i], self.env.steady)
            self.drones.append(dr)
            ag = Agent(i, cfg, dr, make_controller(cfg["controller"]), start_xy=start,
                       rng=agent_rngs[i], trace_fsm=trace_fsm)
            ag.heading = h0
            self.agents.append(ag)
        self.trace_fsm = trace_fsm

    # ------------------------------------------------------------------
    def run(self) -> SimResult:
        cfg = self.cfg
        n, dt = self.n, cfg["dt"]
        T = int(cfg["t_max"] / dt) + 1
        tr = Trace(
            dt=dt, n=n, t=np.zeros(T), pos=np.zeros((T, n, 3)), est_pos=np.zeros((T, n, 3)),
            mode=np.zeros((T, n), dtype=np.int8), airborne=np.zeros((T, n), dtype=bool),
            participant=np.zeros((T, n), dtype=bool), battery=np.zeros((T, n), dtype=np.float32),
            peers=np.zeros((T, n), dtype=np.int8), form_err=np.full(T, np.nan),
            consistent=np.ones(T, dtype=bool), min_sep=np.full(T, np.inf),
            ref_dist_final=np.full(T, np.inf), breach=np.zeros(T, dtype=bool),
            avoid=np.zeros((T, n), dtype=bool))
        wp_last = np.array(cfg["mission"]["waypoints"][-1], dtype=float)
        fence = cfg["safety"]["geofence"]
        mission_radius = 10.0
        t_complete: Optional[float] = None
        end_step = T
        true_pos = np.zeros((n, 3))
        iu = np.triu_indices(n, 1)
        k = 0
        while k < T:
            t = k * dt
            self.faults.update(t, self)
            self.env.step(dt)
            for dr in self.drones:
                dr.step_estimator(t, dt)
            for j, msg in self.comms.deliver(t):
                self.agents[j].receive(t, msg)
            cmds = []
            for i, ag in enumerate(self.agents):
                cmds.append(ag.step(t, dt))
            for i in range(n):
                true_pos[i] = self.drones[i].pos
            for ag in self.agents:
                if ag.outbox is not None:
                    self.comms.broadcast(t, ag.outbox, true_pos)
            for i, dr in enumerate(self.drones):
                dr.step_dynamics(dt, cmds[i], self.env.wind3(i))
            # ---------------- ground-truth recording ----------------
            for i, (dr, ag) in enumerate(zip(self.drones, self.agents)):
                tr.pos[k, i] = dr.pos
                tr.est_pos[k, i] = dr.est_pos
                tr.mode[k, i] = ag.fsm.mode
                tr.airborne[k, i] = dr.airborne
                tr.participant[k, i] = (ag.fsm.mode == FORMATION) and dr.airborne and not dr.failed
                tr.battery[k, i] = dr.battery
                tr.peers[k, i] = len(ag.healthy_peers)
                tr.avoid[k, i] = ag.avoid_active
            tr.t[k] = t
            part = np.nonzero(tr.participant[k])[0]
            air = np.nonzero(tr.airborne[k])[0]
            if len(air) >= 2:
                p = tr.pos[k][air]
                dd = np.linalg.norm(p[:, None, :] - p[None, :, :], axis=2)
                tr.min_sep[k] = dd[np.triu_indices(len(air), 1)].min()
            if len(air):
                p = tr.pos[k][air]
                tr.breach[k] = bool(np.any((p[:, 0] < fence[0]) | (p[:, 0] > fence[2]) |
                                           (p[:, 1] < fence[1]) | (p[:, 1] > fence[3])))
            if len(part) >= 1:
                refs = []
                s_list = []
                for i in part:
                    ag = self.agents[i]
                    s = rot(ag.heading, ag.slot)
                    s_list.append(s)
                    refs.append(tr.pos[k, i, :2] - s)
                refs = np.array(refs)
                tr.ref_dist_final[k] = float(np.hypot(*(refs.mean(axis=0) - wp_last)))
                if len(part) >= 2:
                    dev = refs - refs.mean(axis=0)
                    tr.form_err[k] = float(np.sqrt((dev ** 2).sum(axis=1).mean()))
                pset = frozenset(int(i) for i in part)
                tr.consistent[k] = all(self.agents[i].alive == pset for i in part)
            if t_complete is None and tr.ref_dist_final[k] < mission_radius and len(part) >= 2 \
                    and all(self.agents[i].wp_idx >= len(self.agents[i].wps) for i in part):
                t_complete = t
            if t_complete is not None and t >= t_complete + cfg["settle_time"]:
                end_step = k + 1
                break
            k += 1
        tr.steps = min(end_step, T)
        self._trim(tr)

        events: List[Event] = []
        for ag in self.agents:
            events.extend(ag.events)
        events.sort(key=lambda e: (e[0], e[2]))
        res = SimResult(cfg=cfg, seed=self.seed, trace=tr, events=events, faults=self.faults.records,
                        t_complete=t_complete, comms_sent=self.comms.sent,
                        comms_dropped=self.comms.dropped, wind_steady=float(np.hypot(*self.env.steady)))
        if self.trace_fsm:
            res.fsm_traces = [ag.fsm_trace for ag in self.agents]
        self._classify_peer_loss(res)
        return res

    @staticmethod
    def _trim(tr: Trace) -> None:
        s = tr.steps
        for name in ("t", "pos", "est_pos", "mode", "airborne", "participant", "battery", "peers",
                     "form_err", "consistent", "min_sep", "ref_dist_final", "breach", "avoid"):
            setattr(tr, name, getattr(tr, name)[:s])

    def _classify_peer_loss(self, res: SimResult) -> None:
        """A PEER_LOST is *explained* if the subject or observer was not a healthy
        participant, or a radio/airframe fault involved either of them. Otherwise it
        is a false alarm (e.g. packet loss tripping the heartbeat timeout)."""
        tr = res.trace
        false = explained = 0
        for (t, kind, obs, subj, _d) in res.events:
            if kind != "PEER_LOST" or t < 2.0:
                continue
            k = min(int(round(t / tr.dt)), tr.steps - 1)
            subj_ok = bool(tr.participant[max(k - 8, 0): k + 1, subj].all())   # healthy for last ~0.8 s
            obs_ok = bool(tr.participant[k, obs])
            if (not subj_ok) or (not obs_ok) or self.faults.comms_fault_active(t, [subj, obs]):
                explained += 1
            else:
                false += 1
        res.false_peer_loss = false
        res.explained_peer_loss = explained


def build_config(scenario_cfg: Optional[Dict] = None, **overrides) -> Dict:
    cfg = deep_merge(DEFAULTS, scenario_cfg or {})
    cfg = deep_merge(cfg, overrides)
    return cfg


def run_simulation(cfg: Dict, seed: int = 0, trace_fsm: bool = False) -> SimResult:
    return Simulation(cfg, seed=seed, trace_fsm=trace_fsm).run()
