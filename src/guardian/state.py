"""Graph state for the Quality Guardian agent.

`GuardianState` is the working memory every node reads and partially updates.
Fields annotated with a reducer (`add_messages`) are merged by LangGraph;
plain fields are overwritten by whatever a node returns for them.
"""

from typing import Annotated, Literal, Optional

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class GuardianState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

    dataset: str

    # check_schema
    schema_ok: Optional[bool]

    # validate_rules
    rows_checked: Optional[int]
    rule_violations: Optional[list[str]]

    # score — per-record counts that drive the flow (a red average can hide individual reds)
    n_red: Optional[int]
    n_yellow: Optional[int]
    health_score: Optional[float]
    quality_flag: Optional[Literal["green", "yellow", "red"]]
    recommendation: Optional[str]

    # carried between nodes, not user-facing
    _scored: Optional[list]  # [(id, score, flag)] for write_ledger
    _rows: Optional[list]  # raw rows for the optimizer

    # evaluator-optimizer (prompt 05)
    hardening: int  # number of times the evaluator has rejected a proposal
    proposed_fixes: Optional[list]  # [(id, patch)] from the generator
    eval_feedback: Optional[str]  # rejection reason, fed back to the generator
    eval_accepted: Optional[bool]
    corrected_rows: Optional[list]  # rows patched in-state, for re-scoring

    # control / human-in-the-loop
    retries: int
    needs_human: bool
    human_decision: Optional[str]
    written: Optional[bool]


def initial_state(dataset: str = "customers") -> GuardianState:
    return GuardianState(
        messages=[],
        dataset=dataset,
        schema_ok=None,
        rows_checked=None,
        rule_violations=None,
        n_red=None,
        n_yellow=None,
        health_score=None,
        quality_flag=None,
        recommendation=None,
        _scored=None,
        _rows=None,
        hardening=0,
        proposed_fixes=None,
        eval_feedback=None,
        eval_accepted=None,
        corrected_rows=None,
        retries=0,
        needs_human=False,
        human_decision=None,
        written=None,
    )
