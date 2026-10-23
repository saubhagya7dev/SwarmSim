"""Formation geometry and mission-path helpers."""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import numpy as np


def formation_offsets(shape: str, m: int, spacing: float) -> List[Tuple[float, float]]:
    """Slot offsets (forward, left) in metres for m drones, rank 0 first.

    Rank 0 is the reference slot (leader position for leader-follower).
    """
    out: List[Tuple[float, float]] = [(0.0, 0.0)]
    for k in range(1, m):
        r = (k + 1) // 2                      # ring index 1,1,2,2,3,3,...
        side = 1.0 if k % 2 == 1 else -1.0    # alternate left / right
        if shape == "wedge":
            out.append((-0.8 * spacing * r, side * 0.8 * spacing * r))
        elif shape == "line":                 # abreast
            out.append((0.0, side * spacing * r))
        elif shape == "column":               # in trail
            out.append((-spacing * k, 0.0))
        else:
            raise ValueError(f"unknown formation {shape!r}")
    return out[:m]


def slot_offset(shape: str, rank: int, m: int, spacing: float) -> np.ndarray:
    """(forward, left) offset of a given rank in a formation of m drones."""
    return np.array(formation_offsets(shape, m, spacing)[rank], dtype=float)


def rot(heading: float, off: Sequence[float]) -> np.ndarray:
    """Rotate a (forward, left) offset into the world XY frame."""
    c, s = math.cos(heading), math.sin(heading)
    return np.array([off[0] * c - off[1] * s, off[0] * s + off[1] * c])


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def leg_heading(waypoints: Sequence[Sequence[float]], idx: int, start_xy: Sequence[float]) -> float:
    """Heading of mission leg ending at waypoint idx (clamped to last leg)."""
    idx = min(idx, len(waypoints) - 1)
    a = np.asarray(start_xy if idx == 0 else waypoints[idx - 1], dtype=float)
    b = np.asarray(waypoints[idx], dtype=float)
    d = b - a
    if np.hypot(d[0], d[1]) < 1e-9:
        return 0.0
    return math.atan2(d[1], d[0])


def min_nearest_distance(offsets: Sequence[Tuple[float, float]]) -> float:
    """Smallest pairwise distance inside a slot template (sanity checks)."""
    best = float("inf")
    for i in range(len(offsets)):
        for j in range(i + 1, len(offsets)):
            best = min(best, math.hypot(offsets[i][0] - offsets[j][0], offsets[i][1] - offsets[j][1]))
    return best
