"""Broadcast radio model: range limit, latency + jitter, packet loss, outages."""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np


@dataclass(frozen=True)
class Message:
    """State broadcast ("heartbeat + state"). Treated as immutable.

    Fields mirror docs/ICD.md section 3.
    """
    src: int
    t_sent: float
    pos: Tuple[float, float, float]     # estimated position [m]
    vel: Tuple[float, float, float]     # estimated ground velocity [m/s]
    wp: int                             # current mission waypoint index
    slot: Tuple[float, float]           # advertised slot offset (forward, left) [m]
    healthy: bool                       # True only in FORMATION mode
    mode: int                           # supervisor mode (see supervisor.py)
    battery: float                      # percent
    t_form: float = 0.0                 # time this drone (re)entered FORMATION (leader seniority)
    gps_age: float = 0.0                # seconds since this drone last accepted a GPS fix


class CommsNetwork:
    def __init__(self, n: int, cfg: Dict, rng: np.random.Generator):
        self.n = n
        self.c = cfg["comms"]
        self.rng = rng
        self.tx_ok = [True] * n
        self.rx_ok = [True] * n
        self.extra_loss = 0.0
        self._q: List[Tuple[float, int, int, Message]] = []
        self._seq = itertools.count()
        self.sent = 0
        self.dropped = 0

    def broadcast(self, t: float, msg: Message, true_pos: np.ndarray) -> None:
        s = msg.src
        if not self.tx_ok[s]:
            return
        c = self.c
        p_loss = min(1.0, c["loss_prob"] + self.extra_loss)
        for j in range(self.n):
            if j == s:
                continue
            self.sent += 1
            d = true_pos[s] - true_pos[j]
            if (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) ** 0.5 > c["range"]:
                self.dropped += 1
                continue
            if self.rng.random() < p_loss:
                self.dropped += 1
                continue
            lat = c["latency"] + c["latency_jitter"] * self.rng.random()
            heapq.heappush(self._q, (t + lat, next(self._seq), j, msg))

    def deliver(self, t: float) -> List[Tuple[int, Message]]:
        out: List[Tuple[int, Message]] = []
        while self._q and self._q[0][0] <= t + 1e-9:
            _, _, j, msg = heapq.heappop(self._q)
            if self.rx_ok[j]:
                out.append((j, msg))
        return out
