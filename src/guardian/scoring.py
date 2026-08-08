"""Data quality scoring rules — pure logic, no I/O, no LLM.

Kept in its own module so it's testable in isolation and reads cleanly on a
slide. The graph's `score` node is a thin wrapper around `aggregate`.
"""

from . import config


def evaluate_row(row: dict) -> tuple[float, list[str]]:
    """Score a single customer row in [0, 1] and list the rule violations found."""
    score = 1.0
    violations: list[str] = []

    email = row.get("email")
    if not email or "@" not in email:
        score -= 0.5
        violations.append("email inválido/ausente")

    if not row.get("company"):
        score -= 0.15
        violations.append("company nula")

    n_orders = row.get("n_orders") or 0
    failed_orders = row.get("failed_orders") or 0
    if n_orders > 0:
        fail_ratio = failed_orders / n_orders
        if fail_ratio > 0:
            score -= min(0.4, fail_ratio)
            violations.append(f"{fail_ratio:.0%} dos pedidos falharam")

    return max(0.0, round(score, 3)), violations


def flag_for(score: float) -> str:
    """Map a score to green/yellow/red using the configured thresholds."""
    if score >= config.GREEN_AT:
        return "green"
    if score >= config.YELLOW_AT:
        return "yellow"
    return "red"


def aggregate(rows: list[dict]) -> dict:
    """Score a batch of rows and summarize the dataset's health.

    `n_red`/`n_yellow` count individual flagged records — the dataset average
    can hide a red row inside an otherwise healthy batch, so downstream
    routing must key off these counts, not just `dataset_health`.
    """
    scored: list[tuple[int, float, str]] = []
    all_violations: list[str] = []
    n_red = 0
    n_yellow = 0

    for row in rows:
        score, violations = evaluate_row(row)
        flag = flag_for(score)
        scored.append((row["id"], score, flag))
        all_violations.extend(violations)
        if flag == "red":
            n_red += 1
        elif flag == "yellow":
            n_yellow += 1

    dataset_health = round(sum(s for _, s, _ in scored) / len(scored), 3) if scored else 0.0

    return {
        "scored": scored,
        "violations": all_violations,
        "dataset_health": dataset_health,
        "dataset_flag": flag_for(dataset_health),
        "n_red": n_red,
        "n_yellow": n_yellow,
    }
