"""End-to-end tests: whole simulated missions, checked against ground truth."""
import os
import re

import numpy as np
import pytest

from swarmsim.criteria import effective_rules, evaluate, load_criteria
from swarmsim.metrics import compute_metrics
from swarmsim.runner import DEFAULT_CRITERIA, DEFAULT_SCENARIOS, prepare_cfg
from swarmsim.simulation import run_simulation
from swarmsim.supervisor import FAILED, FAILSAFE_GPS, LANDED, LANDING

CRIT = load_criteria(DEFAULT_CRITERIA)
CONTROLLERS = ["leader_follower", "consensus"]


def scenario_path(prefix):
    for f in sorted(os.listdir(DEFAULT_SCENARIOS)):
        if f.startswith(prefix):
            return os.path.join(DEFAULT_SCENARIOS, f)
    raise FileNotFoundError(prefix)


def trial(prefix, controller, seed=1000, avoidance=None):
    cfg = prepare_cfg(scenario_path(prefix), controller, avoidance)
    res = run_simulation(cfg, seed=seed)
    m = compute_metrics(res, CRIT["evaluation"])
    ok, details = evaluate(m, effective_rules(CRIT, cfg))
    return res, m, ok, details


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_nominal_mission_passes_all_criteria(controller):
    res, m, ok, details = trial("01_", controller)
    assert ok, [d for d in details if not d["passed"]]
    assert m["mission_complete"] and m["survivors_at_end"] == 5
    assert m["min_separation_m"] > 4.0
    assert m["false_peer_loss_events"] == 0


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_same_seed_is_bit_for_bit_reproducible(controller):
    _, a, _, _ = trial("12_", controller, seed=4242)
    _, b, _, _ = trial("12_", controller, seed=4242)
    assert a == b


def test_different_seeds_give_different_runs():
    _, a, _, _ = trial("01_", "consensus", seed=1)
    _, b, _, _ = trial("01_", "consensus", seed=2)
    assert a["wind_steady_ms"] != b["wind_steady_ms"] or a["min_separation_m"] != b["min_separation_m"]


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_follower_crash_is_detected_and_survivors_stay_safe(controller):
    res, m, ok, _ = trial("07_", controller)
    tr = res.trace
    assert m["survivors_at_end"] == 4
    assert m["detection_time_s"] <= 4.0
    assert m["collision_events"] == 0 and m["min_separation_m"] > 2.0
    assert not tr.airborne[-1][3] or tr.pos[-1][3][2] <= 0.0 + 1e-6     # drone 3 reached the ground
    assert tr.mode[-1][3] == FAILED
    assert m["mission_complete"]


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_leader_loss_mission_continues(controller):
    res, m, ok, _ = trial("08_", controller)
    assert m["mission_complete"] and m["survivors_at_end"] == 4
    assert m["min_separation_m"] > 2.0


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_long_gps_loss_leads_to_controlled_landing(controller):
    res, m, ok, _ = trial("03_", controller)
    tr = res.trace
    modes = [e[4] for e in res.events if e[1] == "MODE" and e[2] == 2]
    assert any("FORMATION->FAILSAFE_GPS" in x for x in modes)
    assert any("FAILSAFE_GPS->LANDING" in x for x in modes)
    assert tr.mode[-1][2] == LANDED
    assert tr.pos[-1][2][2] == 0.0
    assert m["mission_complete"] and m["min_separation_m"] > 2.0


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_short_gps_loss_rejoins(controller):
    res, m, ok, _ = trial("02_", controller)
    assert m["survivors_at_end"] == 5
    assert not np.isnan(m["rejoin_time_s"]) and m["rejoin_time_s"] < 30.0


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_total_radio_blackout_is_collision_free_and_recovers(controller):
    res, m, ok, _ = trial("06_", controller)
    assert m["collision_events"] == 0 and m["min_separation_m"] > 2.0
    assert m["survivors_at_end"] == 5 and m["mission_complete"]
    assert any("FORMATION->HOLD" in e[4] for e in res.events if e[1] == "MODE")


@pytest.mark.parametrize("controller", CONTROLLERS)
def test_heartbeat_does_not_false_alarm_under_30pct_loss(controller):
    res, m, ok, _ = trial("10_", controller)
    assert m["false_peer_loss_events"] == 0
    assert m["comms_drop_rate"] > 0.25


def test_agents_never_read_ground_truth_position():
    """On-board code may only use estimates. Ground-truth `.pos` belongs to the simulator."""
    root = os.path.join(os.path.dirname(DEFAULT_SCENARIOS), "swarmsim")
    for fname in ("agent.py", "controllers.py", "supervisor.py"):
        src = open(os.path.join(root, fname), encoding="utf-8").read()
        assert not re.search(r"\b(?:d|drone|self\.drone)\.pos\b", src), fname
        assert not re.search(r"\bground_vel\b", src), fname


def test_metric_sanity_on_trace_shapes():
    res, m, _, _ = trial("01_", "consensus")
    tr = res.trace
    assert tr.pos.shape == (tr.steps, 5, 3) and len(tr.t) == tr.steps
    assert np.all(np.diff(tr.t) > 0)
    assert 0.0 <= m["comms_drop_rate"] <= 1.0
    assert m["duration_s"] == pytest.approx(tr.t[-1])
