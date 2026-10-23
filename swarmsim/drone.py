"""Drone plant model, GPS/dead-reckoning estimator and environment (wind).

Deliberately simple and honest: a 3-D point mass with a first-order velocity
loop, acceleration and speed limits, and a wind disturbance. It is NOT a
rotor-level flight model; see docs/DESIGN.md "Limitations".
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np

G = 9.81


class Environment:
    """Steady wind + common gust + per-drone turbulence (Ornstein-Uhlenbeck)."""

    def __init__(self, cfg: Dict, n: int, rng: np.random.Generator):
        e = cfg["env"]
        self.cfg = e
        self.rng = rng
        speed = rng.uniform(e["wind_steady_min"], e["wind_steady_max"])
        ang = rng.uniform(0.0, 2.0 * math.pi)
        self.steady = np.array([speed * math.cos(ang), speed * math.sin(ang)])
        self.gust = np.zeros(2)
        self.turb = np.zeros((n, 2))

    @staticmethod
    def _ou(x: np.ndarray, sigma: float, tau: float, dt: float, rng: np.random.Generator) -> np.ndarray:
        if sigma <= 0.0:
            return x
        return x - x / tau * dt + sigma * math.sqrt(2.0 / tau * dt) * rng.standard_normal(x.shape)

    def step(self, dt: float) -> None:
        e = self.cfg
        self.gust = self._ou(self.gust, e["gust_sigma"], e["gust_tau"], dt, self.rng)
        self.turb = self._ou(self.turb, e["turb_sigma"], e["turb_tau"], dt, self.rng)

    def wind3(self, i: int) -> np.ndarray:
        w = self.steady + self.gust + self.turb[i]
        return np.array([w[0], w[1], 0.0])


class Drone:
    def __init__(self, idx: int, pos0, cfg: Dict, rng: np.random.Generator, wind_hint: np.ndarray):
        self.id = idx
        self.cfg = cfg
        self.rng = rng
        self.pos = np.array(pos0, dtype=float)
        self.vel = np.zeros(3)            # air-relative velocity (what the autopilot tracks)
        self.ground_vel = np.zeros(3)
        self.failed = False               # total motor failure
        self.grounded = False
        self.battery = 100.0

        # --- estimator state ---
        s = cfg["sensors"]
        self.est_pos = self.pos + rng.normal(0.0, s["gps_sigma"], 3)
        self.est_vel = np.zeros(3)
        self.est_wind = np.array(wind_hint, dtype=float) + rng.normal(0.0, 0.3, 2)  # pre-flight wind reading
        self.vbias = np.zeros(3)
        self.last_gps_t = 0.0             # last time the receiver delivered a fix
        self.last_accept_t = 0.0          # last time a fix passed the innovation gate
        self.next_gps_t = 0.0
        self.fix_rejected = 0
        self.fix_accepted = 0

        # --- fault hooks (set by the fault injector) ---
        self.gps_available = True
        self.gps_sigma_scale = 1.0
        self.gps_outlier_prob = 0.0

    # ------------------------------------------------------------ physics
    def step_dynamics(self, dt: float, v_cmd_air: np.ndarray, wind3: np.ndarray) -> None:
        d = self.cfg["drone"]
        if self.grounded:
            self.vel[:] = 0.0
            self.ground_vel[:] = 0.0
            return
        if self.failed:
            # motors out: ballistic fall with horizontal drag
            self.vel[:2] *= math.exp(-0.3 * dt)
            self.vel[2] = max(self.vel[2] - G * dt, -30.0)
        else:
            cmd = np.array(v_cmd_air, dtype=float)
            h = math.hypot(cmd[0], cmd[1])
            if h > d["v_max"]:
                cmd[:2] *= d["v_max"] / h
            cmd[2] = max(-d["vz_max"], min(d["vz_max"], cmd[2]))
            a = (cmd - self.vel) / d["tau_v"]
            an = float(np.linalg.norm(a))
            if an > d["a_max"]:
                a *= d["a_max"] / an
            self.vel += a * dt
            spd = math.hypot(self.vel[0], self.vel[1])
            if spd > d["v_max"]:
                self.vel[:2] *= d["v_max"] / spd
            self.vel[2] = max(-d["vz_max"], min(d["vz_max"], self.vel[2]))
            self.battery = max(0.0, self.battery - (d["battery_drain_hover"]
                                                     + d["battery_drain_speed"] * spd) * dt)
        self.ground_vel = self.vel + wind3
        self.pos = self.pos + self.ground_vel * dt
        if self.pos[2] <= 0.0:
            self.pos[2] = 0.0
            self.vel[:] = 0.0
            self.ground_vel[:] = 0.0
            self.grounded = True

    # ---------------------------------------------------------- estimator
    def step_estimator(self, t: float, dt: float) -> None:
        """Dead-reckon every step; correct with a GPS fix at the receiver rate.

        * measured air velocity carries a slowly drifting bias (random walk)
        * wind is estimated as the low-passed difference GPS-velocity - air-velocity
        * fixes far from the prediction are rejected by an innovation gate, but only
          while the estimate is trusted (recent fix), so a long outage can recover
        """
        s = self.cfg["sensors"]
        if self.grounded:
            return
        self.vbias += self.rng.normal(0.0, s["imu_bias_walk"] * math.sqrt(dt), 3)
        v_air_meas = self.vel + self.vbias
        wind3 = np.array([self.est_wind[0], self.est_wind[1], 0.0])
        self.est_vel = v_air_meas + wind3
        self.est_pos = self.est_pos + self.est_vel * dt

        period = 1.0 / s["gps_rate_hz"]
        if t + 1e-9 >= self.next_gps_t:
            while self.next_gps_t <= t + 1e-9:
                self.next_gps_t += period
            if not self.gps_available:
                return
            sigma = s["gps_sigma"] * self.gps_sigma_scale
            z = self.pos + self.rng.normal(0.0, sigma, 3) * np.array([1.0, 1.0, 1.5])
            if self.gps_outlier_prob > 0.0 and self.rng.random() < self.gps_outlier_prob:
                z[:2] += self.rng.normal(0.0, 15.0, 2)
            gps_vel = self.ground_vel + self.rng.normal(0.0, s["gps_vel_sigma"], 3)
            self.last_gps_t = t                       # receiver is alive
            innov = z - self.est_pos
            gate = max(s["gate_min"], s["gate_sigmas"] * sigma)
            trusted = (t - self.last_accept_t) < 2.0
            if trusted and math.hypot(innov[0], innov[1]) > gate:
                self.fix_rejected += 1
            else:
                self.est_pos = self.est_pos + s["gps_alpha"] * innov
                self.last_accept_t = t
                self.fix_accepted += 1
            k = min(1.0, period / s["wind_est_tau"])
            self.est_wind = self.est_wind + k * ((gps_vel - v_air_meas)[:2] - self.est_wind)

    # --------------------------------------------------------------- misc
    @property
    def est_error(self) -> float:
        return float(np.linalg.norm(self.est_pos - self.pos))

    @property
    def airborne(self) -> bool:
        return not self.grounded
