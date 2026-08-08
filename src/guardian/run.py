"""CLI: draw the state machine, or run it end-to-end against the real Ledger.

    python -m src.guardian.run draw
    python -m src.guardian.run run [--thread ID] [--plain] [--dataset customers]
    python -m src.guardian.run resume --thread ID --decision approve|override [--plain]
"""

import argparse
import sqlite3
import sys
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from . import config
from .graph import build_graph
from .render import make_renderer
from .state import initial_state

CHECKPOINT_DB = "guardian_checkpoints.db"

# Legacy Windows consoles (cp1252) raise UnicodeEncodeError on the emoji the
# renderers use, even with `rich` installed — reconfigure to UTF-8 so a run
# never crashes on the visual layer. Best-effort: no-op on stdio that doesn't
# support reconfigure (e.g. when captured/piped in some environments).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _checkpointer() -> SqliteSaver:
    """Durable per-thread state, in a local SQLite file.

    A `PostgresSaver` pointed at the same W01 Postgres would work the same
    way (`from_conn_string(...)` + `.setup()` once) — SQLite is enough for
    the workshop and needs no extra service.
    """
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    return SqliteSaver(conn)


def _report_state(compiled, run_config: dict) -> None:
    snap = compiled.get_state(run_config)
    thread_id = run_config["configurable"]["thread_id"]
    if snap.next:
        print(f"[PAUSADO em {snap.next}]")
        print(f"  retome com: python -m src.guardian.run resume --thread {thread_id} --decision approve")
    else:
        print("[CONCLUÍDO]")


def _draw() -> None:
    compiled = build_graph()
    print(compiled.get_graph().draw_ascii())
    print()
    print(compiled.get_graph().draw_mermaid())


def _run(thread: str | None, plain: bool, dataset: str) -> None:
    compiled = build_graph(checkpointer=_checkpointer())
    renderer = make_renderer(rich=not plain)

    thread_id = thread or str(uuid.uuid4())
    run_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": config.RECURSION_LIMIT,
    }
    print(f"thread_id={thread_id}")

    for chunk in compiled.stream(initial_state(dataset), run_config, stream_mode="updates"):
        renderer.update(chunk)

    _report_state(compiled, run_config)


def _resume(thread: str, decision: str, plain: bool) -> None:
    # human_gate is still a stub (real interrupt() lands in prompt 07) — this
    # subcommand exists now so the CLI surface is already in place. Once the
    # graph actually pauses, this is how a human unblocks it on the same
    # thread_id, from the exact checkpoint it stopped at.
    compiled = build_graph(checkpointer=_checkpointer())
    renderer = make_renderer(rich=not plain)

    run_config = {
        "configurable": {"thread_id": thread},
        "recursion_limit": config.RECURSION_LIMIT,
    }
    print(f"thread_id={thread} resume decision={decision}")

    for chunk in compiled.stream(Command(resume=decision), run_config, stream_mode="updates"):
        renderer.update(chunk)

    _report_state(compiled, run_config)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.guardian.run")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("draw", help="print the graph as ASCII + mermaid")

    run_parser = subcommands.add_parser("run", help="run the graph against the W01 Ledger")
    run_parser.add_argument("--thread", default=None, help="checkpoint thread id (default: random)")
    run_parser.add_argument("--plain", action="store_true", help="force the plain ANSI renderer")
    run_parser.add_argument("--dataset", default="customers")

    resume_parser = subcommands.add_parser(
        "resume", help="resume a paused thread (human-in-the-loop, wired up in prompt 07)"
    )
    resume_parser.add_argument("--thread", required=True, help="checkpoint thread id to resume")
    resume_parser.add_argument("--decision", required=True, choices=["approve", "override"])
    resume_parser.add_argument("--plain", action="store_true")

    args = parser.parse_args()

    if args.command == "draw":
        _draw()
    elif args.command == "run":
        _run(args.thread, args.plain, args.dataset)
    elif args.command == "resume":
        _resume(args.thread, args.decision, args.plain)


if __name__ == "__main__":
    main()
