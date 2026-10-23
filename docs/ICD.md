# SwarmSim: Interface Control Document

This document fixes every interface in the system so that the parts can be developed, replaced and
tested independently. Units: metres, seconds, m/s, percent. Local frame: x east, y north, z up.

## 1. System context

```
 scenario.yaml ─┐                                   ┌─> trials.csv, summary.json
 criteria.yaml ─┼─> Runner ─> Simulation ─> Trace ──┼─> Metrics ─> Criteria verdict
 config defaults┘            │  drones, radio,      └─> Report (PDF, MD) / Dashboard (HTML)
                             │  faults, agents
                             └─> failsafe supervisor  <──>  failsafe/heartbeat_monitor.h
```

## 2. Module interfaces (Python)

| Module | Provides | Consumes |
|---|---|---|
| `config` | `load_scenario(path) -> cfg`, `validate_config(cfg)` | YAML |
| `drone.Drone` | `step_dynamics(dt, v_cmd_air, wind)`, `step_estimator(t, dt)`; fields `pos` (truth), `est_pos`, `est_vel`, `est_wind`, `last_gps_t`, `last_accept_t`, `battery` | velocity command |
| `comms.CommsNetwork` | `broadcast(t, msg, true_pos)`, `deliver(t) -> [(dst, msg)]`; fault hooks `tx_ok[]`, `rx_ok[]`, `extra_loss` | `Message` |
| `agent.Agent` | `receive(t, msg)`, `step(t, dt) -> v_cmd_air`; `outbox` (message to send this tick) | estimates, messages |
| `supervisor.SupervisorFSM` | `step(t, link_age, gps_age, on_ground) -> transition or None` | four numbers |
| `controllers.*Controller` | `command(agent, t, dt, peers) -> v_ground` | peer table |
| `faults.FaultInjector` | `update(t, sim)` applies and clears faults | `cfg["faults"]` |
| `simulation.Simulation` | `run() -> SimResult` (trace, events, fault records) | `cfg`, seed |
| `metrics` | `compute_metrics(result, evaluation_cfg) -> dict` | `SimResult` |
| `criteria` | `evaluate(metrics, rules) -> (passed, details)` | rules |

Information boundary: `Agent` and the controllers may read estimates (`est_*`), the on-ground flag,
the GPS timestamps and received messages. They must not read `Drone.pos` or `Drone.ground_vel`.
`tests/test_system.py::test_agents_never_read_ground_truth_position` enforces this.

## 3. Radio message (broadcast, 5 Hz per drone)

| Field | Type | Meaning |
|---|---|---|
| `src` | int | sender id |
| `t_sent` | float s | send time (shared simulation clock) |
| `pos` | 3 x float m | sender's estimated position |
| `vel` | 3 x float m/s | sender's estimated ground velocity |
| `wp` | int | index of the sender's current mission waypoint |
| `slot` | 2 x float m | sender's formation slot (forward, left) |
| `healthy` | bool | true only in FORMATION mode |
| `mode` | int | supervisor mode, see section 4 |
| `battery` | float % | remaining charge |
| `t_form` | float s | time the sender (re)entered FORMATION; older means more senior (leader election) |
| `gps_age` | float s | time since the sender last accepted a GPS fix; receivers widen their keep-out zone with it |

Channel model: delivery only within `comms.range` (80 m), latency `0.2 s` plus up to `0.1 s` jitter,
baseline loss `5 %`, plus fault-injected loss. A peer is considered lost after `hb_timeout` (2.4 s)
without a message; the timeout is derived from the loss rate (see `DESIGN.md`).

## 4. Supervisor modes and transitions

| Mode | Id | Entered when | Left when |
|---|---|---|---|
| FORMATION | 0 | nominal | link silent > 3 s (to HOLD); GPS age > 1.5 s (to FAILSAFE_GPS) |
| HOLD | 1 | no peer heard for 3 s | 1 s of continuous reception (to FORMATION) |
| FAILSAFE_GPS | 2 | no accepted GPS fix for 1.5 s | 2 s of fixes (to FORMATION); 10 s in this mode (to LANDING) |
| LANDING | 3 | 10 s in FAILSAFE_GPS | on ground (to LANDED); latched, never aborted |
| LANDED | 4 | touched down | terminal |
| FAILED | 5 | set from outside (motor failure) | terminal |

GPS loss takes priority over link loss. The same logic is implemented in `failsafe/heartbeat_monitor.h`.

## 5. Scenario file schema (`scenarios/*.yaml`)

```yaml
name: 05_comms_loss_single          # unique id, defaults to the file name
description: free text              # shown in report and dashboard
tags: [comms, recovery]             # optional
allowed_losses: 0                   # drones that may be lost without failing the survivors criterion
expect_rejoin: false                # true: rejoin_time_s is evaluated
n_drones: 5                         # any key of config.DEFAULTS can be overridden, nested keys merge
env: {wind_steady_max: 5.0}
faults:                             # list, any number
  - type: gps_dropout               # gps_dropout | gps_noise | comms_loss | drone_failure | packet_loss
    drone: 3                        # int, list of ints, or "all" (default "all")
    t: 40.0                         # onset [s]
    t_jitter: 5.0                   # optional: onset drawn uniformly in t +/- jitter, per seed
    duration: 10.0                  # optional: omit for a permanent fault
    # fault-specific: gps_noise: sigma_scale, outlier_prob;  packet_loss: prob
criteria:                           # optional additions or overrides of criteria.yaml defaults
  recovery_time_s: {max: 12.0}
```

## 6. Criteria file schema (`criteria/criteria.yaml`)

`defaults` holds one rule per metric: `{min: x}`, `{max: x}` or `{equals: v}`; `evaluation` holds the
thresholds used when computing metrics; `required_pass_rate` is the share of trials that must pass for a
scenario and controller to be accepted. A metric that is missing or NaN fails its rule.

## 7. Result files

`results/trials.csv`: one row per trial. Keys: `scenario, controller, seed, avoidance, passed,
failed_criteria` followed by every metric in `TEST_PLAN.md` section 4.
`results/summary.json`: one record per scenario and controller with pass counts, Wilson interval,
verdict, percentiles and a `fail_reasons` histogram.

## 8. Command line

```
python -m swarmsim one <scenario-prefix> <controller> [--seed N] [--events]
python -m swarmsim run [--trials 30] [--workers N] [--ablate --ablate-trials 20] [--out results]
python -m swarmsim report
python -m swarmsim dashboard
```

## 9. C++ replay interface (`failsafe/replay_main.cpp`)

stdin line 1: `link_timeout link_recovery gps_timeout gps_recovery gps_land_after hb_timeout`;
then one line per tick `t link_age gps_age on_ground`. stdout: one mode id per tick.
