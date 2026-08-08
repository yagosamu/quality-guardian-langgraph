"""Tests for the pure scoring logic, the graph's routers, and the LLM
fallback layer. No I/O against the Ledger — these run against plain dicts."""

import pytest

from src.guardian import config, graph, llm, scoring

# --- scoring.evaluate_row / flag_for ------------------------------------------


def test_clean_row_scores_perfect_and_green():
    row = {"id": 1, "email": "a@b.com", "company": "Acme", "n_orders": 2, "failed_orders": 0}
    score, violations = scoring.evaluate_row(row)
    assert score == 1.0
    assert violations == []
    assert scoring.flag_for(score) == "green"


def test_broken_email_penalizes_and_flags_violation():
    row = {"id": 2, "email": "broken", "company": "Acme", "n_orders": 0, "failed_orders": 0}
    score, violations = scoring.evaluate_row(row)
    assert score < 1.0
    assert any("email" in v for v in violations)


def test_failed_orders_penalize_relative_to_a_clean_row():
    clean = {"id": 3, "email": "a@b.com", "company": "Acme", "n_orders": 4, "failed_orders": 0}
    bad = {"id": 4, "email": "a@b.com", "company": "Acme", "n_orders": 4, "failed_orders": 2}
    clean_score, _ = scoring.evaluate_row(clean)
    bad_score, _ = scoring.evaluate_row(bad)
    assert bad_score < clean_score


def test_aggregate_counts_individual_reds():
    rows = [
        {"id": 1, "email": "a@b.com", "company": "Acme", "n_orders": 0, "failed_orders": 0},
        {"id": 2, "email": "broken", "company": None, "n_orders": 2, "failed_orders": 2},
    ]
    result = scoring.aggregate(rows)
    assert result["n_red"] >= 1


# --- graph routers: pure functions of state -----------------------------------


def test_route_after_decide_red_goes_to_human_gate():
    assert graph.route_after_decide({"quality_flag": "red", "hardening": 0}) == "human_gate"


def test_route_after_decide_yellow_with_budget_goes_to_optimize():
    assert graph.route_after_decide({"quality_flag": "yellow", "hardening": 0}) == "optimize"


def test_route_after_decide_yellow_exhausted_goes_to_recommend():
    state = {"quality_flag": "yellow", "hardening": config.MAX_RETRIES}
    assert graph.route_after_decide(state) == "recommend"


def test_route_after_decide_green_goes_to_recommend():
    assert graph.route_after_decide({"quality_flag": "green", "hardening": 0}) == "recommend"


def test_route_after_evaluate_accepted_goes_to_validate_rules():
    state = {"eval_accepted": True, "hardening": 0}
    assert graph.route_after_evaluate(state) == "validate_rules"


def test_route_after_evaluate_rejected_with_budget_goes_to_optimize():
    state = {"eval_accepted": False, "hardening": 0}
    assert graph.route_after_evaluate(state) == "optimize"


def test_route_after_evaluate_exhausted_goes_to_human_gate():
    state = {"eval_accepted": False, "hardening": config.MAX_RETRIES}
    assert graph.route_after_evaluate(state) == "human_gate"


# --- llm fallback layer: forced to run without a key --------------------------


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_recommend_fallback_groups_violations_by_type():
    text, source = llm.recommend(
        "customers", 0.6, "yellow", ["email inválido/ausente", "company nula"]
    )
    assert source == "fallback"
    assert "email" in text
    assert "company" in text


def test_propose_fix_fallback_fixes_email_and_company():
    row = {
        "id": 1,
        "name": "Ana Silva",
        "email": "broken",
        "company": None,
        "n_orders": 0,
        "failed_orders": 0,
    }
    patch, source = llm.propose_fix(row)
    assert source == "fallback"
    assert "@" in patch.get("email", "")
    assert patch.get("company")


def test_judge_fix_fallback_accepts_a_good_patch():
    row = {"id": 1, "email": "broken", "company": None}
    patch = {"email": "ana@example.com", "company": "Ana Ltda"}
    accepted, _reason, source = llm.judge_fix(row, patch)
    assert source == "fallback"
    assert accepted is True


def test_judge_fix_fallback_rejects_a_bad_patch():
    row = {"id": 1, "email": "broken", "company": None}
    patch = {"email": "still-broken"}
    accepted, _reason, source = llm.judge_fix(row, patch)
    assert source == "fallback"
    assert accepted is False
