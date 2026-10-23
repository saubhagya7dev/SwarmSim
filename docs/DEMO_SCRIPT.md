# SwarmSim: 3-minute demo script

Use this for a screen recording or a live walkthrough. Total about 3 minutes. Have `results/dashboard.html`
open in a browser and a terminal in the project folder.

## 0:00 to 0:25 - the question (say it, show the README)

"This is SwarmSim, a simulation test bench for drone-swarm fault tolerance. It answers one question: under which
faults does a small swarm stay safe and finish its mission, and where does it fail? It is simulation only, with
no hardware, payload or operational content."

## 0:25 to 1:15 - one fault, live (dashboard)

1. Pick scenario **07 drone failure follower**, controller **Consensus**, press Play at 2x.
2. Point at the event log: "A follower loses its motors at about 40 seconds. Within about 3 seconds the others
   notice the missing heartbeat and carry on with four drones."
3. Point at the chart: "Minimum separation never goes near the 2 metre collision line."
4. Switch to **03 gps dropout long**: "A drone loses GPS. It holds, drops to a lower layer, then lands after 10 seconds.
   The state machine behind this is also written in C++ for a microcontroller, and a test checks it matches
   the Python version on every tick."

## 1:15 to 2:10 - the evidence (open REPORT.pdf, page 2)

"Each scenario runs 30 seeded trials per controller. The acceptance criteria were written before the experiments.
23 of 24 combinations meet the 90 percent rule. There was one collision in 720 trials, and no false alarms
even with 30 percent packet loss."

Show the pass-rate chart: "The one failure is leader-follower in strong wind, 19 of 30."

## 2:10 to 2:40 - a failure explained

"I diagnosed it: with 3 to 5 metres per second of wind and a 4 metre per second cruise speed, the drones run out
of airspeed on upwind legs. Raising the speed limit to 12 makes it 30 of 30. I did not hide it or retune the
criteria. It is written up as an open issue with the trade-off: slowing down would fix the formation but miss the
mission time."

## 2:40 to 3:00 - honesty and next steps

"Limits: point-mass physics, statistical GPS and radio, no real flight stack. Results are simulation evidence,
not guarantees. Next: a MAVLink bridge to PX4 SITL and running the failsafe monitor on real hardware."

## Terminal commands if asked to run something live

```
python -m pytest tests -q                       # 65 tests, about 30 seconds
python -m swarmsim one 07 consensus --events    # one trial, verdict and events
python -m swarmsim one 11 leader_follower --seed 1022   # a strong-wind failure
```

## Questions you should be ready for

- **Why not PX4 or Gazebo?** Setup risk with a 3-day window. The interfaces are narrow so a bridge can replace the vehicle model later.
- **Why do early test seeds overlap with the campaign?** Disclosed in `docs/DESIGN.md`; a mild source of optimism.
- **Is 30 of 30 proof of safety?** No. The 95% lower bound is about 89%, which is why intervals are shown.
- **Why is consensus better in wind?** Not investigated. The airspeed cause is confirmed; the difference between controllers is an open question.
