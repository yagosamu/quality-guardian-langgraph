"""The Quality Guardian state machine.

    START -> check_schema -> validate_rules -> score --[route_after_decide]-->
        red    -> human_gate -> recommend -> write_ledger -> END
        yellow -> optimize -> evaluate --[route_after_evaluate]-->
            accepted           -> validate_rules (loop back, re-score, health rises)
            rejected, budget   -> optimize (loop back, try again)
            rejected, no budget -> human_gate -> recommend -> write_ledger -> END
        green  -> recommend -> write_ledger -> END

Every node is a plain `(state) -> dict` function that returns a partial state
update plus one message describing what it did, so the graph's reasoning is
visible in the `messages` stream. `human_gate` is the one exception: it
pauses the graph for real with `interrupt()` and returns a `Command` instead
of a dict, since it also needs to steer where the graph goes next.
"""

from langchain.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import config, ledger, llm, scoring
from .state import GuardianState


def check_schema(state: GuardianState) -> dict:
    columns = ledger.get_columns(state["dataset"])
    missing = ledger.EXPECTED_COLUMNS - columns
    schema_ok = not missing

    if schema_ok:
        content = f"schema of '{state['dataset']}' ok — all expected columns present"
    else:
        content = f"schema of '{state['dataset']}' missing columns: {sorted(missing)}"

    return {
        "schema_ok": schema_ok,
        "messages": [AIMessage(content=content, name="check_schema")],
    }


def validate_rules(state: GuardianState) -> dict:
    # On re-entry after a successful auto-correction, re-score the corrected
    # rows in-state instead of re-reading the Ledger — that's what makes the
    # health rise visible in the same run, before anything is written back.
    corrected = state.get("corrected_rows")
    rows = corrected if corrected else ledger.read_customers()
    result = scoring.aggregate(rows)

    content = (
        f"validated {len(rows)} rows — health {result['dataset_health']}, "
        f"{result['n_red']} red, {result['n_yellow']} yellow, "
        f"{len(result['violations'])} violations"
    )

    update = {
        "rows_checked": len(rows),
        "rule_violations": result["violations"],
        "health_score": result["dataset_health"],
        "n_red": result["n_red"],
        "n_yellow": result["n_yellow"],
        "_scored": result["scored"],
        "_rows": rows,
        "messages": [AIMessage(content=content, name="validate_rules")],
    }

    if corrected is not None:
        # Consumed — these are single-round scratch fields, not sticky state.
        update["corrected_rows"] = None
        update["eval_accepted"] = None
        update["eval_feedback"] = None

    return update


def score(state: GuardianState) -> dict:
    n_red = state.get("n_red") or 0
    n_yellow = state.get("n_yellow") or 0
    health = state.get("health_score") or 0.0

    # Individual-aware: with a 50-row window, one corrupted customer barely
    # dents the average (~0.99) and would sail through masked. The flag
    # fires on the worst INDIVIDUAL record, not just the batch average.
    if n_red > 0:
        flag = "red"
    elif n_yellow > 0:
        flag = "yellow"
    else:
        flag = scoring.flag_for(health)

    needs_human = flag == "red"
    content = f"quality_flag={flag} (health={health}, n_red={n_red}, n_yellow={n_yellow})"

    return {
        "quality_flag": flag,
        "needs_human": needs_human,
        "messages": [AIMessage(content=content, name="score")],
    }


def optimize(state: GuardianState) -> dict:
    """The weak generator: propose a minimal patch for every non-green row."""
    rows = state.get("_rows") or []
    weak = [r for r in rows if scoring.flag_for(scoring.evaluate_row(r)[0]) != "green"]

    hardening = state.get("hardening", 0)
    feedback = state.get("eval_feedback") or ""

    proposed = []
    sources = set()
    for row in weak:
        patch, source = llm.propose_fix(row, hardening, feedback)
        proposed.append((row["id"], patch))
        sources.add(source)

    content = (
        f"proposed fixes for {len(proposed)} weak row(s) "
        f"(hardening={hardening}, source={'/'.join(sorted(sources)) or 'n/a'})"
    )

    return {
        "proposed_fixes": proposed,
        "messages": [AIMessage(content=content, name="optimize")],
    }


def evaluate(state: GuardianState) -> dict:
    """The strong evaluator: judge each proposal, accept only if it actually
    re-scores green — a patch that "sounds right" but doesn't fix the number
    doesn't count."""
    rows_by_id = {r["id"]: r for r in (state.get("_rows") or [])}
    proposed = state.get("proposed_fixes") or []
    hardening = state.get("hardening", 0)

    accepted: dict[int, dict] = {}
    rejection_reason = None

    for row_id, patch in proposed:
        row = rows_by_id.get(row_id, {})
        judge_accepts, motivo, _source = llm.judge_fix(row, patch)
        rescored_flag = scoring.flag_for(scoring.evaluate_row({**row, **patch})[0])

        if judge_accepts and rescored_flag == "green":
            accepted[row_id] = patch
        else:
            rejection_reason = motivo if not judge_accepts else (
                f"correção do registro {row_id} não elevou a green (ficou {rescored_flag})"
            )

    all_accepted = bool(proposed) and len(accepted) == len(proposed)

    if all_accepted:
        corrected_rows = [
            {**rows_by_id[rid], **patch} if rid in accepted else rows_by_id[rid]
            for rid in rows_by_id
        ]
        content = f"accepted {len(accepted)} fix(es) — re-scoring should raise health"
        return {
            "corrected_rows": corrected_rows,
            "eval_accepted": True,
            "eval_feedback": None,
            "messages": [AIMessage(content=content, name="evaluate")],
        }

    content = f"rejected — {rejection_reason} (hardening {hardening} -> {hardening + 1})"
    return {
        "eval_accepted": False,
        "hardening": hardening + 1,
        "eval_feedback": rejection_reason,
        "messages": [AIMessage(content=content, name="evaluate")],
    }


def recommend(state: GuardianState) -> dict:
    text, source = llm.recommend(
        state["dataset"],
        state.get("health_score"),
        state.get("quality_flag"),
        state.get("rule_violations") or [],
    )
    return {
        "recommendation": text,
        "messages": [AIMessage(content=f"[{source}] {text}", name="recommend")],
    }


def human_gate(state: GuardianState) -> Command:
    # Writing a RED verdict is a risky action — the graph PAUSES here for real
    # and hands control back to a human. `interrupt()` freezes execution at
    # this exact point (thanks to the checkpointer from prompt 06) until
    # `Command(resume=...)` comes in on the same thread_id.
    decision = interrupt(
        {
            "question": (
                f"Dataset '{state['dataset']}' está RED "
                f"(health={state.get('health_score')}). Aprovar gravação?"
            ),
            "violations": state.get("rule_violations") or [],
            "options": ["approve", "override"],
        }
    )

    if decision == "override":
        content = "human override: red downgraded to yellow before write"
        return Command(
            update={
                "human_decision": "override",
                "quality_flag": "yellow",
                "messages": [AIMessage(content=content, name="human_gate")],
            },
            goto="recommend",
        )

    content = "human approved: red flag stands as-is"
    return Command(
        update={
            "human_decision": "approve",
            "messages": [AIMessage(content=content, name="human_gate")],
        },
        goto="recommend",
    )


def write_ledger(state: GuardianState) -> dict:
    ledger.ensure_quality_columns()

    scored = state.get("_scored") or []
    if state.get("human_decision") == "override":
        # The human chose not to write a RED verdict as-is — soften the
        # individually-red records to yellow before persisting.
        scored = [
            (row_id, row_score, "yellow" if flag == "red" else flag)
            for row_id, row_score, flag in scored
        ]

    n_written = ledger.write_scores(scored)
    distribution = ledger.count_by_flag()

    content = f"wrote {n_written} scores — distribution {distribution}"

    return {
        "written": True,
        "messages": [AIMessage(content=content, name="write_ledger")],
    }


def route_after_decide(state: GuardianState) -> str:
    flag = state.get("quality_flag")
    hardening = state.get("hardening", 0)

    if flag == "red":
        return "human_gate"
    if flag == "yellow" and hardening < config.MAX_RETRIES:
        return "optimize"
    return "recommend"


def route_after_evaluate(state: GuardianState) -> str:
    if state.get("eval_accepted"):
        return "validate_rules"
    if state.get("hardening", 0) < config.MAX_RETRIES:
        return "optimize"
    return "human_gate"


def build_graph(checkpointer=None):
    builder = StateGraph(GuardianState)

    builder.add_node("check_schema", check_schema)
    builder.add_node("validate_rules", validate_rules)
    builder.add_node("score", score)
    builder.add_node("optimize", optimize)
    builder.add_node("evaluate", evaluate)
    builder.add_node("recommend", recommend)
    builder.add_node("human_gate", human_gate)
    builder.add_node("write_ledger", write_ledger)

    builder.add_edge(START, "check_schema")
    builder.add_edge("check_schema", "validate_rules")
    builder.add_edge("validate_rules", "score")

    builder.add_conditional_edges(
        "score",
        route_after_decide,
        {"optimize": "optimize", "human_gate": "human_gate", "recommend": "recommend"},
    )

    builder.add_edge("optimize", "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"validate_rules": "validate_rules", "optimize": "optimize", "human_gate": "human_gate"},
    )

    # No static edge out of human_gate: it always returns Command(goto=...),
    # which controls routing directly (to "recommend", in both branches).
    builder.add_edge("recommend", "write_ledger")
    builder.add_edge("write_ledger", END)

    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
