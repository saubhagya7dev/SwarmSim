"""Command line interface:  python -m swarmsim <command> ..."""
from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .criteria import load_criteria
from .runner import (CONTROLLERS, DEFAULT_CRITERIA, DEFAULT_SCENARIOS, list_scenarios, prepare_cfg,
                     read_csv, run_suite, summarize, write_summary)


def _scenario_paths(directory: str, only: List[str]) -> List[str]:
    paths = list_scenarios(directory)
    if only:
        paths = [p for p in paths if any(o in os.path.basename(p) for o in only)]
        if not paths:
            raise SystemExit(f"no scenario matches {only}")
    return paths


def cmd_run(a: argparse.Namespace) -> int:
    paths = _scenario_paths(a.scenarios, a.only)
    controllers = a.controllers.split(",")
    crit = load_criteria(a.criteria)
    os.makedirs(a.out, exist_ok=True)
    print(f"SwarmSim: {len(paths)} scenarios x {len(controllers)} controllers x {a.trials} trials "
          f"= {len(paths) * len(controllers) * a.trials} runs ({a.workers} workers)")
    rows = run_suite(paths, controllers, a.trials, a.workers, a.out, a.criteria, a.seed,
                     avoidance=None, label="trials")
    summ = summarize(rows, crit["required_pass_rate"])
    write_summary(os.path.join(a.out, "summary.json"), summ)
    if a.ablate:
        abl_paths = [p for p in paths if any(k in os.path.basename(p) for k in a.ablate_only)] \
            if a.ablate_only else paths
        n_abl = a.ablate_trials or a.trials
        print(f"Ablation: safety avoidance OFF on {len(abl_paths)} scenarios, {n_abl} trials each")
        rows_off = run_suite(abl_paths, controllers, n_abl, a.workers, a.out, a.criteria, a.seed,
                             avoidance=False, label="trials_ablation_no_avoidance")
        write_summary(os.path.join(a.out, "summary_ablation.json"),
                      summarize(rows_off, crit["required_pass_rate"]))
    print_summary(summ)
    return 0


def print_summary(summ) -> None:
    print(f"\n{'scenario':28s} {'controller':16s} {'pass':>9s} {'rate':>6s}  verdict  minsep  recov95")
    for s in summ:
        rec = s["recovery_p95"]
        print(f"{s['scenario']:28s} {s['controller']:16s} {s['passes']:>4d}/{s['trials']:<4d} "
              f"{s['pass_rate']:6.2f}  {s['verdict']:7s} {s['min_separation_min']:6.2f}  "
              f"{'-' if rec != rec else format(rec, '.1f')}")


def cmd_one(a: argparse.Namespace) -> int:
    from .metrics import compute_metrics
    from .criteria import effective_rules, evaluate
    from .simulation import run_simulation
    path = _scenario_paths(a.scenarios, [a.scenario])[0]
    cfg = prepare_cfg(path, a.controller, None if a.avoidance is None else a.avoidance == "on")
    crit = load_criteria(a.criteria)
    res = run_simulation(cfg, seed=a.seed)
    m = compute_metrics(res, crit["evaluation"])
    ok, details = evaluate(m, effective_rules(crit, cfg))
    print(f"{cfg['name']} / {a.controller} / seed {a.seed}: {'PASS' if ok else 'FAIL'}")
    for d in details:
        print(f"  {'ok  ' if d['passed'] else 'FAIL'} {d['criterion']:26s} = {d['value']!s:10.10s} {d['rule']} {d['why']}")
    if a.events:
        print("\nevents:")
        for (t, kind, obs, subj, det) in res.events:
            if kind in ("MODE", "PEER_LOST", "LEADER", "GEOFENCE") or a.events == "all":
                print(f"  t={t:6.1f}  {kind:10s} drone {obs}  subject {subj}  {det}")
    return 0 if ok else 1


def cmd_report(a: argparse.Namespace) -> int:
    from .report import build_report
    build_report(a.results, a.criteria, a.scenarios)
    return 0


def cmd_dashboard(a: argparse.Namespace) -> int:
    from .dashboard import build_dashboard
    out = build_dashboard(a.out, a.scenarios, a.criteria, a.seed)
    print(f"wrote {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="swarmsim", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--scenarios", default=DEFAULT_SCENARIOS)
        sp.add_argument("--criteria", default=DEFAULT_CRITERIA)

    r = sub.add_parser("run", help="run the full test campaign")
    common(r)
    r.add_argument("--trials", type=int, default=30)
    r.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    r.add_argument("--controllers", default=",".join(CONTROLLERS))
    r.add_argument("--only", nargs="*", default=[], help="substring filter on scenario file names")
    r.add_argument("--seed", type=int, default=1000)
    r.add_argument("--out", default="results")
    r.add_argument("--ablate", action="store_true", help="also run with the avoidance layer disabled")
    r.add_argument("--ablate-only", nargs="*", default=[])
    r.add_argument("--ablate-trials", type=int, default=0)
    r.set_defaults(fn=cmd_run)

    o = sub.add_parser("one", help="run a single trial and print the criteria verdict")
    common(o)
    o.add_argument("scenario")
    o.add_argument("controller", choices=list(CONTROLLERS))
    o.add_argument("--seed", type=int, default=1000)
    o.add_argument("--avoidance", choices=["on", "off"], default=None)
    o.add_argument("--events", nargs="?", const="key", default=None)
    o.set_defaults(fn=cmd_one)

    rp = sub.add_parser("report", help="build plots, REPORT.md and the PDF from results/")
    common(rp)
    rp.add_argument("--results", default="results")
    rp.set_defaults(fn=cmd_report)

    d = sub.add_parser("dashboard", help="build the self-contained HTML replay dashboard")
    common(d)
    d.add_argument("--out", default="results/dashboard.html")
    d.add_argument("--seed", type=int, default=1000)
    d.set_defaults(fn=cmd_dashboard)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
