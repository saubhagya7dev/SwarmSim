"""Batch runner: scenarios x controllers x seeds, in parallel, with criteria verdicts."""
from __future__ import annotations

import csv
import glob
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import deep_merge, load_scenario
from .criteria import effective_rules, evaluate, load_criteria
from .metrics import compute_metrics
from .simulation import SimResult, run_simulation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCENARIOS = os.path.join(ROOT, "scenarios")
DEFAULT_CRITERIA = os.path.join(ROOT, "criteria", "criteria.yaml")
CONTROLLERS = ("leader_follower", "consensus")

Task = Tuple[str, str, int, Optional[bool], str]


def list_scenarios(directory: str = DEFAULT_SCENARIOS) -> List[str]:
    paths = sorted(glob.glob(os.path.join(directory, "*.yaml")))
    if not paths:
        raise FileNotFoundError(f"no scenario YAML files in {directory}")
    return paths


def prepare_cfg(scenario_path: str, controller: str, avoidance: Optional[bool]) -> Dict[str, Any]:
    cfg = load_scenario(scenario_path)
    cfg["controller"] = controller
    if avoidance is not None:
        cfg = deep_merge(cfg, {"safety": {"avoidance": bool(avoidance)}})
    return cfg


def run_one(task: Task) -> Dict[str, Any]:
    """Run a single trial and return one flat result row (picklable)."""
    scenario_path, controller, seed, avoidance, criteria_path = task
    cfg = prepare_cfg(scenario_path, controller, avoidance)
    criteria = load_criteria(criteria_path)
    res = run_simulation(cfg, seed=seed)
    metrics = compute_metrics(res, criteria["evaluation"])
    rules = effective_rules(criteria, cfg)
    passed, details = evaluate(metrics, rules)
    failed = [d["criterion"] + ":" + d["why"] for d in details if not d["passed"]]
    row: Dict[str, Any] = {
        "scenario": cfg["name"], "controller": controller, "seed": seed,
        "avoidance": bool(cfg["safety"]["avoidance"]), "passed": passed,
        "failed_criteria": ";".join(failed),
    }
    row.update(metrics)
    return row


def run_suite(scenarios: Iterable[str], controllers: Iterable[str], trials: int, workers: int,
              out_dir: str, criteria_path: str = DEFAULT_CRITERIA, base_seed: int = 1000,
              avoidance: Optional[bool] = None, label: str = "trials", quiet: bool = False
              ) -> List[Dict[str, Any]]:
    scenarios = list(scenarios)
    controllers = list(controllers)
    tasks: List[Task] = [(sp, c, base_seed + i, avoidance, criteria_path)
                         for sp in scenarios for c in controllers for i in range(trials)]
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    rows: List[Dict[str, Any]] = []
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for k, row in enumerate(ex.map(run_one, tasks, chunksize=4), 1):
                rows.append(row)
                if not quiet and (k % 60 == 0 or k == len(tasks)):
                    print(f"  [{label}] {k}/{len(tasks)} trials  ({time.time() - t0:.0f}s)", flush=True)
    else:
        for k, task in enumerate(tasks, 1):
            rows.append(run_one(task))
            if not quiet and (k % 60 == 0 or k == len(tasks)):
                print(f"  [{label}] {k}/{len(tasks)} trials  ({time.time() - t0:.0f}s)", flush=True)
    write_csv(os.path.join(out_dir, f"{label}.csv"), rows)
    return rows


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_csv(path: str) -> List[Dict[str, Any]]:
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            row: Dict[str, Any] = {}
            for k, v in r.items():
                if v in ("True", "False"):
                    row[k] = (v == "True")
                else:
                    try:
                        row[k] = int(v) if v.lstrip("-").isdigit() else float(v)
                    except (ValueError, AttributeError):
                        row[k] = v
            out.append(row)
    return out


# ------------------------------------------------------------------ statistics
def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def percentile(vals: List[float], q: float) -> float:
    xs = sorted(v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v)))
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q / 100.0
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if math.isinf(xs[lo]) or math.isinf(xs[hi]):
        return float("inf") if xs[hi] == float("inf") and pos > lo else xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarize(rows: List[Dict[str, Any]], required_pass_rate: float) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str, bool], List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["scenario"], r["controller"], bool(r["avoidance"])), []).append(r)
    out = []
    for (scen, ctrl, av), rs in sorted(groups.items()):
        n = len(rs)
        k = sum(1 for r in rs if r["passed"])
        lo, hi = wilson(k, n)

        def col(name: str) -> List[float]:
            return [r[name] for r in rs if name in r]
        fail_counts: Dict[str, int] = {}
        for r in rs:
            for item in str(r.get("failed_criteria", "")).split(";"):
                if item:
                    key = item.split(":")[0]
                    fail_counts[key] = fail_counts.get(key, 0) + 1
        out.append({
            "scenario": scen, "controller": ctrl, "avoidance": av, "trials": n, "passes": k,
            "pass_rate": k / n, "ci_low": lo, "ci_high": hi,
            "verdict": "PASS" if (k / n) >= required_pass_rate else "FAIL",
            "min_separation_min": min(col("min_separation_m")),
            "min_separation_p5": percentile(col("min_separation_m"), 5),
            "collision_trials": sum(1 for r in rs if r["collision_events"] > 0),
            "detection_p50": percentile(col("detection_time_s"), 50),
            "detection_p95": percentile(col("detection_time_s"), 95),
            "recovery_p50": percentile(col("recovery_time_s"), 50),
            "recovery_p95": percentile(col("recovery_time_s"), 95),
            "rejoin_p50": percentile(col("rejoin_time_s"), 50),
            "rejoin_p95": percentile(col("rejoin_time_s"), 95),
            "steady_error_p50": percentile(col("steady_error_p95_m"), 50),
            "steady_error_p95": percentile(col("steady_error_p95_m"), 95),
            "mission_complete_rate": sum(1 for r in rs if r["mission_complete"]) / n,
            "false_alarm_trials": sum(1 for r in rs if r["false_peer_loss_events"] > 0),
            "geofence_breach_trials": sum(1 for r in rs if r["geofence_breach"]),
            "mean_survivors": sum(col("survivors_at_end")) / n,
            "fail_reasons": fail_counts,
        })
    return out


def write_summary(path_json: str, summary: List[Dict[str, Any]]) -> None:
    def clean(o):
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
            return None if math.isnan(o) else "inf"
        return o
    with open(path_json, "w", encoding="utf-8") as fh:
        json.dump([{k: clean(v) for k, v in s.items()} for s in summary], fh, indent=2)
