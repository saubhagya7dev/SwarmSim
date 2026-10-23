# SwarmSim: Design Notes

## 1. Why a self-contained simulator

The first plan used PX4/ArduPilot SITL with Gazebo. With three days available, setup risk (Linux or WSL2,
toolchain, physics bring-up) was larger than the value it adds for this question. SwarmSim therefore
simulates the vehicle, sensors and radio itself in Python. The trade-off is physical fidelity; the
interfaces in `ICD.md` are kept narrow so a MAVLink bridge to a real flight stack can replace `drone.py`
later (section 7).

## 2. Architecture

`Simulation` steps at 10 Hz: faults update, wind evolves, estimators run, radio delivers, every `Agent`
computes a velocity command from its own estimates and received messages, radio broadcasts go out, and
the drones move. A ground-truth `Trace` is recorded each step. Metrics and criteria read only the trace.

Per drone, on board: **estimator** (GPS plus dead reckoning), **peer table**, **supervisor** (failsafe
state machine), **controller** (formation), **safety monitor** (avoidance and geofence), **broadcaster**.

## 3. Models and their parameters (all in `config.py`)

| Part | Model | Key values |
|---|---|---|
| Vehicle | 3-D point mass, first-order velocity loop | v_max 8 m/s, a_max 3 m/s^2, tau 0.5 s |
| Wind | steady (0 to 2 m/s) + common gust (Ornstein-Uhlenbeck, sigma 0.8, tau 5 s) + per-drone turbulence | |
| GPS | 5 Hz, position noise 0.6 m, velocity noise 0.1 m/s, innovation gate max(5 m, 4 sigma) | |
| Estimator | dead reckoning with drifting velocity bias; wind estimated from GPS minus air velocity, tau 4 s | bias walk 0.04 m/s per sqrt(s) |
| Radio | broadcast 5 Hz, range 80 m, latency 0.2 s + up to 0.1 s, loss 5% baseline | heartbeat timeout 2.4 s |

## 4. Control and safety logic

- **Fixed home slots.** Slot = function of drone id. A lost drone leaves its gap; a returning drone flies
  back to its own slot. Nobody is reshuffled.
- **Leader-follower.** The most senior healthy drone leads (seniority = earliest entry into FORMATION).
  A drone returning from a fault is junior, so leadership does not flip back. Followers track the
  leader's broadcast state extrapolated by its age, plus the slot offset difference.
- **Consensus.** Each drone averages the formation reference point implied by every healthy peer and flies
  the mission along that shared point. No leader to lose.
- **Turn feed-forward.** The heading is low-pass filtered (7 s) and slot velocity caused by the turn is fed
  forward, which limits how fast outer slots swing around a corner.
- **Safety monitor.** Every drone repels itself from every peer it has any record of, including silent
  ones (their keep-out radius grows with silence and with the staleness of their GPS), adds vertical
  deconfliction (lower id climbs, higher id descends), and is pushed back from the geofence edge.
- **Supervisor.** See `ICD.md` section 4. In GPS failsafe a drone descends 6 m to a separation layer using
  barometric altitude, which does not depend on GPS.

## 5. Change history: what the test bench found, and what changed

Small test runs (10 trials, seeds 1000 to 1009) were used while developing. Each change below was made
because a run exposed a specific problem, not by searching for a passing number. These seeds overlap with
the first 10 campaign seeds, which is a mild source of optimism in the campaign.

| # | Observation | Cause | Change |
|---|---|---|---|
| 1 | Nominal formation error p95 about 4.5 m | outer slots swung too fast in turns | heading filter 3 s to 7 s; slot-velocity feed-forward. p95 fell to about 1.5 to 1.9 m |
| 2 | Short GPS dropout and compound scenarios passed 0 to 2 of 10; separation fell to about 0.5 to 1 m | slots were reassigned by rank when membership changed, so a rejoining drone crossed others' paths | fixed home slots; seniority-based leader |
| 3 | Remaining GPS-dropout near-misses (down to 0.5 m) | a drone on dead reckoning drifted up to about 14 m while peers avoided its last broadcast position | broadcast GPS age and widen peers' keep-out; descend to a separation layer; faster wind estimator (tau 10 s to 4 s) |
| 4 | 30% packet-loss scenario raised false peer-loss alarms in 6 of 10 trials | a 1.6 s timeout is 8 packets; 0.3^8 times about 500 windows times 20 links is about 0.65 events per trial | timeout 2.4 s (12 packets, about 0.005 per trial); detection stays near 2.7 s against the 4 s limit |

## 6. Limitations

See `REPORT.pdf` section 8. In short: point-mass physics, statistical GPS and radio, no real flight stack,
single faults, fixed slots leave a gap after a loss, and results are simulation evidence only.

## 7. Future work

1. MAVLink bridge to PX4 SITL for one drone, then a swarm, replacing `drone.py` while keeping the agent code.
2. Close ranks after a loss (re-slotting) with a safe hand-over, now that the bench can measure the risk.
3. Run `heartbeat_monitor.h` on a microcontroller with a serial replay of recorded traces.
4. Correlated and adversarial network faults; larger swarms; battery-driven failures.

## 8. Open issues found by the campaign (analysis of 22 Oct 2026, seeds 1000 to 1029)

These are hand-written analysis notes. They are not regenerated when the campaign is rerun.

1. **Leader-follower fails in strong wind (scenario 11): 19 of 30 trials pass, steady error p95 8.2 m against a 4 m limit.**
   Cause confirmed by a diagnostic: airspeed headroom. A 3 to 5 m/s wind against a 4 m/s cruise speed needs
   about 7 to 9 m/s of air speed on upwind legs, at or above the 8 m/s vehicle limit before gusts are added.
   Rerunning the same 30 seeds with `v_max` raised to 12 m/s gives 30 of 30 for both controllers (leader-follower
   median steady error falls from 2.4 m to 1.7 m). Consensus passes 29 of 30 at 8 m/s, so the two controllers
   respond differently to the same saturation; why was not investigated.
   *Not fixed.* Slowing the mission to keep headroom would push the mission past its 200 s limit in strong wind,
   which trades a formation failure for a mission-time failure. Recommendation: make an airspeed margin a
   stated requirement, and schedule cruise speed from the estimated headwind with an explicit mission-time budget.
2. **A drone landing without GPS can drift outside the geofence (scenario 04, seed 1024, both controllers).**
   After about 27 s of dead reckoning its position estimate was off by about 52 m, and its true position was
   outside the fence for 3 to 4 s at 3 to 4 m altitude. 1 trial in 30 per controller. *Not fixed.* Options: a
   faster descent, a drift-aware hold, or a larger geofence margin for a drone known to be without GPS.
3. **One close approach between two healthy drones (scenario 12, leader-follower, seed 1022): 1.24 m at 71.9 s,**
   about 10 s after the GPS dropout ended and with a crashed drone on the ground. This is the only collision in
   720 trials. Cause not isolated. The safety layer was active and still allowed 1.24 m, so a stronger repulsion
   near the formation slot spacing is worth testing.
4. **The safety layer matters in specific cases, not everywhere.** With it off, the worst case in the single
   radio-loss scenario falls from 6.0 m to 1.0 m (one collision in 40 trials). In most other scenarios the worst
   case changes by less than 0.5 m, and total passes are identical (469 of 480 either way). It is a backstop for a
   silent neighbour, not a general-purpose formation aid.
