"""Configuration defaults and YAML loading for SwarmSim.

Every tunable number lives here (or in a scenario YAML that overrides it), so a
reviewer can see exactly which assumptions a result depends on.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict

import yaml

DEFAULTS: Dict[str, Any] = {
    "n_drones": 5,
    "dt": 0.1,                 # simulation / control step [s]
    "t_max": 200.0,            # hard time limit per trial [s]
    "settle_time": 6.0,        # extra time simulated after mission completion [s]
    "altitude": 30.0,          # common cruise altitude [m]
    "spacing": 10.0,           # formation spacing parameter [m]
    "formation": "wedge",      # wedge | line | column
    "controller": "leader_follower",   # leader_follower | consensus
    "mission": {
        # Horizontal waypoints of the formation reference point [m], local frame.
        "waypoints": [[100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]],
        "cruise_speed": 4.0,   # [m/s]
        "accept_radius": 8.0,  # intermediate waypoint acceptance radius [m]
        "final_radius": 4.0,   # final waypoint acceptance radius [m]
    },
    "drone": {
        "v_max": 8.0,          # max horizontal air speed [m/s]
        "vz_max": 2.0,         # max vertical speed [m/s]
        "a_max": 3.0,          # max acceleration [m/s^2]
        "tau_v": 0.5,          # velocity-loop time constant [s]
        "battery_drain_hover": 0.012,   # [% per s]
        "battery_drain_speed": 0.002,   # additional [% per (m/s) per s]
    },
    "env": {
        "wind_steady_min": 0.0,    # steady wind speed range [m/s]
        "wind_steady_max": 2.0,
        "gust_sigma": 0.8,         # common gust (Ornstein-Uhlenbeck) [m/s]
        "gust_tau": 5.0,           # [s]
        "turb_sigma": 0.3,         # per-drone turbulence [m/s]
        "turb_tau": 2.0,           # [s]
    },
    "sensors": {
        "gps_rate_hz": 5.0,
        "gps_sigma": 0.6,          # position noise [m]
        "gps_vel_sigma": 0.1,      # velocity noise [m/s]
        "gps_alpha": 0.5,          # position-fix blending gain
        "gate_min": 5.0,           # innovation gate lower bound [m]
        "gate_sigmas": 4.0,        # innovation gate in sigmas
        "imu_bias_walk": 0.04,     # velocity bias random walk [m/s/sqrt(s)]
        "wind_est_tau": 4.0,       # wind estimator time constant [s]
    },
    "comms": {
        "rate_hz": 5.0,
        "range": 80.0,             # radio range [m]
        "latency": 0.2,            # [s]
        "latency_jitter": 0.1,     # [s]
        "loss_prob": 0.05,         # baseline per-packet loss
        "hb_timeout": 2.4,         # peer lost after this silence [s]; 12 packets at 5 Hz: false alarm ~ loss^12
    },
    "supervisor": {                # failsafe state machine (mirrored in C++)
        "link_timeout": 3.0,       # [s] with no peer heard -> HOLD
        "link_recovery": 1.0,      # [s] of continuous reception to leave HOLD
        "gps_timeout": 1.5,        # [s] with no accepted fix -> GPS failsafe
        "gps_recovery": 2.0,       # [s] of fixes needed to leave GPS failsafe
        "gps_land_after": 10.0,    # [s] in GPS failsafe before landing
        "land_speed": 1.0,         # [m/s]
        "gps_layer_drop": 6.0,     # in GPS failsafe, descend this far below formation altitude [m]
    },
    "safety": {                    # runtime safety monitor
        "avoidance": True,         # separation keeping + ghost tracks
        "d_avoid": 7.0,            # start repelling inside this range [m]
        "k_rep": 1.5,              # repulsion gain [1/s]
        "k_vert": 1.5,             # vertical deconfliction strength (x v_max at contact)
        "unc_rate": 0.7,           # keep-out growth per second of stale peer GPS [m/s]
        "unc_free": 1.5,           # seconds of staleness ignored (normal fix gaps, latency)
        "unc_cap": 10.0,           # max keep-out growth [m]
        "ghost_time": 20.0,        # keep tracks of silent peers this long [s]
        "ghost_extrap": 3.0,       # max extrapolation of a silent peer [s]
        "geofence": [-50.0, -50.0, 150.0, 150.0],   # xmin, ymin, xmax, ymax
        "geofence_margin": 10.0,   # soft push-back band inside the fence [m]
        "geofence_enforce": True,
    },
    "control": {
        "kp": 0.8,                 # slot tracking gain [1/s]
        "kz": 1.0,                 # altitude gain [1/s]
        "heading_tau": 7.0,        # heading filter [s]; limits outer-slot swing speed in turns
    },
    "faults": [],
}


def deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Return base updated recursively with over (neither input is mutated)."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def load_scenario(path: str) -> Dict[str, Any]:
    """Load a scenario YAML and merge it over DEFAULTS.

    A scenario file has: name, description, [sim overrides...], faults, criteria,
    allowed_losses. The result carries the merged simulation config plus the
    keys 'name', 'description', 'criteria', 'allowed_losses'.
    """
    raw = load_yaml(path)
    name = raw.get("name") or os.path.splitext(os.path.basename(path))[0]
    meta_keys = ("name", "description", "criteria", "allowed_losses", "tags", "expect_rejoin")
    sim_overrides = {k: v for k, v in raw.items() if k not in meta_keys}
    cfg = deep_merge(DEFAULTS, sim_overrides)
    cfg["name"] = name
    cfg["description"] = raw.get("description", "")
    cfg["criteria"] = raw.get("criteria", {}) or {}
    cfg["allowed_losses"] = int(raw.get("allowed_losses", 0))
    cfg["expect_rejoin"] = bool(raw.get("expect_rejoin", False))
    cfg["tags"] = raw.get("tags", [])
    validate_config(cfg)
    return cfg


FAULT_TYPES = ("gps_dropout", "gps_noise", "comms_loss", "drone_failure", "packet_loss")


def validate_config(cfg: Dict[str, Any]) -> None:
    """Raise ValueError with a clear message on a malformed configuration."""
    n = cfg["n_drones"]
    if not (2 <= n <= 12):
        raise ValueError(f"n_drones must be in [2, 12], got {n}")
    if cfg["controller"] not in ("leader_follower", "consensus"):
        raise ValueError(f"unknown controller {cfg['controller']!r}")
    if cfg["formation"] not in ("wedge", "line", "column"):
        raise ValueError(f"unknown formation {cfg['formation']!r}")
    if not cfg["mission"]["waypoints"]:
        raise ValueError("mission needs at least one waypoint")
    for f in cfg["faults"]:
        if f.get("type") not in FAULT_TYPES:
            raise ValueError(f"unknown fault type {f.get('type')!r}; valid: {FAULT_TYPES}")
        if "t" not in f:
            raise ValueError(f"fault {f} needs an onset time 't'")
        d = f.get("drone", "all")
        if d != "all":
            ids = d if isinstance(d, list) else [d]
            for i in ids:
                if not (0 <= int(i) < n):
                    raise ValueError(f"fault targets drone {i} but n_drones={n}")
