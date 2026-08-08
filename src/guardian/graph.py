"""The Quality Guardian state machine — version 1: a straight line.

START -> check_schema -> validate_rules -> score -> write_ledger -> END

No branching, no cycles yet. Every node is a plain `(state) -> dict` function
that returns a partial state update plus one message describing what it did,
so the graph's reasoning is visible in the `messages` stream.
"""

from langchain.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from . import ledger, scoring
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
    rows = ledger.read_customers()
    result = scoring.aggregate(rows)

    content = (
        f"validated {len(rows)} rows — health {result['dataset_health']}, "
        f"{result['n_red']} red, {result['n_yellow']} yellow, "
        f"{len(result['violations'])} violations"
    )

    return {
        "rows_checked": len(rows),
        "rule_violations": result["violations"],
        "health_score": result["dataset_health"],
        "n_red": result["n_red"],
        "n_yellow": result["n_yellow"],
        "_scored": result["scored"],
        "_rows": rows,
        "messages": [AIMessage(content=content, name="validate_rules")],
    }


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


def write_ledger(state: GuardianState) -> dict:
    ledger.ensure_quality_columns()
    n_written = ledger.write_scores(state["_scored"])
    distribution = ledger.count_by_flag()

    content = f"wrote {n_written} scores — distribution {distribution}"

    return {
        "written": True,
        "messages": [AIMessage(content=content, name="write_ledger")],
    }


def build_graph(checkpointer=None):
    builder = StateGraph(GuardianState)

    builder.add_node("check_schema", check_schema)
    builder.add_node("validate_rules", validate_rules)
    builder.add_node("score", score)
    builder.add_node("write_ledger", write_ledger)

    builder.add_edge(START, "check_schema")
    builder.add_edge("check_schema", "validate_rules")
    builder.add_edge("validate_rules", "score")
    builder.add_edge("score", "write_ledger")
    builder.add_edge("write_ledger", END)

    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
