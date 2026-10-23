"""The on-board software of one drone: peer table, supervisor, controller, safety monitor.

Everything in here only uses information a real vehicle would have: its own
estimated state and the (delayed, lossy) messages it received. Ground truth is
used by the simulator and the metrics, never by the agent.
"""
from __future__ import annotations

import math
from typing import Dict, FrozenSet, List, Optional, Tuple

import numpy as np

from .comms import Message
from .drone import Drone
from .formation import leg_heading, rot, slot_offset, wrap_angle
from .supervisor import (FAILED, FAILSAFE_GPS, FORMATION, HOLD, LANDED, LANDING,
                         MODE_NAMES, SupervisorFSM)

Event = Tuple[float, str, int, int, str]   # (t, type, observer, subject, detail)


class Agent:
    def __init__(self, idx: int, cfg: Dict, drone: Drone, controller, start_xy=(0.0, 0.0),
                 rng: Optional[np.random.Generator] = None, trace_fsm: bool = False):
        self.id = idx
        self.cfg = cfg
        self.drone = drone
        self.controller = controller
        self.rng = rng if rng is not None else np.random.default_rng(idx)
        self.fsm = SupervisorFSM(cfg["supervisor"], cfg["comms"]["hb_timeout"])
        self.wps = [np.array(w, dtype=float) for w in cfg["mission"]["waypoints"]]
        self.start_xy = np.array(start_xy, dtype=float)
        self.wp_idx = 0
        self.heading = leg_heading(self.wps, 0, self.start_xy)
        self.heading_rate = 0.0
        self.slot = slot_offset(cfg["formation"], idx, cfg["n_drones"], cfg["spacing"])  # fixed home slot
        self.t_form = 0.0
        self.table: Dict[int, Tuple[Message, float]] = {}
        self.last_any_rx = 0.0
        self.healthy_peers: Dict[int, Tuple[Message, float]] = {}
        self.prev_peer_ids: FrozenSet[int] = frozenset()
        self.alive: FrozenSet[int] = frozenset([idx])
        self.leader: Optional[int] = None
        self.hold_pos: Optional[np.ndarray] = None
        self.events: List[Event] = []
        self.outbox: Optional[Message] = None
        self.next_tx = 0.02 * idx                       # stagger transmissions
        self._sent_landed = False
        self.mission_done = False
        self.trace_fsm = trace_fsm
        self.fsm_trace: List[Tuple[float, float, float, int, int]] = []
        self.avoid_active = False
        self.geofence_active = False

    # ------------------------------------------------------------------ io
    def receive(self, t: float, msg: Message) -> None:
        prev = self.table.get(msg.src)
        if prev is None or msg.t_sent > prev[0].t_sent:
            self.table[msg.src] = (msg, t)
        self.last_any_rx = t

    @property
    def mode(self) -> int:
        return self.fsm.mode

    def log(self, t: float, kind: str, subject: int = -1, detail: str = "") -> None:
        self.events.append((t, kind, self.id, subject, detail))

    # -------------------------------------------------------- mission help
    def mission_velocity(self, c_xy: np.ndarray, idx: int) -> np.ndarray:
        """Desired ground velocity of the formation reference point."""
        m = self.cfg["mission"]
        if idx >= len(self.wps):
            return np.zeros(2)
        d = self.wps[idx] - c_xy
        dist = float(np.hypot(d[0], d[1]))
        if dist < 1e-6:
            return np.zeros(2)
        speed = m["cruise_speed"]
        if idx == len(self.wps) - 1:
            speed = min(speed, 0.5 * dist)
        return d / dist * speed

    def maybe_advance_waypoint(self, t: float, c_xy: np.ndarray) -> None:
        m = self.cfg["mission"]
        if self.wp_idx >= len(self.wps):
            return
        final = self.wp_idx == len(self.wps) - 1
        radius = m["final_radius"] if final else m["accept_radius"]
        if float(np.hypot(*(self.wps[self.wp_idx] - c_xy))) < radius:
            self.wp_idx += 1
            self.log(t, "WAYPOINT", -1, str(self.wp_idx))
            if self.wp_idx >= len(self.wps):
                self.mission_done = True

    def update_heading(self, dt: float) -> None:
        tgt = leg_heading(self.wps, self.wp_idx, self.start_xy)
        k = 1.0 - math.exp(-dt / self.cfg["control"]["heading_tau"])
        old = self.heading
        self.heading = wrap_angle(self.heading + wrap_angle(tgt - self.heading) * k)
        self.heading_rate = wrap_angle(self.heading - old) / dt

    def slot_velocity(self) -> np.ndarray:
        """Feed-forward velocity of the slot point caused by the formation turning."""
        s = rot(self.heading, self.slot)
        return self.heading_rate * np.array([-s[1], s[0]])

    def altitude_rate(self) -> float:
        c = self.cfg
        return c["control"]["kz"] * (c["altitude"] - self.drone.est_pos[2])

    # ------------------------------------------------------------ the step
    def step(self, t: float, dt: float) -> np.ndarray:
        """Run one control tick and return the air-relative velocity command."""
        d = self.drone
        self.outbox = None
        if self.fsm.mode == FAILED:
            return np.zeros(3)
        cfg = self.cfg
        hb = cfg["comms"]["hb_timeout"]

        # 1. supervisor (pure state machine on four numbers)
        link_age = t - self.last_any_rx
        gps_age = t - d.last_gps_t
        tr = self.fsm.step(t, link_age, gps_age, d.grounded)
        if self.trace_fsm:
            self.fsm_trace.append((t, link_age, gps_age, 1 if d.grounded else 0, self.fsm.mode))
        if tr is not None:
            self.log(t, "MODE", -1, f"{MODE_NAMES[tr[0]]}->{MODE_NAMES[tr[1]]}")
            if tr[1] == HOLD:
                self.hold_pos = d.est_pos.copy()
            if tr[1] == FORMATION:
                self.t_form = t            # re-entered: junior to everyone who stayed
        mode = self.fsm.mode

        # 2. peer bookkeeping
        healthy = {j: (m, rx) for j, (m, rx) in self.table.items()
                   if (t - rx) <= hb and m.healthy and m.mode == FORMATION}
        ids_now = frozenset(healthy)
        for j in self.prev_peer_ids - ids_now:
            self.log(t, "PEER_LOST", j)
        for j in ids_now - self.prev_peer_ids:
            self.log(t, "PEER_JOINED", j)
        self.prev_peer_ids = ids_now
        self.healthy_peers = healthy
        self.alive = frozenset(ids_now | {self.id})

        # 3. desired ground velocity
        v_g = np.zeros(3)
        if mode == FORMATION:
            v_g = self.controller.command(self, t, dt, healthy)
        elif mode == HOLD:
            kp = cfg["control"]["kp"]
            hp = self.hold_pos if self.hold_pos is not None else d.est_pos
            v_g[:2] = kp * (hp[:2] - d.est_pos[:2])
            v_g[2] = self.altitude_rate()
        elif mode == FAILSAFE_GPS:
            # barometric altitude does not need GPS: drop to a separation layer below the formation
            v_g[2] = cfg["control"]["kz"] * (cfg["altitude"] - cfg["supervisor"]["gps_layer_drop"] - d.est_pos[2])
        elif mode == LANDING:
            v_g[2] = -cfg["supervisor"]["land_speed"]

        # 4. runtime safety monitor
        if mode in (FORMATION, HOLD, FAILSAFE_GPS):
            v_g = self._safety_filter(t, v_g, mode)

        # 5. convert ground-velocity command to air-relative (wind feed-forward)
        v_air = v_g.copy()
        if mode != LANDED:
            v_air[:2] = v_g[:2] - d.est_wind
        else:
            v_air[:] = 0.0

        # 6. schedule broadcast
        if t + 1e-9 >= self.next_tx:
            self.next_tx += 1.0 / cfg["comms"]["rate_hz"]
            if mode != LANDED or not self._sent_landed:
                if mode == LANDED:
                    self._sent_landed = True
                self.outbox = Message(
                    src=self.id, t_sent=t,
                    pos=(float(d.est_pos[0]), float(d.est_pos[1]), float(d.est_pos[2])),
                    vel=(float(d.est_vel[0]), float(d.est_vel[1]), float(d.est_vel[2])),
                    wp=self.wp_idx,
                    slot=(float(self.slot[0]), float(self.slot[1])),
                    healthy=(mode == FORMATION), mode=mode, battery=d.battery, t_form=self.t_form,
                    gps_age=float(max(t - d.last_accept_t, 0.0)))
        return v_air

    # ---------------------------------------------------------- safety layer
    def _safety_filter(self, t: float, v_g: np.ndarray, mode: int) -> np.ndarray:
        s = self.cfg["safety"]
        hb = self.cfg["comms"]["hb_timeout"]
        d = self.drone
        vmax = self.cfg["drone"]["v_max"]
        out = v_g.copy()
        self.avoid_active = False
        if s["avoidance"]:
            rep = np.zeros(3)
            for j, (m, rx) in self.table.items():
                age = t - rx
                if age > s["ghost_time"] or m.mode == LANDED:
                    continue
                ext = min(max(t - m.t_sent, 0.0), s["ghost_extrap"])
                pred = np.array(m.pos) + np.array(m.vel) * ext
                # silent peers keep a growing keep-out radius (position uncertainty)
                d_eff = s["d_avoid"] + (0.3 * min(age, 10.0) if age > hb else 0.0)
                # a peer that reports stale GPS may really be anywhere near its broadcast position
                d_eff += min(s["unc_cap"], s["unc_rate"] * max(m.gps_age + age - s["unc_free"], 0.0))
                delta = d.est_pos - pred
                dist = float(np.linalg.norm(delta))
                if dist < d_eff:
                    if dist < 1e-3:
                        delta = self.rng.normal(0.0, 1.0, 3)
                        dist = float(np.linalg.norm(delta)) + 1e-9
                    frac = (d_eff - dist)
                    rep += delta / dist * s["k_rep"] * frac
                    # vertical deconfliction: the lower id climbs, the higher id descends
                    rep[2] += (1.0 if self.id < j else -1.0) * s["k_vert"] * frac / d_eff * vmax
            rn = float(np.linalg.norm(rep))
            if rn > 1e-9:
                self.avoid_active = True
                if rn > vmax:
                    rep *= vmax / rn
                out += rep
        self.geofence_active = False
        if s["geofence_enforce"] and mode in (FORMATION, HOLD):
            xmin, ymin, xmax, ymax = s["geofence"]
            mg = s["geofence_margin"]
            push = np.zeros(2)
            x, y = d.est_pos[0], d.est_pos[1]
            for axis, (lo, hi) in enumerate(((xmin, xmax), (ymin, ymax))):
                p = x if axis == 0 else y
                if p < lo + mg:
                    push[axis] += 3.0 * min(2.0, (lo + mg - p) / mg)
                elif p > hi - mg:
                    push[axis] -= 3.0 * min(2.0, (p - (hi - mg)) / mg)
            if abs(push[0]) + abs(push[1]) > 0.0:
                self.geofence_active = True
                out[:2] += push
        return out
