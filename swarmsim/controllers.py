"""Two formation controllers with different failure characteristics.

Both use FIXED HOME SLOTS (slot = f(drone id)). A lost drone leaves a gap that is kept
open for it, so membership changes never reshuffle the remaining drones and a returning
drone flies back to its own place. The cost is that the formation is not "closed up"
after a loss (listed under future work in docs/DESIGN.md).

LeaderFollowerController  hierarchical: the most senior healthy drone leads (seniority =
                          earliest (re)entry into FORMATION, ties by id). Everyone else
                          tracks the leader's broadcast state plus slot differences.
                          A returning drone is junior, so leadership does not flip back.
ConsensusController       leaderless: each drone averages the formation-reference point
                          implied by every healthy peer (p_j - R*slot_j), flies the mission
                          along that shared reference and tracks its own slot.

Both return a desired GROUND velocity [vx, vy, vz]; the agent converts it to an
air-relative command with the wind estimate and applies the safety filter.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

from .comms import Message
from .formation import rot

Peers = Dict[int, Tuple[Message, float]]


class LeaderFollowerController:
    name = "leader_follower"

    @staticmethod
    def _leader(agent, peers: Peers) -> int:
        best = (agent.t_form, agent.id)
        for j, (m, _) in peers.items():
            key = (m.t_form, j)
            if key < best:
                best = key
        return best[1]

    def command(self, agent, t: float, dt: float, peers: Peers) -> np.ndarray:
        cfg = agent.cfg
        kp = cfg["control"]["kp"]
        d = agent.drone
        leader = self._leader(agent, peers)
        if leader != agent.leader:
            agent.log(t, "LEADER", leader, "")
            agent.leader = leader
        for m, _ in peers.values():                    # adopt shared mission progress
            if m.wp > agent.wp_idx:
                agent.wp_idx = m.wp
                if agent.wp_idx >= len(agent.wps):
                    agent.mission_done = True
        est_xy = d.est_pos[:2]
        agent.update_heading(dt)
        h = agent.heading
        v = np.zeros(3)
        if leader == agent.id:
            c = est_xy - rot(h, agent.slot)             # formation reference point
            agent.maybe_advance_waypoint(t, c)
            v[:2] = agent.mission_velocity(c, agent.wp_idx) + agent.slot_velocity()
        else:
            lm, _ = peers[leader]
            age = max(t - lm.t_sent, 0.0)
            lpos = np.array(lm.pos[:2]) + np.array(lm.vel[:2]) * age
            lvel = np.array(lm.vel[:2])
            c = lpos - rot(h, lm.slot)
            target = c + rot(h, agent.slot)
            v[:2] = kp * (target - est_xy) + lvel + agent.slot_velocity()
        v[2] = agent.altitude_rate()
        return v


class ConsensusController:
    name = "consensus"

    def command(self, agent, t: float, dt: float, peers: Peers) -> np.ndarray:
        cfg = agent.cfg
        kc = cfg["control"]["kp"]
        d = agent.drone
        agent.leader = None
        for m, _ in peers.values():
            if m.wp > agent.wp_idx:
                agent.wp_idx = m.wp
                if agent.wp_idx >= len(agent.wps):
                    agent.mission_done = True
        agent.update_heading(dt)
        h = agent.heading
        est_xy = d.est_pos[:2]
        acc = est_xy - rot(h, agent.slot)
        for m, _ in peers.values():
            age = max(t - m.t_sent, 0.0)
            pj = np.array(m.pos[:2]) + np.array(m.vel[:2]) * age
            acc = acc + (pj - rot(h, m.slot))
        c_est = acc / (1 + len(peers))
        agent.maybe_advance_waypoint(t, c_est)
        target = c_est + rot(h, agent.slot)
        v = np.zeros(3)
        v[:2] = (agent.mission_velocity(c_est, agent.wp_idx) + kc * (target - est_xy)
                 + agent.slot_velocity())
        v[2] = agent.altitude_rate()
        return v


CONTROLLERS = {
    "leader_follower": LeaderFollowerController,
    "consensus": ConsensusController,
}


def make_controller(name: str):
    try:
        return CONTROLLERS[name]()
    except KeyError:
        raise ValueError(f"unknown controller {name!r}; valid: {sorted(CONTROLLERS)}")
