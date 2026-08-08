"""Programmatic API for the Quality Guardian.

This is the surface the MCP server (prompt 09) and the Chainlit UI (prompt 10)
consume instead of the CLI: a plain function call that runs the graph and
returns a structured result, transparently handling the paused/human-in-the-
loop case instead of leaving callers to parse a text stream.
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from . import config
from .graph import build_graph
from .state import initial_state

CHECKPOINT_DB = "guardian_checkpoints.db"


@dataclass
class GuardianResult:
    dataset: str
    thread_id: str
    status: str  # "completed" | "paused"
    steps: list[str]
    health_score: Optional[float]
    quality_flag: Optional[str]
    n_red: Optional[int]
    rows_checked: Optional[int]
    interrupt: Optional[dict]

    def summary(self) -> str:
        if self.status == "paused":
            question = (self.interrupt or {}).get("question", "aprovação necessária")
            return (
                f"[{self.dataset}/{self.thread_id}] PAUSADO — {question} "
                f"(health={self.health_score}, flag={self.quality_flag})"
            )
        return (
            f"[{self.dataset}/{self.thread_id}] CONCLUÍDO — health={self.health_score}, "
            f"flag={self.quality_flag}, n_red={self.n_red}, rows={self.rows_checked}"
        )


def _checkpointer() -> SqliteSaver:
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    return SqliteSaver(conn)


def _collect(graph, stream_input, run_config: dict) -> GuardianResult:
    steps: list[str] = []
    interrupt_payload: Optional[dict] = None

    for chunk in graph.stream(stream_input, run_config, stream_mode="updates"):
        for node_name, payload in chunk.items():
            if node_name == "__interrupt__":
                value = payload[0].value
                interrupt_payload = value if isinstance(value, dict) else {"value": value}
            else:
                steps.append(node_name)

    snap = graph.get_state(run_config)
    values = snap.values
    status = "paused" if snap.next else "completed"

    return GuardianResult(
        dataset=values.get("dataset"),
        thread_id=run_config["configurable"]["thread_id"],
        status=status,
        steps=steps,
        health_score=values.get("health_score"),
        quality_flag=values.get("quality_flag"),
        n_red=values.get("n_red"),
        rows_checked=values.get("rows_checked"),
        interrupt=interrupt_payload if status == "paused" else None,
    )


def run_guardian(
    dataset: str = "customers",
    thread_id: str = "default",
    auto_approve: Optional[str] = None,
) -> GuardianResult:
    """Run the graph end-to-end against the Ledger and return a structured result.

    If the run pauses (RED) and `auto_approve` is "approve" or "override",
    immediately resumes with that decision — for non-interactive callers
    (tests, scheduled jobs) that already know their policy. Otherwise the
    result comes back with `status="paused"` and the interrupt payload for
    a caller (MCP tool, UI) to act on.
    """
    compiled = build_graph(checkpointer=_checkpointer())
    run_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": config.RECURSION_LIMIT,
    }

    result = _collect(compiled, initial_state(dataset), run_config)

    if result.status == "paused" and auto_approve in ("approve", "override"):
        return resume_guardian(thread_id, auto_approve)

    return result


def resume_guardian(thread_id: str, decision: str = "approve") -> GuardianResult:
    """Feed a human decision back into a paused thread and continue it."""
    compiled = build_graph(checkpointer=_checkpointer())
    run_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": config.RECURSION_LIMIT,
    }

    return _collect(compiled, Command(resume=decision), run_config)
