"""Acceptance criteria: load, merge per scenario, evaluate against trial metrics."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from .config import deep_merge, load_yaml

Rule = Dict[str, Any]


def load_criteria(path: str) -> Dict[str, Any]:
    c = load_yaml(path)
    for key in ("defaults", "evaluation", "required_pass_rate"):
        if key not in c:
            raise ValueError(f"criteria file {path} is missing '{key}'")
    for name, rule in c["defaults"].items():
        _check_rule(name, rule)
    return c


def _check_rule(name: str, rule: Rule) -> None:
    if not isinstance(rule, dict) or not (set(rule) & {"min", "max", "equals"}) \
            or set(rule) - {"min", "max", "equals"}:
        raise ValueError(f"criterion '{name}' must be a dict with min/max/equals, got {rule!r}")


def effective_rules(criteria: Dict[str, Any], scenario_cfg: Dict[str, Any]) -> Dict[str, Rule]:
    rules = deep_merge(criteria["defaults"], scenario_cfg.get("criteria", {}) or {})
    n = scenario_cfg["n_drones"]
    rules["survivors_at_end"] = {"min": n - int(scenario_cfg.get("allowed_losses", 0))}
    for name, rule in rules.items():
        _check_rule(name, rule)
    return rules


def evaluate(metrics: Dict[str, Any], rules: Dict[str, Rule]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Return (all passed, per-criterion details). Missing/NaN data fails the criterion."""
    details = []
    ok_all = True
    for name, rule in rules.items():
        v = metrics.get(name)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            passed, why = False, "no data"
        else:
            passed, why = True, ""
            if "min" in rule and not (v >= rule["min"]):
                passed, why = False, f"{_fmt(v)} < min {rule['min']}"
            if "max" in rule and not (v <= rule["max"]):
                passed, why = False, f"{_fmt(v)} > max {rule['max']}"
            if "equals" in rule:
                exp = rule["equals"]
                ok = (bool(v) == exp) if isinstance(exp, bool) else (v == exp)
                if not ok:
                    passed, why = False, f"{_fmt(v)} != {exp}"
        details.append({"criterion": name, "value": v, "rule": rule, "passed": passed, "why": why})
        ok_all = ok_all and passed
    return ok_all, details


def _fmt(v: Any) -> str:
    return f"{v:.3g}" if isinstance(v, float) else str(v)
