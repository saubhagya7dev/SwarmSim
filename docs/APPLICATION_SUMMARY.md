# SwarmSim: one-page project summary

**Applicant project for the swarm-drone research internship (Indian Army Internship Programme, AICTE portal).**
Simulation only. No hardware, payload, weapons or deployment content.

## The problem

In a drone swarm one fault can cascade: a lost GPS fix or radio link can pull the formation apart or cause
near-collisions. Real flight tests are costly and risky, and ad hoc testing has no agreed meaning of
"acceptable" and no repeatable evidence. SwarmSim is a test bench that answers one question with evidence:
**under which faults does a small swarm stay safe and finish its mission, and where does it fail?**

## What I built

- A Python simulator of a 5-drone swarm: vehicle dynamics, wind and gusts, GPS with dead-reckoning fallback, and a delayed, lossy radio.
- Two formation controllers, **leader-follower** and leaderless **consensus**, tested identically.
- A per-drone **failsafe state machine** (hold, GPS failsafe, controlled landing) and a runtime **safety monitor**
  (separation keeping, vertical deconfliction, geofence). The state machine is also ported to **embedded-style C++**
  and checked tick-for-tick against the Python version.
- A **fault injector** and 12 scenarios: GPS dropout (short, long, leader), radio loss (one drone, all drones),
  motor failure (follower, leader), degraded GPS, 30% packet loss, strong wind, and a compound case.
- **Acceptance criteria written before the experiments**, in a config file, and a runner that executes 30 seeded
  trials per case in parallel, scores them from ground truth, and reports pass rates with confidence intervals.
- A test report (PDF), a browser replay dashboard, 65 automated tests, and requirements, interface, test-plan and design documents.

## How it maps to the posting

| Posting | In SwarmSim |
|---|---|
| UAV engineering, navigation | dynamics, estimator, waypoint mission, GPS-loss handling |
| Software and system integration | simulator, agents, radio, faults, metrics joined through a written interface document |
| System reliability | fault injection, failsafe logic, detection and recovery metrics |
| Simulation-based, non-operational testing | the whole project; stated as a requirement |
| Reviewing interface requirements | `docs/ICD.md` |
| Comparing results against agreed criteria | criteria file fixed first; two controllers compared with intervals |
| Technical documentation, evidence-based reporting | `docs/`, `results/REPORT.pdf` |
| Python, C++, control systems, embedded | Python package; C++ monitor with no heap or STL, sized for a microcontroller |

## Results (720 trials plus 480 ablation trials)

- **23 of 24** scenario and controller combinations met the 90% rule. Consensus passed 357 of 360 trials, leader-follower 343 of 360.
- **One collision** (under 2 m) in 720 trials. No false peer-loss alarms, including at 30% packet loss.
- **A real failure found and explained:** leader-follower passes only 19 of 30 in strong wind. The cause is airspeed
  headroom (3 to 5 m/s wind against a 4 m/s cruise speed and an 8 m/s limit). Raising the limit to 12 m/s gives 30 of 30.
- **The safety layer is a backstop, not a cure-all:** with it off, the worst separation in the single radio-loss case falls from 6.0 m to 1.0 m; in most other scenarios it changes almost nothing.

## What I learned

Early test runs showed drones crossing paths when one rejoined after a fault, which led to fixed formation slots.
A 30% packet-loss run showed false "peer lost" alarms, and working out the odds (0.3 to the power 8, over many
links and windows, is about 0.65 per trial) led to a longer heartbeat timeout. Every parameter changed after early
runs is listed in `docs/DESIGN.md`, including that those runs shared seeds with the first 10 campaign trials.

## Limits I state up front

Point-mass physics, statistical GPS and radio, no real flight stack, one fault at a time, results are simulation
evidence rather than guarantees. Next steps: a MAVLink bridge to PX4 SITL, closing ranks after a loss, running the
C++ monitor on a real microcontroller.

## Run it

```
pip install -r requirements.txt
python -m pytest tests -q
python -m swarmsim one 07 consensus --events
open results/dashboard.html        # replay every scenario in a browser
```
