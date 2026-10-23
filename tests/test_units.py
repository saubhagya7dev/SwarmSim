"""Unit tests for pure helpers: geometry, config, criteria, statistics, radio, faults."""
import math

import numpy as np
import pytest

from swarmsim.comms import CommsNetwork, Message
from swarmsim.config import DEFAULTS, deep_merge, load_scenario, validate_config
from swarmsim.criteria import effective_rules, evaluate, load_criteria
from swarmsim.faults import FaultInjector
from swarmsim.formation import formation_offsets, min_nearest_distance, rot, wrap_angle
from swarmsim.metrics import _good_window
from swarmsim.runner import DEFAULT_CRITERIA, list_scenarios, percentile, wilson


# ------------------------------------------------------------------ formation
@pytest.mark.parametrize("shape", ["wedge", "line", "column"])
@pytest.mark.parametrize("m", [2, 3, 5, 8, 12])
def test_formation_slots_are_separated(shape, m):
    offs = formation_offsets(shape, m, 10.0)
    assert len(offs) == m
    assert offs[0] == (0.0, 0.0)
    assert min_nearest_distance(offs) >= 10.0 * 0.8 * math.sqrt(2) - 1e-9 or shape != "wedge"
    assert min_nearest_distance(offs) >= 8.0 - 1e-9


def test_rot_is_a_rotation():
    v = rot(math.pi / 2, (1.0, 0.0))
    assert np.allclose(v, [0.0, 1.0], atol=1e-12)
    assert np.isclose(np.linalg.norm(rot(1.234, (3.0, 4.0))), 5.0)


def test_wrap_angle():
    assert math.isclose(wrap_angle(3 * math.pi), math.pi, abs_tol=1e-9) or \
        math.isclose(wrap_angle(3 * math.pi), -math.pi, abs_tol=1e-9)
    assert math.isclose(wrap_angle(0.5), 0.5)


# --------------------------------------------------------------------- config
def test_deep_merge_does_not_mutate():
    base = {"a": {"b": 1, "c": 2}}
    out = deep_merge(base, {"a": {"b": 9}})
    assert out["a"] == {"b": 9, "c": 2}
    assert base["a"]["b"] == 1


def test_all_shipped_scenarios_load_and_validate():
    paths = list_scenarios()
    assert len(paths) == 12
    for p in paths:
        cfg = load_scenario(p)
        assert cfg["name"] and cfg["n_drones"] >= 2


def test_validation_rejects_bad_configs():
    good = deep_merge(DEFAULTS, {})
    validate_config(good)
    with pytest.raises(ValueError):
        validate_config(deep_merge(good, {"n_drones": 1}))
    with pytest.raises(ValueError):
        validate_config(deep_merge(good, {"controller": "nope"}))
    with pytest.raises(ValueError):
        validate_config(deep_merge(good, {"faults": [{"type": "alien_abduction", "t": 1.0}]}))
    with pytest.raises(ValueError):
        validate_config(deep_merge(good, {"faults": [{"type": "gps_dropout", "t": 1.0, "drone": 99}]}))
    with pytest.raises(ValueError):
        validate_config(deep_merge(good, {"faults": [{"type": "gps_dropout", "drone": 1}]}))


# ------------------------------------------------------------------- criteria
def test_criteria_file_loads():
    c = load_criteria(DEFAULT_CRITERIA)
    assert 0.0 < c["required_pass_rate"] <= 1.0
    assert "min_separation_m" in c["defaults"]


def test_evaluate_min_max_equals_and_missing():
    rules = {"a": {"min": 2.0}, "b": {"max": 1.0}, "c": {"equals": True}, "d": {"max": 5.0}}
    ok, det = evaluate({"a": 2.0, "b": 0.5, "c": True, "d": 4.0}, rules)
    assert ok and all(d["passed"] for d in det)
    ok, det = evaluate({"a": 1.99, "b": 0.5, "c": True, "d": 4.0}, rules)
    assert not ok and [d["criterion"] for d in det if not d["passed"]] == ["a"]
    ok, det = evaluate({"a": 3, "b": 2.0, "c": False, "d": float("nan")}, rules)
    failed = {d["criterion"] for d in det if not d["passed"]}
    assert failed == {"b", "c", "d"}                     # NaN = no data = fail, never a silent pass
    ok, det = evaluate({"a": 3, "b": 0.1, "c": True}, rules)    # missing key also fails
    assert not ok


def test_effective_rules_survivors_follow_allowed_losses():
    crit = load_criteria(DEFAULT_CRITERIA)
    cfg = deep_merge(DEFAULTS, {})
    cfg["allowed_losses"] = 1
    cfg["criteria"] = {"detection_time_s": {"max": 4.0}}
    rules = effective_rules(crit, cfg)
    assert rules["survivors_at_end"] == {"min": cfg["n_drones"] - 1}
    assert rules["detection_time_s"] == {"max": 4.0}
    assert "min_separation_m" in rules


def test_bad_rule_shape_is_rejected():
    crit = load_criteria(DEFAULT_CRITERIA)
    cfg = deep_merge(DEFAULTS, {})
    cfg["criteria"] = {"foo": {"bigger_than": 3}}
    with pytest.raises(ValueError):
        effective_rules(crit, cfg)


# ----------------------------------------------------------------- statistics
def test_wilson_interval_sanity():
    lo, hi = wilson(30, 30)
    assert hi == pytest.approx(1.0) and 0.88 < lo < 0.9
    lo, hi = wilson(0, 30)
    assert lo == 0.0 and 0.1 < hi < 0.12
    lo, hi = wilson(15, 30)
    assert lo < 0.5 < hi
    assert wilson(0, 0) == (0.0, 0.0)


def test_percentile_handles_nan_and_inf():
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert math.isnan(percentile([float("nan")], 50))
    assert percentile([1.0, float("nan"), 3.0], 50) == pytest.approx(2.0)
    assert percentile([1.0, float("inf")], 95) == float("inf")


def test_good_window():
    ok = np.array([0, 1, 1, 1, 0, 1, 1, 1, 1], dtype=bool)
    gw = _good_window(ok, 3)
    assert gw.tolist() == [False, True, False, False, False, True, True, False, False]
    assert not _good_window(ok, 20).any()


# ---------------------------------------------------------------------- radio
def _msg(src):
    return Message(src=src, t_sent=0.0, pos=(0, 0, 0), vel=(0, 0, 0), wp=0, slot=(0, 0),
                   healthy=True, mode=0, battery=100.0)


def test_comms_range_loss_and_outage():
    cfg = deep_merge(DEFAULTS, {"comms": {"loss_prob": 0.0, "range": 50.0}})
    net = CommsNetwork(3, cfg, np.random.default_rng(0))
    pos = np.array([[0, 0, 0], [10, 0, 0], [200, 0, 0]], dtype=float)
    net.broadcast(0.0, _msg(0), pos)
    got = net.deliver(5.0)
    assert [j for j, _ in got] == [1]                    # drone 2 is out of range
    net.tx_ok[0] = False
    net.broadcast(1.0, _msg(0), pos)
    assert net.deliver(9.0) == []                        # dead transmitter sends nothing
    net.tx_ok[0] = True
    net.rx_ok[1] = False
    net.broadcast(2.0, _msg(0), pos)
    assert net.deliver(9.0) == []                        # dead receiver hears nothing
    net.rx_ok[1] = True
    net.extra_loss = 1.0
    net.broadcast(3.0, _msg(0), pos)
    assert net.deliver(9.0) == []


def test_comms_latency_is_respected():
    cfg = deep_merge(DEFAULTS, {"comms": {"loss_prob": 0.0, "latency": 0.3, "latency_jitter": 0.0}})
    net = CommsNetwork(2, cfg, np.random.default_rng(0))
    net.broadcast(0.0, _msg(0), np.zeros((2, 3)))
    assert net.deliver(0.2) == []
    assert len(net.deliver(0.31)) == 1


# --------------------------------------------------------------------- faults
class _Stub:
    class _D:
        gps_available = True
        gps_sigma_scale = 1.0
        gps_outlier_prob = 0.0
        failed = False

    class _A:
        class fsm:
            forced = False

            @classmethod
            def force_failed(cls):
                cls.forced = True

    def __init__(self, n, cfg):
        self.drones = [self._D() for _ in range(n)]
        self.agents = [self._A() for _ in range(n)]
        self.comms = CommsNetwork(n, cfg, np.random.default_rng(0))


def test_fault_injector_applies_and_clears():
    faults = [
        {"type": "gps_dropout", "drone": 1, "t": 5.0, "duration": 2.0},
        {"type": "comms_loss", "drone": [0, 2], "t": 10.0, "duration": 3.0},
        {"type": "drone_failure", "drone": 3, "t": 20.0},
        {"type": "packet_loss", "t": 0.0, "prob": 0.4, "duration": 8.0},
    ]
    cfg = deep_merge(DEFAULTS, {"n_drones": 4, "faults": faults})
    validate_config(cfg)
    inj = FaultInjector(cfg, np.random.default_rng(0))
    sim = _Stub(4, cfg)
    inj.update(0.0, sim)
    assert sim.comms.extra_loss == 0.4 and sim.drones[1].gps_available
    inj.update(5.0, sim)
    assert not sim.drones[1].gps_available
    inj.update(7.0, sim)
    assert sim.drones[1].gps_available
    inj.update(10.0, sim)
    assert not sim.comms.tx_ok[0] and not sim.comms.rx_ok[2] and sim.comms.tx_ok[1]
    inj.update(13.0, sim)
    assert all(sim.comms.tx_ok) and all(sim.comms.rx_ok)
    inj.update(8.0, sim)
    inj.update(21.0, sim)
    assert sim.drones[3].failed and sim.agents[3].fsm.forced
    assert sim.comms.extra_loss == 0.0


def test_fault_time_jitter_is_seeded():
    cfg = deep_merge(DEFAULTS, {"faults": [{"type": "gps_dropout", "drone": 1, "t": 40.0, "t_jitter": 5.0}]})
    a = FaultInjector(cfg, np.random.default_rng(7)).records[0].t_on
    b = FaultInjector(cfg, np.random.default_rng(7)).records[0].t_on
    c = FaultInjector(cfg, np.random.default_rng(8)).records[0].t_on
    assert a == b and a != c and 35.0 <= a <= 45.0
