"""Rendering layer for streamed graph runs.

Purely a LENS over `graph.stream(..., stream_mode="updates")` — the graph's
own logic (graph.py) knows nothing about presentation. LangGraph Studio
(prompt 11) will be another lens over the exact same graph.

`RichRenderer` draws a breadcrumb of the path taken plus a live-state table,
and a red panel when the graph hits an `interrupt()`. `PlainRenderer` is an
ANSI-only fallback so a missing/broken `rich` install never breaks a run.
"""

NODE_STYLE = {
    "check_schema": ("\U0001f50d", "cyan"),  # 🔍
    "validate_rules": ("\U0001f4cb", "yellow"),  # 📋
    "score": ("⚖️", "magenta"),  # ⚖️
    "optimize": ("\U0001f6e0️", "yellow"),  # 🛠️
    "evaluate": ("\U0001f9ea", "magenta"),  # 🧪
    "recommend": ("\U0001f9e0", "blue"),  # 🧠
    "human_gate": ("⏸️", "red"),  # ⏸️
    "write_ledger": ("\U0001f4be", "green"),  # 💾
}
DEFAULT_STYLE = ("•", "white")  # •

# ASCII-only labels for PlainRenderer — legacy Windows consoles (cp1252) can't
# encode emoji at all, and this renderer's whole reason to exist is to never
# break a run because of the visual layer.
PLAIN_LABEL = {
    "check_schema": "[SCHEMA]",
    "validate_rules": "[VALIDATE]",
    "score": "[SCORE]",
    "optimize": "[OPTIMIZE]",
    "evaluate": "[EVALUATE]",
    "recommend": "[RECOMMEND]",
    "human_gate": "[HUMAN]",
    "write_ledger": "[WRITE]",
}

FLAG_COLOR = {"green": "green", "yellow": "yellow", "red": "red"}

# Internal plumbing (raw rows, scored tuples, the message log) — noisy, not
# meant for the live-state table.
_HIDDEN_FIELDS = {"messages", "_rows", "_scored"}


def _visible(partial: dict) -> dict:
    return {k: v for k, v in partial.items() if k not in _HIDDEN_FIELDS}


class PlainRenderer:
    """ANSI-only fallback — no external dependency, never breaks a run."""

    def __init__(self) -> None:
        self.path: list[str] = []
        self.state: dict = {}

    def update(self, chunk: dict) -> None:
        for node_name, payload in chunk.items():
            if node_name == "__interrupt__":
                self._render_interrupt(payload)
                continue
            self.path.append(node_name)
            self.state.update(_visible(payload))
            self._render_step(node_name)

    def _render_step(self, node_name: str) -> None:
        label = PLAIN_LABEL.get(node_name, node_name)
        print(f"path: {' -> '.join(self.path)}")
        print(label)
        for key, value in self.state.items():
            print(f"  {key}: {self._fmt(value)}")
        print()

    def _render_interrupt(self, payload) -> None:
        print("!! DECISAO NECESSARIA !!")
        print(f"  {payload}")
        print()

    @staticmethod
    def _fmt(value) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)


class RichRenderer:
    """Breadcrumb + live-state table + red interrupt panel, via `rich`."""

    def __init__(self) -> None:
        from rich.console import Console

        self.console = Console()
        self.path: list[str] = []
        self.state: dict = {}

    def update(self, chunk: dict) -> None:
        for node_name, payload in chunk.items():
            if node_name == "__interrupt__":
                self._render_interrupt(payload)
                continue
            self.path.append(node_name)
            self.state.update(_visible(payload))
            self._render_step(node_name)

    def _render_step(self, node_name: str) -> None:
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        breadcrumb = Text()
        for i, name in enumerate(self.path):
            icon, color = NODE_STYLE.get(name, DEFAULT_STYLE)
            if i:
                breadcrumb.append(" -> ", style="dim")
            breadcrumb.append(f"{icon} {name}", style=color)

        table = Table(show_header=True, header_style="bold", expand=True)
        table.add_column("field", style="dim")
        table.add_column("value")
        for key, value in self.state.items():
            table.add_row(key, self._fmt(key, value))

        icon, color = NODE_STYLE.get(node_name, DEFAULT_STYLE)
        self.console.print(Panel(breadcrumb, title=f"{icon} {node_name}", border_style=color))
        self.console.print(table)

    def _render_interrupt(self, payload) -> None:
        from rich.panel import Panel

        self.console.print(
            Panel(
                str(payload),
                title="⏸️  DECISAO NECESSARIA",
                border_style="red",
                style="bold red",
            )
        )

    def _fmt(self, key: str, value):
        from rich.text import Text

        if isinstance(value, bool):
            return Text("✓" if value else "✗", style="green" if value else "red")
        if key == "quality_flag" and value in FLAG_COLOR:
            return Text(str(value), style=f"bold {FLAG_COLOR[value]}")
        return str(value)


def make_renderer(rich: bool = True):
    """Pick RichRenderer, falling back to PlainRenderer if `rich` is unavailable."""
    if rich:
        try:
            return RichRenderer()
        except ImportError:
            pass
    return PlainRenderer()
