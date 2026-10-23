"""Per-drone failsafe supervisor: a small pure state machine.

The decision logic is deliberately a function of four numbers only (time, age of
the last peer message, age of the last GPS fix, on-ground flag), with no
dependency on the rest of the simulator. That makes it easy to (a) unit test and
(b) mirror in C++ for an embedded target: see ``failsafe/heartbeat_monitor.cpp``
and ``tests/test_cpp_conformance.py`` which replays recorded simulation traces
through both implementations and requires identical mode sequences.

Modes
-----
FORMATION     normal flight, tracking the formation / mission
HOLD          hold position: no peer heard for ``link_timeout``
FAILSAFE_GPS  no GPS fix for ``gps_timeout``: hover on dead-reckoning
LANDING       GPS failsafe lasted ``gps_land_after``: controlled descent (latched)
LANDED        on the ground (terminal)
FAILED        total vehicle failure, set from outside (motors out)
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

FORMATION, HOLD, FAILSAFE_GPS, LANDING, LANDED, FAILED = range(6)
MODE_NAMES = ("FORMATION", "HOLD", "FAILSAFE_GPS", "LANDING", "LANDED", "FAILED")


class SupervisorFSM:
    def __init__(self, sup_cfg: Dict, hb_timeout: float):
        self.link_timeout = float(sup_cfg["link_timeout"])
        self.link_recovery = float(sup_cfg["link_recovery"])
        self.gps_timeout = float(sup_cfg["gps_timeout"])
        self.gps_recovery = float(sup_cfg["gps_recovery"])
        self.gps_land_after = float(sup_cfg["gps_land_after"])
        self.hb_timeout = float(hb_timeout)
        self.mode = FORMATION
        self.t_gps_lost: Optional[float] = None
        self.gps_ok_since: Optional[float] = None
        self.in_streak = False
        self.streak_start = 0.0

    def step(self, t: float, link_age: float, gps_age: float, on_ground: bool
             ) -> Optional[Tuple[int, int]]:
        """Advance one tick. Returns (old_mode, new_mode) on a transition."""
        old = self.mode
        if old == FAILED:
            return None

        # continuous-reception tracking for leaving HOLD
        if link_age < self.hb_timeout:
            if not self.in_streak:
                self.in_streak = True
                self.streak_start = t
        else:
            self.in_streak = False

        gps_lost = gps_age > self.gps_timeout
        if gps_lost:
            self.gps_ok_since = None
        elif self.gps_ok_since is None:
            self.gps_ok_since = t

        m = self.mode
        if m == LANDED:
            pass
        elif m == LANDING:
            if on_ground:
                self.mode = LANDED
        else:
            if gps_lost:
                if m in (FORMATION, HOLD):
                    self.mode = FAILSAFE_GPS
                    self.t_gps_lost = t
                elif m == FAILSAFE_GPS and (t - self.t_gps_lost) >= self.gps_land_after:
                    self.mode = LANDING
            else:
                if m == FAILSAFE_GPS and (t - self.gps_ok_since) >= self.gps_recovery:
                    self.mode = FORMATION
            m = self.mode
            if m in (FORMATION, HOLD):
                if link_age > self.link_timeout:
                    self.mode = HOLD
                elif m == HOLD and self.in_streak and (t - self.streak_start) >= self.link_recovery:
                    self.mode = FORMATION

        if self.mode != old:
            return (old, self.mode)
        return None

    def force_failed(self) -> None:
        self.mode = FAILED
