# SwarmSim: Requirements

Scope: a **simulation-only** test bench that represents, monitors, stresses and assesses a small UAV
swarm. It contains no flight hardware code, no payload, no weapons and no deployment logic.

Verification methods: **T** = automated test (`tests/`), **C** = campaign result (`REPORT.pdf`),
**I** = inspection of code or docs.

## 1. Functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| FR-1 | Simulate 2 to 12 drones flying a waypoint mission in a chosen formation (wedge, line, column). | T `test_system` |
| FR-2 | Provide two interchangeable formation controllers: leader-follower and leaderless consensus. | T `test_system` |
| FR-3 | Model GPS (noise, outliers, dropout), dead-reckoning fallback, wind and gusts, and a lossy delayed radio with range limit. | I `drone.py`, `comms.py`; T `test_units` |
| FR-4 | Inject scripted faults: GPS dropout, GPS noise, radio loss (one, some or all drones), motor failure, packet loss. | T `test_units` |
| FR-5 | Run a per-drone failsafe supervisor: hold on lost link, hover then land on lost GPS, recover when the cause clears. | T `test_supervisor` |
| FR-6 | Run a runtime safety monitor: separation keeping against peers including silent ones, vertical deconfliction, geofence. | T `test_system`; C ablation |
| FR-7 | Monitor every drone live: position, mode, altitude, battery, peers heard, estimation error, formation error, minimum separation. | I `dashboard.py` |
| FR-8 | Define scenarios and pass/fail criteria as YAML files, separate from code. | T `test_units` |
| FR-9 | Run many seeded trials in parallel and compute metrics from ground truth. | T `test_system` |
| FR-10 | Produce a test report with figures, tables and generated findings, and a replay dashboard. | C, I |
| FR-11 | Provide an embedded-style C++ port of the failsafe supervisor that is behaviourally identical to the Python one. | T `test_cpp_conformance` |

## 2. Non-functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| NFR-1 | Reproducible: the same scenario, controller and seed give bit-identical metrics. | T `test_same_seed_is_bit_for_bit_reproducible` |
| NFR-2 | On-board code never reads ground-truth positions, only estimates and received messages. | T `test_agents_never_read_ground_truth_position` |
| NFR-3 | No setup hurdles: pure Python with numpy, matplotlib, pyyaml and reportlab; a full campaign runs on a 2-core laptop in under 15 minutes. | C |
| NFR-4 | A missing or NaN metric fails its criterion; it never passes silently. | T `test_evaluate_min_max_equals_and_missing` |
| NFR-5 | Bad configuration is rejected with a clear message before any run starts. | T `test_validation_rejects_bad_configs` |
| NFR-6 | Results are reported with confidence intervals, not only point values. | I `report.py` |

## 3. Safety and information-handling requirements

| ID | Requirement |
|---|---|
| SR-1 | No two drones come closer than 2 m in any accepted scenario (hard limit). |
| SR-2 | Time spent inside the 4 m margin is at most 1 s per trial (soft limit). |
| SR-3 | No drone leaves the geofence. |
| SR-4 | A drone with lost GPS must not keep flying with the formation; it holds, descends to a separation layer, and lands if the loss persists. |
| SR-5 | The project contains no operational, payload, deployment or performance data for any real system. All parameters are generic simulation values. |

## 4. Mapping to the internship posting

| Posting says | Where it is covered |
|---|---|
| General UAV engineering, navigation concepts | `drone.py` (dynamics, estimator), `controllers.py`, mission waypoints |
| Software and system integration | `simulation.py` joins drones, agents, radio, faults, metrics; `docs/ICD.md` |
| System reliability | fault scenarios, failsafe supervisor, recovery and rejoin metrics |
| Simulation-based testing, non-operational assessment | the whole project; SR-5 |
| Reviewing interface requirements | `docs/ICD.md` |
| Comparing results against agreed criteria | `criteria/criteria.yaml`, pass rates with Wilson intervals |
| Technical documentation, evidence-based reporting | `docs/`, `results/REPORT.pdf` |
| Python, C++, control systems, embedded, electronics | Python package; C++ monitor in `failsafe/` sized for a microcontroller |
