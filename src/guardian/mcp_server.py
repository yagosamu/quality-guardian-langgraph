"""Exposes the Quality Guardian agent (graph + HITL + checkpoint) as an MCP
server — 3 tools any MCP-aware LLM (Claude Code/Desktop, the W03 Crew) can
call in natural language, over stdio.
"""

from mcp.server.fastmcp import FastMCP

from . import ledger
from .api import resume_guardian, run_guardian

mcp = FastMCP("quality-guardian")


@mcp.tool()
def validate_dataset(dataset: str = "customers", thread_id: str = "mcp") -> str:
    """Run the Quality Guardian graph against a dataset in the W01 Ledger.

    Validates the most recent window of records, scores them, and either
    writes the result straight to the Ledger (green/yellow) or PAUSES for
    human approval (red) — a risky verdict is never written unattended.
    If it pauses, call `resume_validation` with the same thread_id and a
    decision ("approve" or "override") to unblock it.
    """
    result = run_guardian(dataset=dataset, thread_id=thread_id)
    lines = [result.summary(), f"steps: {' -> '.join(result.steps)}"]
    if result.status == "paused":
        lines.append(
            f"Chame resume_validation(thread_id='{thread_id}', decision='approve') "
            "(ou 'override') para prosseguir."
        )
    return "\n".join(lines)


@mcp.tool()
def resume_validation(thread_id: str, decision: str = "approve") -> str:
    """Resume a Quality Guardian run that paused for human approval.

    `decision` is "approve" (keep the red verdict as-is) or "override"
    (downgrade it to yellow before writing). Must use the same thread_id
    that `validate_dataset` reported as paused.
    """
    result = resume_guardian(thread_id, decision)
    return "\n".join([result.summary(), f"steps: {' -> '.join(result.steps)}"])


@mcp.tool()
def quality_report() -> str:
    """Report the current quality_flag distribution across the whole Ledger.

    Highlights how many customers are RED — that count is the trigger the
    W03 Crew (Monitor -> Diagnostician -> Remediator -> Reporter) watches
    for.
    """
    distribution = ledger.count_by_flag()
    n_red = distribution.get("red", 0)
    lines = ["quality_flag distribution:"]
    for flag, count in sorted(distribution.items(), key=lambda kv: (kv[0] is None, kv[0])):
        lines.append(f"  {flag or '(não avaliado)'}: {count}")
    lines.append(f"-> {n_red} red — trigger do W03" if n_red else "-> nenhum red no momento")
    return "\n".join(lines)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
