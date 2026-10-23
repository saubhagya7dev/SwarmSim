"""The C++ failsafe monitor must behave exactly like the Python state machine.

Two checks: (1) replay supervisor inputs recorded from real simulated missions through the
compiled C++ and compare the mode on every tick; (2) the same on random adversarial inputs.
"""
import os
import random
import shutil
import subprocess

import pytest

from swarmsim.config import DEFAULTS
from swarmsim.runner import DEFAULT_SCENARIOS, prepare_cfg
from swarmsim.simulation import run_simulation
from swarmsim.supervisor import SupervisorFSM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "failsafe", "replay_main.cpp")

pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not available")


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("cpp") / "replay")
    cmd = ["g++", "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
           "-I", os.path.join(ROOT, "failsafe"), SRC, "-o", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def replay(binary, params, rows):
    head = " ".join(repr(float(params[k])) for k in
                    ("link_timeout", "link_recovery", "gps_timeout", "gps_recovery", "gps_land_after"))
    head += " " + repr(float(params["hb_timeout"]))
    body = "\n".join(f"{t!r} {la!r} {ga!r} {int(g)}" for (t, la, ga, g) in rows)
    r = subprocess.run([binary], input=head + "\n" + body + "\n", capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [int(x) for x in r.stdout.split()]


def python_modes(sup_cfg, hb, rows):
    f = SupervisorFSM(sup_cfg, hb)
    out = []
    for (t, la, ga, g) in rows:
        f.step(t, la, ga, bool(g))
        out.append(f.mode)
    return out


def params_of(cfg):
    p = dict(cfg["supervisor"])
    p["hb_timeout"] = cfg["comms"]["hb_timeout"]
    return p


@pytest.mark.parametrize("prefix", ["02_", "03_", "05_", "06_", "10_", "12_"])
def test_recorded_mission_traces_match(binary, prefix):
    path = [os.path.join(DEFAULT_SCENARIOS, f) for f in sorted(os.listdir(DEFAULT_SCENARIOS))
            if f.startswith(prefix)][0]
    cfg = prepare_cfg(path, "consensus", None)
    res = run_simulation(cfg, seed=1000, trace_fsm=True)
    checked = 0
    for tr in res.fsm_traces:
        rows = [(t, la, ga, g) for (t, la, ga, g, _m) in tr]
        recorded = [m for (*_x, m) in tr]
        if not rows:
            continue
        cpp = replay(binary, params_of(cfg), rows)
        assert cpp == recorded
        checked += len(rows)
    assert checked > 1000


def test_random_adversarial_inputs_match(binary):
    cfg = DEFAULTS
    rng = random.Random(12345)
    rows = []
    t = 0.0
    link_age = gps_age = 0.0
    ground = 0
    for _ in range(6000):
        t += 0.1
        # random walks with resets, so both ages cross every threshold many times
        link_age = 0.2 if rng.random() < 0.15 else link_age + 0.1 * rng.random() * 3
        gps_age = 0.1 if rng.random() < 0.10 else gps_age + 0.1 * rng.random() * 3
        if rng.random() < 0.003:
            ground = 1 - ground
        rows.append((t, link_age, gps_age, ground))
    cpp = replay(binary, params_of(cfg), rows)
    py = python_modes(cfg["supervisor"], cfg["comms"]["hb_timeout"], rows)
    assert cpp == py
    assert len(set(py)) >= 4                                # the input really exercised the machine
