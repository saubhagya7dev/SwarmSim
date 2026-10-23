# SwarmSim: Test Plan

## 1. Objective

Answer one question with repeatable evidence: **under which injected faults does a 5-drone swarm stay
safe and finish its mission, and where does it fail?** Two formation controllers face identical tests so
the comparison is fair. Everything is simulation; no result is a statement about a physical system.

## 2. Test items and approach

- Items under test: leader-follower controller, consensus controller, the per-drone failsafe supervisor
  and the runtime safety monitor.
- Each scenario file in `scenarios/` is run for each controller with 30 seeded trials
  (seeds 1000 to 1029). The seed fixes wind, sensor noise, packet loss, initial offsets and fault-onset jitter.
- The acceptance criteria in `criteria/criteria.yaml` were written **before** the campaign and are not
  edited to fit results.
- An ablation reruns every scenario with the avoidance layer switched off on 20 of the same seeds, to show
  what that layer contributes.

## 3. Scenarios

| ID | Fault injected | What the swarm is expected to do |
|---|---|---|
| 01 nominal | none | complete the mission with a tight formation; no false alarms |
| 02 gps dropout short | follower GPS lost 6 s | drop out, hover, rejoin its own slot |
| 03 gps dropout long | follower GPS lost 20 s | hover, then land after 10 s; others continue |
| 04 gps dropout leader | leader GPS lost, permanent | land; leadership passes on; mission continues |
| 05 comms loss single | one radio dead 10 s | hold; others keep clear of it; rejoin |
| 06 comms blackout all | every radio dead 6 s | everyone holds; no collision; formation re-forms |
| 07 drone failure follower | motor failure, follower | peers detect it and continue with four |
| 08 drone failure leader | motor failure, leader | re-election (or none needed); continue with four |
| 09 gps degraded all | 4x GPS noise and 3% outliers, 25 s | stay safe on degraded navigation |
| 10 packet loss 30 | 30% loss on every link, whole mission | no false peer-loss alarms; formation holds |
| 11 high wind | steady 3 to 5 m/s, heavy gusts | wind estimator keeps the formation tight |
| 12 compound | 15% loss, follower crash, then another GPS dropout | survive both events |

## 4. Metrics (computed from ground truth)

| Metric | Definition |
|---|---|
| `min_separation_m` | smallest 3-D distance between any two airborne drones, whole trial |
| `time_below_safe_sep_s` | total time that smallest distance was under 4 m |
| `collision_events` | number of separate intervals under 2 m |
| `formation_error_*` | RMS shape error of the healthy participants, each against its own assigned slot, after a 10 s warm-up |
| `steady_error_p95_m` | 95th percentile of the shape error in steady state: all participants agree on membership and nothing changed for 6 s |
| `detection_time_s` | fault onset to the first healthy peer dropping the faulty drone (worst over discrete faults) |
| `recovery_time_s` | fault onset to: agreed membership and shape error under 2.5 m, held for 4 s (worst over discrete faults) |
| `rejoin_time_s` | end of a finite GPS or radio fault to the drone being a participant again and formed up (only when `expect_rejoin`) |
| `mission_complete` | the formation reference point reached the last waypoint with at least 2 participants |
| `survivors_at_end` | drones still in FORMATION and airborne at the end |
| `geofence_breach` | any airborne drone outside the geofence at any step |
| `false_peer_loss_events` | a peer-lost event with no fault, mode change or radio outage involving either drone |

## 5. Pass rule and statistics

A trial passes when every applicable criterion passes (see the table printed in `REPORT.pdf`, section 7).
A scenario and controller is **accepted** when at least 90% of its trials pass. Pass rates are reported
with Wilson 95% intervals. Two controllers are called different on a scenario only when their intervals
do not overlap. A 30-of-30 result has a lower bound of about 89%, so "accepted" means "no evidence of failure
at this sample size", not "proven safe".

## 6. Automated test suite (`python -m pytest tests -q`)

| File | What it checks |
|---|---|
| `test_units.py` | formation geometry, config validation, all 12 scenarios load, criteria engine (including NaN fails), Wilson and percentile helpers, radio range, latency and loss, fault apply and clear, seeded jitter |
| `test_supervisor.py` | every supervisor transition, recovery streaks, no flapping on an intermittent link, latched landing, terminal modes |
| `test_system.py` | whole missions: nominal passes, same seed gives identical results, crash and leader-loss handling, GPS-loss landing, blackout safety, no false alarms at 30% loss, no ground-truth reads |
| `test_cpp_conformance.py` | compiles the C++ monitor with `-Wall -Wextra -Werror -pedantic`, replays inputs recorded from six missions and 6000 random adversarial ticks, requires identical modes on every tick |

## 7. Exit criteria for the project

1. Test suite green.
2. Campaign completed with all 720 trials plus ablation, results archived in `results/`.
3. Every combination that is not accepted is explained in the report, with its failed criteria listed.
4. Report, dashboard and docs regenerate from a clean checkout with the commands in `README.md`.

## 8. Known weaknesses of this test design

- Faults are injected one at a time except for one compound case.
- Early tuning runs (10 trials each, seeds 1000 to 1009) overlap with the first 10 campaign seeds, so the
  campaign is not fully independent of tuning. `DESIGN.md` section 5 lists every parameter changed that way.
- Criteria thresholds are engineering judgements for a generic small swarm, not derived from a standard.
