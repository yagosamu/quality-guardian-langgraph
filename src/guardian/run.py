"""CLI: draw the state machine, or run it end-to-end against the real Ledger.

    python -m src.guardian.run draw
    python -m src.guardian.run run [--thread ID] [--plain] [--dataset customers]
"""

import argparse
import sys
import uuid

from . import config
from .graph import build_graph
from .render import make_renderer
from .state import initial_state

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


def _draw() -> None:
    compiled = build_graph()
    print(compiled.get_graph().draw_ascii())
    print()
    print(compiled.get_graph().draw_mermaid())


def _run(thread: str | None, plain: bool, dataset: str) -> None:
    compiled = build_graph()
    renderer = make_renderer(rich=not plain)

    thread_id = thread or str(uuid.uuid4())
    run_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": config.RECURSION_LIMIT,
    }
    print(f"thread_id={thread_id}")

    for chunk in compiled.stream(initial_state(dataset), run_config, stream_mode="updates"):
        renderer.update(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.guardian.run")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("draw", help="print the graph as ASCII + mermaid")

    run_parser = subcommands.add_parser("run", help="run the graph against the W01 Ledger")
    run_parser.add_argument("--thread", default=None, help="checkpoint thread id (default: random)")
    run_parser.add_argument("--plain", action="store_true", help="force the plain ANSI renderer")
    run_parser.add_argument("--dataset", default="customers")

    args = parser.parse_args()

    if args.command == "draw":
        _draw()
    elif args.command == "run":
        _run(args.thread, args.plain, args.dataset)


if __name__ == "__main__":
    main()
