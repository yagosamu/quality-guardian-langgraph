"""Entry point for running the MCP server: `python -m src.mcp.run` or the `dataops-mcp` console script."""

import asyncio

from src.mcp.server import run_server


def main() -> None:
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
