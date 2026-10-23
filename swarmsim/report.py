"""Build figures, REPORT.md and REPORT.pdf from the campaign results in results/.

Nothing in the findings is hand-written: every number and every sentence about results is
generated from trials.csv / summary.json, so the report cannot drift from the data.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import platform
import sys
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .config import load_scenario
from .criteria import effective_rules, load_criteria
from .runner import CONTROLLERS, list_scenarios, percentile, prepare_cfg, read_csv, wilson

# --- palette: validated with the dataviz validator (blue/orange: CVD dE 24.7, contrast >= 3:1)
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
CCOL = {"leader_follower": "#2a78d6", "consensus": "#eb6834"}
CNAME = {"leader_follower": "Leader-follower", "consensus": "Consensus"}
DRONE_COL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2,
        "text.color": INK, "font.size": 9, "axes.titlesize": 10.5, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "font.family": "DejaVu Sans", "legend.frameon": False,
    })


def _label(s: str) -> str:
    return s.replace("_", " ")


def _fmt(x: Any, nd: int = 1) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        if math.isnan(x):
            return "-"
        if math.isinf(x):
            return "none"
        return f"{x:.{nd}f}"
    return str(x)


def _ok(x: float) -> bool:
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


# ------------------------------------------------------------------------- data
def load_results(results_dir: str):
    trials = read_csv(os.path.join(results_dir, "trials.csv"))
    summ = json.load(open(os.path.join(results_dir, "summary.json"), encoding="utf-8"))
    for s in summ:
        for k, v in list(s.items()):
            if v == "inf":
                s[k] = float("inf")
            elif v is None:
                s[k] = float("nan")
    abl_path = os.path.join(results_dir, "trials_ablation_no_avoidance.csv")
    abl = read_csv(abl_path) if os.path.exists(abl_path) else []
    return trials, summ, abl


def scenario_limits(scen_dir: str, crit_path: str) -> Dict[str, Dict[str, Dict]]:
    crit = load_criteria(crit_path)
    out = {}
    for p in list_scenarios(scen_dir):
        cfg = load_scenario(p)
        out[cfg["name"]] = {"rules": effective_rules(crit, cfg), "cfg": cfg}
    return out


# ---------------------------------------------------------------------- figures
def fig_pass_rate(summ, req, path):
    scens = sorted({s["scenario"] for s in summ})
    fig, ax = plt.subplots(figsize=(7.4, 0.42 * len(scens) + 1.3))
    for i, sc in enumerate(scens):
        y = len(scens) - 1 - i
        for c, off in (("leader_follower", 0.16), ("consensus", -0.16)):
            r = next((s for s in summ if s["scenario"] == sc and s["controller"] == c), None)
            if not r:
                continue
            ax.errorbar(r["pass_rate"], y + off, xerr=[[r["pass_rate"] - r["ci_low"]], [r["ci_high"] - r["pass_rate"]]],
                        fmt="o", ms=6.5, color=CCOL[c], ecolor=CCOL[c], elinewidth=1.2, capsize=0,
                        mec=SURFACE, mew=1.2)
    ax.axvline(req, color=INK2, lw=1.0, ls=(0, (4, 3)))
    ax.text(req - 0.005, len(scens) - 0.35, f"required {req:.0%}", ha="right", va="bottom", fontsize=8, color=INK2)
    ax.set_yticks(range(len(scens)))
    ax.set_yticklabels([_label(s) for s in reversed(scens)])
    ax.set_xlim(0.0, 1.02)
    ax.set_ylim(-0.7, len(scens) - 0.1)
    ax.set_xlabel("trial pass rate (point) with Wilson 95% interval (bar)")
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", visible=False)
    for c, x in (("leader_follower", 0.02), ("consensus", 0.30)):
        ax.plot([], [], "o", color=CCOL[c], label=CNAME[c])
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.09), ncol=2, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _strip(trials, metric, limits, path, title, xlabel, hlines=(), logx=False):
    scens = sorted({t["scenario"] for t in trials})
    rng = np.random.default_rng(3)
    fig, ax = plt.subplots(figsize=(7.4, 0.42 * len(scens) + 1.2))
    for i, sc in enumerate(scens):
        y = len(scens) - 1 - i
        for c, off in (("leader_follower", 0.17), ("consensus", -0.17)):
            v = [t[metric] for t in trials if t["scenario"] == sc and t["controller"] == c and _ok(t[metric])]
            if not v:
                continue
            ax.scatter(v, y + off + rng.uniform(-0.07, 0.07, len(v)), s=16, color=CCOL[c], alpha=0.75,
                       edgecolors="none")
    for val, lab in hlines:
        ax.axvline(val, color=INK2, lw=1.0, ls=(0, (4, 3)))
        ax.text(val, -0.62, f" {lab}", fontsize=8, color=INK2, va="bottom")
    ax.set_yticks(range(len(scens)))
    ax.set_yticklabels([_label(s) for s in reversed(scens)])
    ax.set_ylim(-0.7, len(scens) - 0.05)
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)
    for c in CONTROLLERS:
        ax.scatter([], [], s=24, color=CCOL[c], label=CNAME[c])
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def fig_separation(trials, path):
    _strip(trials, "min_separation_m", None, path, "", "smallest distance between any two drones in a trial [m]",
           hlines=((2.0, "collision 2 m"), (4.0, "safe margin 4 m")))


def _p50_p95(summ, key50, key95, limit_key, limits, path, xlabel, cap=None):
    rows = [s for s in summ if _ok(s[key50]) or s[key50] == float("inf")]
    scens = sorted({s["scenario"] for s in rows})
    if not scens:
        return False
    vals = [s[key95] for s in rows if _ok(s[key95])] + [s[key50] for s in rows if _ok(s[key50])]
    lims = [limits.get(sc, {}).get("rules", {}).get(limit_key, {}).get("max") for sc in scens]
    lims = [x for x in lims if x is not None]
    xmax = max([*(vals or [10.0]), *lims]) * 1.08 + 0.5
    if cap:
        xmax = max(xmax, cap)
    fig, ax = plt.subplots(figsize=(7.4, 0.42 * len(scens) + 1.2))
    for i, sc in enumerate(scens):
        y = len(scens) - 1 - i
        lim = limits.get(sc, {}).get("rules", {}).get(limit_key, {}).get("max")
        if lim is not None:
            ax.plot([lim, lim], [y - 0.36, y + 0.36], color=INK, lw=1.6)
        for c, off in (("leader_follower", 0.16), ("consensus", -0.16)):
            r = next((s for s in rows if s["scenario"] == sc and s["controller"] == c), None)
            if not r or not (_ok(r[key50]) or r[key50] == float("inf")):
                continue
            p50, p95 = r[key50], r[key95]
            if p50 == float("inf"):
                ax.annotate("never", (xmax * 0.97, y + off), color=CCOL[c], fontsize=8, va="center", ha="right")
                continue
            hi = p95 if _ok(p95) else xmax * 0.97
            ax.plot([p50, hi], [y + off, y + off], color=CCOL[c], lw=1.4, solid_capstyle="round")
            ax.plot([p50], [y + off], "o", ms=6.5, color=CCOL[c], mec=SURFACE, mew=1.2)
            if not _ok(p95):
                ax.annotate(">", (hi, y + off), color=CCOL[c], fontsize=9, va="center")
    ax.set_yticks(range(len(scens)))
    ax.set_yticklabels([_label(s) for s in reversed(scens)])
    ax.set_xlim(0, xmax)
    ax.set_ylim(-0.7, len(scens) - 0.2)
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)
    for c in CONTROLLERS:
        ax.plot([], [], "o-", color=CCOL[c], label=CNAME[c])
    ax.plot([], [], color=INK, lw=1.6, label="limit")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return True


def ablation_table(trials_on, trials_off):
    """Per scenario, same seeds, both controllers pooled: worst-case separation and counts."""
    seeds_off = {t["seed"] for t in trials_off}
    on = [t for t in trials_on if t["seed"] in seeds_off]
    out = []
    for sc in sorted({t["scenario"] for t in trials_off}):
        a = [t for t in on if t["scenario"] == sc]
        b = [t for t in trials_off if t["scenario"] == sc]
        if not a or not b:
            continue
        out.append({"scenario": sc, "n": len(b),
                    "on_worst": min(t["min_separation_m"] for t in a), "off_worst": min(t["min_separation_m"] for t in b),
                    "on_lt4": sum(1 for t in a if t["min_separation_m"] < 4.0), "off_lt4": sum(1 for t in b if t["min_separation_m"] < 4.0),
                    "on_coll": sum(1 for t in a if t["collision_events"] > 0), "off_coll": sum(1 for t in b if t["collision_events"] > 0),
                    "on_pass": sum(1 for t in a if t["passed"]), "off_pass": sum(1 for t in b if t["passed"])})
    return out


def fig_ablation(trials_on, trials_off, path):
    rows = ablation_table(trials_on, trials_off) if trials_off else []
    if not rows:
        return False
    fig, ax = plt.subplots(figsize=(7.4, 0.42 * len(rows) + 1.3))
    for i, r in enumerate(rows):
        y = len(rows) - 1 - i
        ax.plot([r["on_worst"], r["off_worst"]], [y, y], color=AXIS, lw=2.0, zorder=1)
        ax.plot([r["on_worst"]], [y], "o", ms=10, color="#2a78d6", mec=SURFACE, mew=1.2, zorder=2)
        ax.plot([r["off_worst"]], [y], "o", ms=5.5, color="#eb6834", mec=SURFACE, mew=0.8, zorder=3)
    for val, lab in ((2.0, "collision 2 m"), (4.0, "safe margin 4 m")):
        ax.axvline(val, color=INK2, lw=1.0, ls=(0, (4, 3)))
        ax.text(val, -0.62, f" {lab}", fontsize=8, color=INK2, va="bottom")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([_label(r["scenario"]) for r in reversed(rows)])
    ax.set_ylim(-0.7, len(rows) - 0.1)
    ax.set_xlim(0, max(r["on_worst"] for r in rows) * 1.15 + 0.5)
    ax.set_xlabel("worst-case smallest separation over the same 40 trials (2 controllers x 20 seeds) [m]")
    ax.grid(axis="y", visible=False)
    ax.plot([], [], "o", ms=9, color="#2a78d6", label="safety layer ON")
    ax.plot([], [], "o", ms=5.5, color="#eb6834", label="safety layer OFF")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return True


def fig_example(scenario_path: str, seed: int, path: str, crit_eval: Dict):
    from .simulation import run_simulation
    runs = {}
    for c in CONTROLLERS:
        cfg = prepare_cfg(scenario_path, c, None)
        runs[c] = run_simulation(cfg, seed=seed)
    name = runs[CONTROLLERS[0]].cfg["name"]
    fig = plt.figure(figsize=(7.4, 7.6))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.35, 0.8, 0.8], hspace=0.42, wspace=0.18)
    for col, c in enumerate(CONTROLLERS):
        ax = fig.add_subplot(gs[0, col])
        r = runs[c]
        tr = r.trace
        for i in range(tr.n):
            ax.plot(tr.pos[:, i, 0], tr.pos[:, i, 1], color=DRONE_COL[i % 5], lw=1.3)
            ax.plot(tr.pos[0, i, 0], tr.pos[0, i, 1], "o", ms=4, color=DRONE_COL[i % 5])
            ax.text(tr.pos[-1, i, 0], tr.pos[-1, i, 1], f" {i}", fontsize=8, color=INK2, va="center")
        for f in r.faults:
            if f.discrete:
                k = min(int(f.t_on / tr.dt), tr.steps - 1)
                for d in f.drones[:2]:
                    ax.plot(tr.pos[k, d, 0], tr.pos[k, d, 1], "x", ms=8, mew=2, color=INK)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title(f"{CNAME[c]}: drone paths", fontsize=9.5)
        ax.set_xlabel("x [m]")
        if col == 0:
            ax.set_ylabel("y [m]")
        ax.grid(True)
    axe = fig.add_subplot(gs[1, :])
    axs = fig.add_subplot(gs[2, :])
    for c in CONTROLLERS:
        tr = runs[c].trace
        axe.plot(tr.t, tr.form_err, color=CCOL[c], lw=1.4, label=CNAME[c])
        sep = np.where(np.isfinite(tr.min_sep), tr.min_sep, np.nan)
        axs.plot(tr.t, sep, color=CCOL[c], lw=1.4)
    for f in runs[CONTROLLERS[0]].faults:
        if f.discrete:
            for ax_ in (axe, axs):
                ax_.axvline(f.t_on, color=INK2, lw=0.9, ls=(0, (4, 3)))
            axe.text(f.t_on, axe.get_ylim()[1], f" {f.type.replace('_', ' ')}", fontsize=7.5, color=INK2, va="top")
    axs.axhline(2.0, color=INK2, lw=0.9, ls=(0, (4, 3)))
    axs.text(axs.get_xlim()[1], 2.0, "collision 2 m ", fontsize=7.5, color=INK2, ha="right", va="bottom")
    axe.set_ylabel("formation error [m]")
    axs.set_ylabel("min separation [m]")
    axs.set_xlabel("time [s]")
    axe.legend(loc="upper right", fontsize=8.5)
    fig.suptitle(f"Example trial: {_label(name)} (seed {seed})", x=0.06, ha="left", fontsize=10.5, fontweight="bold")
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------- narratives
def _pooled(summ, ctrl):
    ss = [s for s in summ if s["controller"] == ctrl]
    k = sum(s["passes"] for s in ss)
    n = sum(s["trials"] for s in ss)
    return k, n, wilson(k, n)


def findings(summ, trials, abl, limits) -> List[str]:
    out: List[str] = []
    req = None
    nA = len(summ)
    acc = [s for s in summ if s["verdict"] == "PASS"]
    out.append(f"{len(acc)} of {nA} scenario/controller combinations met the acceptance rule "
               f"(trial pass rate at or above the required level).")
    for c in CONTROLLERS:
        k, n, (lo, hi) = _pooled(summ, c)
        out.append(f"{CNAME[c]} passed {k} of {n} trials overall ({k / n:.1%}, Wilson 95% interval {lo:.1%} to {hi:.1%}).")
    fails = [s for s in summ if s["verdict"] == "FAIL"]
    for s in fails:
        why = ", ".join(f"{k} ({v}x)" for k, v in sorted(s["fail_reasons"].items(), key=lambda kv: -kv[1])) or "n/a"
        out.append(f"NOT ACCEPTED: {_label(s['scenario'])} with {CNAME[s['controller']]}: "
                   f"{s['passes']}/{s['trials']} passed; failed criteria: {why}.")
    inside = {}
    for s_ in summ:
        if s_["verdict"] == "PASS":
            for k, v in s_["fail_reasons"].items():
                inside.setdefault(k, []).append(f"{_label(s_['scenario'])}/{CNAME[s_['controller']]} x{v}")
    if inside:
        out.append("Individual failed trials inside accepted combinations: "
                   + "; ".join(f"{k.replace('_', ' ')}: " + ", ".join(v) for k, v in sorted(inside.items())) + ".")
    colls = sum(s["collision_trials"] for s in summ)
    ntr = sum(s["trials"] for s in summ)
    out.append(f"Collisions (two drones closer than 2 m): {colls} of {ntr} trials with the safety layer on.")
    diffs = []
    for sc in sorted({s["scenario"] for s in summ}):
        a = next((s for s in summ if s["scenario"] == sc and s["controller"] == "leader_follower"), None)
        b = next((s for s in summ if s["scenario"] == sc and s["controller"] == "consensus"), None)
        if a and b and (a["ci_low"] > b["ci_high"] or b["ci_low"] > a["ci_high"]):
            better = "Leader-follower" if a["pass_rate"] > b["pass_rate"] else "Consensus"
            diffs.append(f"{_label(sc)} ({better} better: {a['passes']}/{a['trials']} vs {b['passes']}/{b['trials']})")
    if diffs:
        out.append("Controller differences larger than the statistical noise (non-overlapping 95% intervals): "
                   + "; ".join(diffs) + ".")
    else:
        out.append("No scenario separates the two controllers beyond statistical noise at this trial count.")
    if abl:
        tab = ablation_table(trials, abl)
        n_on = sum(r["on_pass"] for r in tab)
        n_off = sum(r["off_pass"] for r in tab)
        n_all = sum(r["n"] for r in tab)
        out.append(f"Safety-layer ablation (same seeds, {n_all} trials each way): {n_on} passed with the layer on and "
                   f"{n_off} with it off; collisions {sum(r['on_coll'] for r in tab)} on vs {sum(r['off_coll'] for r in tab)} off; "
                   f"trials inside the 4 m margin {sum(r['on_lt4'] for r in tab)} on vs {sum(r['off_lt4'] for r in tab)} off.")
        helped = [r for r in tab if r["off_worst"] < r["on_worst"] - 0.5]
        if helped:
            out.append("Scenarios where switching the layer off made the worst case clearly worse (more than 0.5 m): "
                       + "; ".join(f"{_label(r['scenario'])} (worst separation {r['on_worst']:.1f} m with, {r['off_worst']:.1f} m without)"
                                   for r in helped) + ". Elsewhere the layer changed the worst case by less than 0.5 m.")
        else:
            out.append("In no scenario did switching the layer off change the worst-case separation by more than 0.5 m.")
    fa = sum(s["false_alarm_trials"] for s in summ)
    out.append(f"False peer-loss alarms (heartbeat timeout with no fault involved): {fa} of {ntr} trials.")
    return out


DIAGNOSTICS = [
    "Strong wind, leader-follower (19 of 30 passed): the cause is airspeed headroom. A 3 to 5 m/s wind against a 4 m/s "
    "cruise speed needs about 7 to 9 m/s of air speed on upwind legs, at or above the 8 m/s vehicle limit. Rerunning the same "
    "30 seeds with the limit raised to 12 m/s gives 30 of 30 for both controllers. Not fixed: slowing the mission to keep "
    "headroom would trade a formation failure for a mission-time failure.",
    "Geofence breach in the leader GPS-loss scenario (1 of 30 trials per controller): the drone that lost GPS drifted about "
    "52 m on dead reckoning while landing and was outside the fence for 3 to 4 s at 3 to 4 m altitude. Not fixed.",
    "The single collision in 720 trials (compound scenario, leader-follower, 1.24 m): two healthy drones in formation, about "
    "10 s after a GPS dropout ended. Cause not isolated.",
    "Safety layer: it changes the worst case clearly only where a neighbour goes silent (worst separation 6.0 m with it, "
    "1.0 m without, in the single radio-loss scenario). Elsewhere total pass counts are identical with it on and off.",
]


STATIC_LIMITS = [
    "Simulation only. The vehicle is a point mass with a first-order velocity loop, an acceleration limit and a "
    "speed limit. It is not a rotor-level or attitude model and no real flight stack (PX4/ArduPilot) is in the loop.",
    "GPS, the radio and the wind are statistical models with the parameters listed in config.py. Real multipath, "
    "jamming, antenna patterns and terrain effects are not modelled.",
    "Results describe behaviour of this simulator under these faults. They are evidence for design decisions and a "
    "regression baseline, not a safety case or a guarantee about any physical system.",
    "Pass rates come from 30 trials per case, so a 100% rate still has a Wilson lower bound near 89%. The report "
    "therefore shows intervals, not only point values.",
    "Formation slots are fixed per drone: after a loss the formation keeps a gap instead of closing ranks. This was a "
    "deliberate choice to avoid slot swaps when a drone rejoins.",
    "Faults are injected one scenario at a time (plus one compound case). Common-cause failures and adversarial "
    "network behaviour are out of scope.",
    "The acceptance criteria were written before the campaign; two design parameters (heartbeat timeout, altitude layer "
    "in GPS failsafe) were changed after earlier small test runs exposed problems. The change history is in docs/DESIGN.md.",
]


# --------------------------------------------------------------------- build it
def build_report(results_dir: str, criteria_path: str, scen_dir: str) -> None:
    _style()
    fig_dir = os.path.join(results_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    trials, summ, abl = load_results(results_dir)
    crit = load_criteria(criteria_path)
    limits = scenario_limits(scen_dir, criteria_path)
    req = crit["required_pass_rate"]

    fig_pass_rate(summ, req, os.path.join(fig_dir, "pass_rate.png"))
    fig_separation(trials, os.path.join(fig_dir, "separation.png"))
    have_rec = _p50_p95(summ, "recovery_p50", "recovery_p95", "recovery_time_s", limits,
                        os.path.join(fig_dir, "recovery.png"), "time from fault to a re-formed swarm [s]\n(point = median trial, bar = 95th-percentile trial)")
    fig_p = _p50_p95(summ, "steady_error_p50", "steady_error_p95", "steady_error_p95_m", limits,
                     os.path.join(fig_dir, "steady_error.png"), "steady-state formation error [m]\n(point = median trial, bar = 95th-percentile trial)")
    have_abl = fig_ablation(trials, abl, os.path.join(fig_dir, "ablation.png"))
    ex = [p for p in list_scenarios(scen_dir) if os.path.basename(p).startswith("12_")]
    if ex:
        fig_example(ex[0], 1000, os.path.join(fig_dir, "example.png"), crit["evaluation"])

    finds = findings(summ, trials, abl, limits)
    figs = {
        "pass_rate": os.path.join(fig_dir, "pass_rate.png"),
        "separation": os.path.join(fig_dir, "separation.png"),
        "recovery": os.path.join(fig_dir, "recovery.png") if have_rec else None,
        "steady": os.path.join(fig_dir, "steady_error.png") if fig_p else None,
        "ablation": os.path.join(fig_dir, "ablation.png") if have_abl else None,
        "example": os.path.join(fig_dir, "example.png") if ex else None,
    }
    write_markdown(results_dir, summ, finds, limits, crit, figs, trials, abl)
    write_pdf(results_dir, summ, finds, limits, crit, figs, trials, abl)
    print(f"wrote {os.path.join(results_dir, 'REPORT.md')} and REPORT.pdf, figures in {fig_dir}")


def _table_rows(summ):
    head = ["Scenario", "Controller", "Pass", "Rate [95% CI]", "Verdict", "Min sep [m]", "Coll.",
            "Detect p95 [s]", "Recover p95 [s]", "Steady err p95 [m]"]
    rows = []
    for s in summ:
        rows.append([_label(s["scenario"]), CNAME[s["controller"]], f"{s['passes']}/{s['trials']}",
                     f"{s['pass_rate']:.0%} [{s['ci_low']:.0%}-{s['ci_high']:.0%}]", s["verdict"],
                     _fmt(s["min_separation_min"], 2), str(s["collision_trials"]), _fmt(s["detection_p95"]),
                     _fmt(s["recovery_p95"]), _fmt(s["steady_error_p95"], 2)])
    return head, rows


def _env_lines() -> List[str]:
    return [f"Python {platform.python_version()}, numpy {np.__version__}, matplotlib {matplotlib.__version__}",
            f"Platform: {platform.system()} {platform.machine()}",
            f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"]


def write_markdown(results_dir, summ, finds, limits, crit, figs, trials, abl):
    L: List[str] = []
    n_tr = len(trials)
    L.append("# SwarmSim: Test Report\n")
    L.append("Simulation-based assessment of two multi-UAV formation controllers under injected faults. "
             "Simulation only: no flight hardware, payload or operational capability.\n")
    L.append("## 1. Summary\n")
    for f in finds:
        L.append(f"- {f}")
    L.append("\n## 2. Method\n")
    L.append(f"- {len(limits)} scenarios x {len(CONTROLLERS)} controllers x {n_tr // (len(limits) * len(CONTROLLERS))} "
             f"seeded trials = {n_tr} trials. Seeds are fixed, so every number is reproducible.")
    L.append("- Each trial flies a 5-drone wedge on a square mission (about 100 s) with wind, GPS noise, a lossy radio and "
             "a fault schedule. Fault onset times carry a seeded jitter.")
    L.append("- Acceptance criteria were written in `criteria/criteria.yaml` before the campaign. "
             f"A trial passes when every applicable criterion passes; a combination is accepted when at least {crit['required_pass_rate']:.0%} of trials pass.")
    L.append("- Metrics are computed from ground truth, never from what a drone believes. On-board code only uses estimates and received messages.\n")
    L.append("## 3. Results\n")
    head, rows = _table_rows(summ)
    L.append("| " + " | ".join(head) + " |")
    L.append("|" + "|".join(["---"] * len(head)) + "|")
    for r in rows:
        L.append("| " + " | ".join(r) + " |")
    L.append("")
    caps = {"pass_rate": "Trial pass rate per scenario", "separation": "Smallest drone-to-drone distance per trial",
            "recovery": "Recovery time after a fault", "steady": "Steady-state formation error",
            "ablation": "Effect of switching the safety layer off", "example": "Example trial"}
    for k in ("pass_rate", "separation", "recovery", "steady", "ablation", "example"):
        if figs.get(k):
            L.append(f"![{caps[k]}](figures/{os.path.basename(figs[k])})\n")
    L.append("## 4. Acceptance criteria applied\n")
    L.append("| Scenario | Criteria |")
    L.append("|---|---|")
    for name, d in sorted(limits.items()):
        txt = "; ".join(f"{k} {_rule(v)}" for k, v in d["rules"].items())
        L.append(f"| {_label(name)} | {txt} |")
    L.append("\n## 5. Diagnostics after the campaign\n")
    L.append("Hand-written analysis of the campaign of 22 Oct 2026 (seeds 1000 to 1029). Not regenerated when the campaign is rerun.\n")
    for d_ in DIAGNOSTICS:
        L.append(f"- {d_}")
    L.append("\n## 6. Limitations\n")
    for s in STATIC_LIMITS:
        L.append(f"- {s}")
    L.append("\n## 7. Reproducing this report\n")
    L.append("```\npip install -r requirements.txt\npython -m swarmsim run --trials 30 --ablate --ablate-trials 20 --out results\n"
             "python -m swarmsim report\npython -m pytest tests -q\n```\n")
    for e in _env_lines():
        L.append(f"- {e}")
    with open(os.path.join(results_dir, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def _rule(r) -> str:
    if "equals" in r:
        return f"= {r['equals']}"
    parts = []
    if "min" in r:
        parts.append(f">= {r['min']}")
    if "max" in r:
        parts.append(f"<= {r['max']}")
    return " and ".join(parts)


def write_pdf(results_dir, summ, finds, limits, crit, figs, trials, abl):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.2, leading=12.6,
                          textColor=colors.HexColor(INK), alignment=TA_LEFT)
    h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=21, leading=25, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=12, spaceAfter=5)
    sub = ParagraphStyle("sub", parent=base, textColor=colors.HexColor(INK2), fontSize=9.6, leading=13)
    cap = ParagraphStyle("cap", parent=base, fontSize=8, leading=10, textColor=colors.HexColor(INK2), spaceAfter=7)
    small = ParagraphStyle("s", parent=base, fontSize=7.1, leading=8.6)
    smallb = ParagraphStyle("sb", parent=small, fontName="Helvetica-Bold")

    doc = SimpleDocTemplate(os.path.join(results_dir, "REPORT.pdf"), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title="SwarmSim Test Report", author="SwarmSim")
    W = A4[0] - 34 * mm
    S: List[Any] = []

    def img(path, width=W):
        from PIL import Image as PI
        w, h = PI.open(path).size
        return Image(path, width=width, height=width * h / w)

    def bullets(items):
        return ListFlowable([ListItem(Paragraph(i, base), leftIndent=10) for i in items], bulletType="bullet",
                            start="•", leftIndent=12, bulletFontSize=8)

    n_tr = len(trials)
    S += [Paragraph("SwarmSim: Test Report", h1),
          Paragraph("Simulation-based assessment of two multi-UAV formation controllers under injected faults. "
                    "Simulation only: no flight hardware, payload or operational capability.", sub), Spacer(1, 8)]
    S += [Paragraph("1. Summary", h2), bullets([_esc(f) for f in finds])]
    S += [Paragraph("2. Method", h2), bullets([
        f"{len(limits)} scenarios x {len(CONTROLLERS)} controllers x {n_tr // (len(limits) * len(CONTROLLERS))} seeded trials = {n_tr} trials. Seeds are fixed, so every number is reproducible.",
        "Each trial flies a 5-drone wedge on a square mission (about 100 s) with wind, GPS noise, a lossy radio and a fault schedule. Fault onset times carry a seeded jitter.",
        f"Acceptance criteria were fixed in criteria/criteria.yaml before the campaign. A trial passes when every applicable criterion passes; a combination is accepted when at least {crit['required_pass_rate']:.0%} of trials pass.",
        "Metrics are computed from ground truth, never from what a drone believes. On-board code only uses its own estimates and received messages.",
    ])]
    if figs.get("pass_rate"):
        S += [KeepTogether([Paragraph("3. Results", h2), img(figs["pass_rate"]),
                            Paragraph("Figure 1. Trial pass rate with Wilson 95% interval. The dashed line is the required rate.", cap)])]
    else:
        S += [Paragraph("3. Results", h2)]
    head, rows = _table_rows(summ)
    data = [[Paragraph(h, smallb) for h in head]] + [[Paragraph(_esc(c), small) for c in r] for r in rows]
    cw = [29 * mm, 24 * mm, 11 * mm, 25 * mm, 14 * mm, 13 * mm, 10 * mm, 14 * mm, 15 * mm, 15 * mm]
    scale = W / sum(cw)
    t = Table(data, colWidths=[c * scale for c in cw], repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeede8")), ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(AXIS)),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
          ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor(GRID))]
    for i, s in enumerate(summ, start=1):
        if s["verdict"] == "FAIL":
            st.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#f8dcdc")))
        else:
            st.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#dcf0dc")))
    t.setStyle(TableStyle(st))
    S += [t, Paragraph("Table 1. Per scenario and controller. Min sep is the smallest distance between any two drones in any trial. "
                       "Detect, recover and steady error are 95th percentiles over trials; '-' means not applicable, 'none' means it never happened in some trial.", cap)]
    if figs.get("separation"):
        S += [KeepTogether([Paragraph("4. Safety", h2), img(figs["separation"]),
                            Paragraph("Figure 2. Smallest distance between any two drones in each trial (one dot per trial). Left of the 2 m line is a collision.", cap)])]
    if figs.get("ablation"):
        S += [KeepTogether([Paragraph("Switching the runtime safety layer (separation keeping, tracks of silent peers, vertical deconfliction) off on the same seeds shows where it changes the outcome and where it does not.", base), Spacer(1, 4),
              img(figs["ablation"]), Paragraph("Figure 3. Worst-case smallest separation, safety layer on versus off, same seeds. Dots on top of each other mean no difference.", cap)])]
    if figs.get("recovery"):
        S += [KeepTogether([Paragraph("5. Fault handling and accuracy", h2), img(figs["recovery"]),
                            Paragraph("Figure 4. Time from fault onset until the surviving swarm is formed up again and everyone agrees who is in it. Black ticks are the scenario limits.", cap)])]
    else:
        S += [Paragraph("5. Fault handling and accuracy", h2)]
    if figs.get("steady"):
        S += [KeepTogether([img(figs["steady"]), Paragraph("Figure 5. Formation shape error in steady state. Black ticks are the scenario limits.", cap)])]
    if figs.get("example"):
        S += [PageBreak(), KeepTogether([Paragraph("6. Example trial", h2), img(figs["example"], W * 0.92),
              Paragraph("Figure 6. The compound scenario (packet loss, a follower crash, then a GPS dropout) for both controllers. Crosses mark where drones were hit by a fault.", cap)])]
    S += [Paragraph("7. Acceptance criteria applied", h2)]
    cd = [[Paragraph("Scenario", smallb), Paragraph("Criteria", smallb)]]
    for name, d in sorted(limits.items()):
        cd.append([Paragraph(_esc(_label(name)), small), Paragraph(_esc("; ".join(f"{k} {_rule(v)}" for k, v in d["rules"].items())), small)])
    tc = Table(cd, colWidths=[38 * mm, W - 38 * mm], repeatRows=1)
    tc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeede8")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor(GRID)), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    S += [tc]
    S += [Paragraph("8. Diagnostics after the campaign", h2),
          Paragraph("Hand-written analysis of the campaign of 22 Oct 2026 (seeds 1000 to 1029). Not regenerated when the campaign is rerun.", sub),
          Spacer(1, 3), bullets([_esc(x) for x in DIAGNOSTICS])]
    S += [Paragraph("9. Limitations", h2), bullets([_esc(x) for x in STATIC_LIMITS])]
    S += [Paragraph("10. Reproducing this report", h2),
          Paragraph("pip install -r requirements.txt<br/>python -m swarmsim run --trials 30 --ablate --ablate-trials 20 --out results<br/>"
                    "python -m swarmsim report<br/>python -m pytest tests -q", ParagraphStyle("code", parent=base, fontName="Courier", fontSize=8.2)),
          Spacer(1, 4), bullets([_esc(e) for e in _env_lines()])]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(17 * mm, 9 * mm, "SwarmSim test report (simulation only)")
        canvas.drawRightString(A4[0] - 17 * mm, 9 * mm, f"page {d.page}")
        canvas.restoreState()

    doc.build(S, onFirstPage=footer, onLaterPages=footer)


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
