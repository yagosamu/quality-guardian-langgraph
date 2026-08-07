"""MCP server exposing the DataOps Knowledge Hub (FastAPI app) as tools for AI agents.

Communicates over stdio, per the MCP spec's local-agent transport. Every tool is a
thin HTTP client call into the already-running FastAPI app (src/api) -- this server
does not talk to the engines or databases directly.
"""

import logging
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
HTTP_TIMEOUT_SECONDS = 60.0


def _format_query_response(data: dict) -> str:
    text = f"## Answer\n\n{data['answer']}\n\n"
    if data.get("recommendation"):
        text += f"## Recommendation\n\n{data['recommendation']}\n\n"
    text += "## Sources Consulted\n\n"
    for source in data["sources_consulted"]:
        text += f"- **{source['source']}** ({source['data_store']}): {source['result_summary']}\n"
        text += f"  Query: `{source['query_used']}`\n"
    text += f"\n_Processing time: {data['processing_time_ms']:.0f}ms_"
    return text


def _format_health_response(data: dict) -> str:
    lines = [f"## Platform Health: {data['status'].upper()}", ""]
    for service, status in data["services"].items():
        lines.append(f"- **{service}**: {status}")
    lines.append("")
    lines.append(f"_Uptime: {data['uptime_seconds']:.0f}s | Version: {data['version']}_")
    return "\n".join(lines)


def _format_ingestion_response(data: dict) -> str:
    return f"**{data.get('status', 'unknown')}**: {data.get('message', '')}"


def create_server() -> Server:
    """Build the MCP server with its tools and handlers registered."""
    server = Server("dataops-knowledge-hub")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="query_knowledge_hub",
                description=(
                    "Query the DataOps Knowledge Hub — an enterprise RAG system that searches "
                    "across 3 data stores: PostgreSQL (factual/numerical data about customers, "
                    "orders, products), Qdrant (policies, SLAs, runbooks, incident logs), and "
                    "Neo4j (pipeline lineage, table dependencies, team ownership). The system "
                    "automatically routes your question to the appropriate engine(s) and "
                    "returns a synthesized answer with sources and recommendations."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Natural language question about the data platform",
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["ledger", "memory", "brain"]},
                            "description": "Optional: restrict search to specific engines. Omit to search all.",
                        },
                    },
                    "required": ["question"],
                },
            ),
            Tool(
                name="check_platform_health",
                description=(
                    "Check the health status of all services in the DataOps Knowledge Hub: "
                    "PostgreSQL, Qdrant, Neo4j, MongoDB, and SeaweedFS. Returns the status of "
                    "each service and overall platform health."
                ),
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="trigger_ingestion",
                description=(
                    "Trigger a re-ingestion of all data sources (SeaweedFS documents + MongoDB "
                    "logs) into the Memory engine (Qdrant). Use this after new documents have "
                    "been added or when you want to refresh the search index."
                ),
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                if name == "query_knowledge_hub":
                    response = await client.post(f"{API_BASE_URL}/api/v1/query", json=arguments)
                    response.raise_for_status()
                    text = _format_query_response(response.json())
                elif name == "check_platform_health":
                    response = await client.get(f"{API_BASE_URL}/health")
                    response.raise_for_status()
                    text = _format_health_response(response.json())
                elif name == "trigger_ingestion":
                    response = await client.post(f"{API_BASE_URL}/api/v1/ingest")
                    response.raise_for_status()
                    text = _format_ingestion_response(response.json())
                else:
                    text = f"Unknown tool: {name}"
        except httpx.HTTPError as exc:
            logger.error("HTTP error calling tool %r: %s", name, exc)
            text = f"Failed to reach the DataOps Knowledge Hub API ({API_BASE_URL}): {exc}"

        return [TextContent(type="text", text=text)]

    return server


async def run_server() -> None:
    """Run the MCP server over stdio until the client disconnects."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
