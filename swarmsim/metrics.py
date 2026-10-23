"""Metrics computed from the ground-truth trace of one trial.

Definitions are documented in docs/TEST_PLAN.md section 4. In short:

min_separation_m        smallest 3-D distance between any two airborne drones, whole run
time_below_safe_sep_s   total time that smallest distance was under the safety margin
formation_error_*       RMS shape error of the healthy participants, each measured against
                        ITS OWN assigned slot, so inconsistent slot assignments show up as error
steady_error_p95_m      same, but only in steady state: membership agreed by everyone and no
                        change in membership during the last ``steady_after_change_s``
detection_time_s        fault onset -> first healthy peer drops the faulty drone (worst fault)
recovery_time_s         fault onset -> membership agreed AND shape error < threshold, held
rejoin_time_s           end of a finite fault -> drone is a participant again and formed up
"""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from .faults import FaultRecord
from .simulation import SimResult

INF = float("inf")


def _good_window(ok: np.ndarray, hold_steps: int) -> np.ndarray:
    """gw[k] is True iff ok[k : k + hold_steps] are all True."""
    T = len(ok)
    gw = np.zeros(T, dtype=bool)
    if hold_steps <= 0 or T < hold_steps:
        return gw
    cs = np.concatenate([[0], np.cumsum(ok.astype(np.int64))])
    win = cs[hold_steps:] - cs[:-hold_steps]
    gw[: len(win)] = win == hold_steps
    return gw


def _first_peer_loss(res: SimResult, fault: FaultRecord) -> float:
    best = INF
    for (t, kind, _obs, subj, _d) in res.events:
        if kind == "PEER_LOST" and t >= fault.t_on - 1e-9 and subj in fault.drones:
            best = min(best, t)
    return best


def compute_metrics(res: SimResult, ev: Dict) -> Dict:
    tr = res.trace
    dt, n, t = tr.dt, tr.n, tr.t
    T = tr.steps
    d_coll, d_safe = ev["d_collision_m"], ev["d_safe_m"]
    rec_err, rec_hold = ev["recovery_error_m"], ev["recovery_hold_s"]
    warm, steady_after = ev["warmup_s"], ev["steady_after_change_s"]
    m: Dict = {}

    m["duration_s"] = float(t[-1]) if T else 0.0
    m["mission_complete"] = res.t_complete is not None
    m["mission_time_s"] = float(res.t_complete) if res.t_complete is not None else float("nan")
    m["survivors_at_end"] = int(tr.participant[-1].sum())

    sep = tr.min_sep
    finite = sep[np.isfinite(sep)]
    m["min_separation_m"] = float(finite.min()) if len(finite) else INF
    m["time_below_safe_sep_s"] = float((sep < d_safe).sum() * dt)
    below = sep < d_coll
    m["collision_events"] = int(below[0]) + int(np.sum(below[1:] & ~below[:-1])) if T else 0
    m["geofence_breach"] = bool(tr.breach.any())

    # ---- formation error
    e = tr.form_err
    valid = (t >= warm) & ~np.isnan(e)
    ev_all = e[valid]
    m["formation_error_mean_m"] = float(ev_all.mean()) if len(ev_all) else float("nan")
    m["formation_error_p95_m"] = float(np.percentile(ev_all, 95)) if len(ev_all) else float("nan")
    m["formation_error_max_m"] = float(ev_all.max()) if len(ev_all) else float("nan")

    code = (tr.participant.astype(np.int64) * (2 ** np.arange(n))).sum(axis=1)
    last_change = np.zeros(T)
    lc = 0.0
    for k in range(1, T):
        if code[k] != code[k - 1]:
            lc = t[k]
        last_change[k] = lc
    steady = valid & tr.consistent & ((t - last_change) >= steady_after)
    es = e[steady]
    m["steady_error_p95_m"] = float(np.percentile(es, 95)) if len(es) >= 20 else float("nan")
    m["steady_fraction"] = float(steady.sum() / max(valid.sum(), 1))

    # ---- navigation quality
    part = tr.participant
    if part.any():
        err = np.linalg.norm(tr.est_pos - tr.pos, axis=2)
        m["est_error_max_m"] = float(err[part].max())
        m["est_error_mean_m"] = float(err[part].mean())
    else:
        m["est_error_max_m"] = m["est_error_mean_m"] = float("nan")

    # ---- fault handling
    recovered = tr.consistent & ~np.isnan(e) & (e < rec_err)
    hold_steps = int(round(rec_hold / dt))
    gw = _good_window(recovered, hold_steps)

    det, rec, rej = [], [], []
    for f in res.faults:
        if not f.discrete:
            continue
        t_first = _first_peer_loss(res, f)
        det_f = t_first - f.t_on
        det.append(det_f)
        if math.isfinite(t_first):
            k0 = int(math.ceil(t_first / dt))
            ks = np.nonzero(gw[k0:])[0]
            rec.append((t[k0 + ks[0]] - f.t_on) if len(ks) else INF)
        else:
            rec.append(INF)
        if res.cfg.get("expect_rejoin") and f.finite and f.type in ("gps_dropout", "comms_loss"):
            k0 = int(math.ceil(f.t_off / dt))
            idx = np.nonzero(gw[k0:])[0]
            best = INF
            for k in idx:
                kk = k0 + k
                if part[kk: kk + hold_steps][:, f.drones].all():
                    best = t[kk] - f.t_off
                    break
            rej.append(best)
    m["detection_time_s"] = float(max(det)) if det else float("nan")
    m["recovery_time_s"] = float(max(rec)) if rec else float("nan")
    m["rejoin_time_s"] = float(max(rej)) if rej else float("nan")
    m["false_peer_loss_events"] = int(res.false_peer_loss)
    m["explained_peer_loss_events"] = int(res.explained_peer_loss)

    # ---- bookkeeping
    m["avoidance_active_s"] = float(tr.avoid.sum() * dt)
    m["comms_drop_rate"] = float(res.comms_dropped / max(res.comms_sent, 1))
    m["wind_steady_ms"] = float(res.wind_steady)
    m["leader_change_events"] = int(sum(1 for e_ in res.events if e_[1] == "LEADER" and e_[0] > 2.0))
    return m
