"""The failsafe state machine, driven directly with the four numbers it depends on."""
import pytest

from swarmsim.config import DEFAULTS
from swarmsim.supervisor import (FAILED, FAILSAFE_GPS, FORMATION, HOLD, LANDED, LANDING,
                                 SupervisorFSM)

S = DEFAULTS["supervisor"]
HB = DEFAULTS["comms"]["hb_timeout"]


def fsm():
    return SupervisorFSM(S, HB)


def run(f, t0, t1, link_age, gps_age, ground=False, dt=0.1):
    t = t0
    while t < t1:
        f.step(t, link_age(t) if callable(link_age) else link_age,
               gps_age(t) if callable(gps_age) else gps_age, ground)
        t += dt
    return t


def test_nominal_stays_in_formation():
    f = fsm()
    run(f, 0.0, 30.0, 0.2, 0.1)
    assert f.mode == FORMATION


def test_link_loss_goes_to_hold_and_recovers_after_streak():
    f = fsm()
    # silence starts at t=5: link age grows with time
    run(f, 0.0, 5.0, 0.2, 0.1)
    run(f, 5.0, 12.0, lambda t: t - 5.0 + 0.2, 0.1)
    assert f.mode == HOLD
    # messages return: needs `link_recovery` s of continuous reception
    run(f, 12.0, 12.5, 0.2, 0.1)
    assert f.mode == HOLD
    run(f, 12.5, 14.0, 0.2, 0.1)
    assert f.mode == FORMATION


def test_hold_does_not_flap_on_intermittent_link():
    f = fsm()
    f.mode = HOLD
    # alternate fresh / stale every 0.5 s: never a continuous 1 s of reception
    t = 0.0
    while t < 10.0:
        age = 0.2 if int(t / 0.5) % 2 == 0 else HB + 0.5
        f.step(t, age, 0.1, False)
        t += 0.1
    assert f.mode == HOLD


def test_gps_loss_goes_to_failsafe_then_lands_and_latches():
    f = fsm()
    run(f, 0.0, 5.0, 0.2, 0.1)
    t = run(f, 5.0, 8.0, 0.2, lambda t: t - 5.0 + 0.2)          # GPS silent since 5.0
    assert f.mode == FAILSAFE_GPS
    t = run(f, 8.0, 20.0, 0.2, lambda t: t - 5.0 + 0.2)
    assert f.mode == LANDING
    # GPS returns: landing is latched, never re-arms mid-descent
    run(f, 20.0, 25.0, 0.2, 0.1)
    assert f.mode == LANDING
    f.step(25.0, 0.2, 0.1, True)
    assert f.mode == LANDED


def test_short_gps_loss_recovers():
    f = fsm()
    run(f, 0.0, 5.0, 0.2, 0.1)
    run(f, 5.0, 9.0, 0.2, lambda t: t - 5.0 + 0.2)
    assert f.mode == FAILSAFE_GPS
    run(f, 9.0, 9.5, 0.2, 0.1)
    assert f.mode == FAILSAFE_GPS                               # needs gps_recovery seconds of fixes
    run(f, 9.5, 12.0, 0.2, 0.1)
    assert f.mode == FORMATION


def test_gps_failsafe_takes_priority_over_hold_and_both_clear():
    f = fsm()
    run(f, 0.0, 5.0, 0.2, 0.1)
    run(f, 5.0, 8.0, lambda t: t - 5.0 + 0.2, lambda t: t - 5.0 + 0.2)   # both lost
    assert f.mode == FAILSAFE_GPS
    run(f, 8.0, 12.0, 0.2, 0.1)
    assert f.mode == FORMATION


def test_failed_and_landed_are_terminal():
    f = fsm()
    f.force_failed()
    assert f.mode == FAILED
    assert run(f, 0.0, 10.0, 0.2, 0.1) and f.mode == FAILED
    g = fsm()
    g.mode = LANDING
    g.step(0.0, 0.2, 0.1, True)
    assert g.mode == LANDED
    run(g, 0.1, 10.0, 99.0, 99.0)
    assert g.mode == LANDED


def test_transition_is_reported_once():
    f = fsm()
    out = []
    for k in range(80):
        r = f.step(k * 0.1, 0.2 if k < 10 else 0.2 + (k - 10) * 0.1, 0.1, False)
        if r:
            out.append(r)
    assert out == [(FORMATION, HOLD)]
