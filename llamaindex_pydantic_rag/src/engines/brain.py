"""Brain engine: LLM-generated Cypher executed against Neo4j, synthesized to natural language.

Uses custom Cypher generation (rather than KnowledgeGraphQueryEngine/PropertyGraphIndex)
since the graph was seeded directly via infra/scripts/init-neo4j.cypher, not through
LlamaIndex's own graph-extraction pipeline — a hand-written schema-aware prompt gives
more reliable control over the exact node/relationship vocabulary already in the graph.
"""

import asyncio
import logging
import re
from typing import Any, Optional

from llama_index.llms.openai import OpenAI
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError
from neo4j.graph import Node, Path, Relationship

from src.engines._text import clean_llm_text
from src.engines.config import EngineConfig
from src.schemas.domain import DependencyChain
from src.schemas.query import BrainQueryResult

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_SECONDS = 30

GRAPH_SCHEMA = """Nodes: Team, Pipeline, Table, Dashboard
Node properties:
- Team: name, slack_channel
- Pipeline: name, schedule, owner, sla_minutes
- Table: name, schema, database, row_count
- Dashboard: name, tool, owner, refresh_frequency

Relationships: OWNS, READS_FROM, WRITES_TO, FEEDS, USED_BY
- (Team)-[:OWNS]->(Pipeline|Table)
- (Pipeline)-[:READS_FROM]->(Table)
- (Pipeline)-[:WRITES_TO]->(Table)
- (Pipeline)-[:FEEDS]->(Pipeline)
- (Table)-[:USED_BY]->(Dashboard)"""

EXAMPLE_QUERIES = """Example questions and their Cypher:
"What pipelines does team-billing own?"
MATCH (t:Team {name:'team-billing'})-[:OWNS]->(p:Pipeline) RETURN p.name

"What happens if orders table goes down?"
MATCH (t:Table {name:'orders'})<-[:READS_FROM|WRITES_TO*1..3]-(downstream) RETURN downstream

"Show lineage of fact_revenue"
MATCH path=(source)-[:READS_FROM|WRITES_TO|FEEDS*]->(t:Table {name:'fact_revenue'}) RETURN path"""

CYPHER_GEN_PROMPT = f"""You are an expert Neo4j Cypher developer for the DataOps Knowledge Hub graph.

Graph schema:
{GRAPH_SCHEMA}

{EXAMPLE_QUERIES}

Generate ONLY a single valid Cypher query (no explanation, no markdown fences) that answers
the user's question below. Prefer returning full nodes or paths (not just names) when the
question is about impact, dependencies, or lineage, so the structure can be inspected.

Question: __QUESTION__

Cypher query:"""

DEPENDENCY_KEYWORDS = ("impact", "downstream", "depend", "affect", "lineage", "goes down", "breaks")


class BrainEngine:
    """Graph traversal query engine over Neo4j (the Brain)."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self.llm = OpenAI(model=config.llm_model, api_key=config.openai_api_key, timeout=QUERY_TIMEOUT_SECONDS)
        self._driver = AsyncGraphDatabase.driver(
            config.neo4j_uri, auth=(config.neo4j_user, config.neo4j_password)
        )

    async def close(self):
        await self._driver.close()

    async def _generate_cypher(self, question: str) -> str:
        prompt = CYPHER_GEN_PROMPT.replace("__QUESTION__", question)
        response = await self.llm.acomplete(prompt)
        cypher = response.text.strip()
        return re.sub(r"^```(?:cypher)?\s*|\s*```$", "", cypher, flags=re.IGNORECASE).strip()

    async def _execute_cypher(self, cypher: str) -> list[dict]:
        # dict(record) preserves neo4j's native Node/Relationship/Path objects as
        # values; record.data() would flatten them into plain dicts, losing the
        # labels/types/paths this engine needs to introspect.
        async with self._driver.session() as session:
            result = await session.run(cypher)
            return [dict(record) async for record in result]

    async def _summarize(self, question: str, cypher: str, records: list[dict]) -> str:
        prompt = (
            f"Question: {question}\n"
            f"Cypher executed: {cypher}\n"
            f"Raw results ({len(records)} records): {records[:20]}\n\n"
            "Write a concise, natural-language answer to the question based on these results. "
            "If the results are empty, say so plainly."
        )
        response = await self.llm.acomplete(prompt)
        return clean_llm_text(response.text.strip())

    @staticmethod
    def _flatten_graph_objects(value: Any) -> list:
        """Unpack a raw record value into the Node/Relationship objects it contains,
        recursing into lists and Path objects (whose .nodes/.relationships hold the
        actual graph entities).
        """
        if isinstance(value, Path):
            return list(value.nodes) + list(value.relationships)
        if isinstance(value, (Node, Relationship)):
            return [value]
        if isinstance(value, list):
            flattened: list = []
            for item in value:
                flattened.extend(BrainEngine._flatten_graph_objects(item))
            return flattened
        return []

    def _iter_graph_objects(self, records: list[dict]):
        for record in records:
            for value in record.values():
                yield from self._flatten_graph_objects(value)

    def _count_nodes(self, records: list[dict]) -> int:
        seen_ids = {obj.element_id for obj in self._iter_graph_objects(records) if isinstance(obj, Node)}
        return len(seen_ids) if seen_ids else len(records)

    def _extract_relationships(self, records: list[dict]) -> list[str]:
        rel_types = [obj.type for obj in self._iter_graph_objects(records) if isinstance(obj, Relationship)]
        return list(dict.fromkeys(rel_types))

    def _build_dependency_chain(self, question: str, records: list[dict]) -> Optional[DependencyChain]:
        if not any(kw in question.lower() for kw in DEPENDENCY_KEYWORDS):
            return None

        downstream_pipelines: set = set()
        downstream_tables: set = set()
        downstream_dashboards: set = set()
        impacted_teams: set = set()

        for obj in self._iter_graph_objects(records):
            if not isinstance(obj, Node):
                continue
            name = obj.get("name")
            if not name:
                continue
            if "Pipeline" in obj.labels:
                downstream_pipelines.add(name)
            elif "Table" in obj.labels:
                downstream_tables.add(name)
            elif "Dashboard" in obj.labels:
                downstream_dashboards.add(name)
            elif "Team" in obj.labels:
                impacted_teams.add(name)

        return DependencyChain(
            source=question,
            downstream_pipelines=sorted(downstream_pipelines),
            downstream_tables=sorted(downstream_tables),
            downstream_dashboards=sorted(downstream_dashboards),
            impacted_teams=sorted(impacted_teams),
        )

    async def query(self, question: str) -> BrainQueryResult:
        cypher = ""
        try:
            cypher = await asyncio.wait_for(self._generate_cypher(question), timeout=QUERY_TIMEOUT_SECONDS)
            records = await asyncio.wait_for(self._execute_cypher(cypher), timeout=QUERY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Brain query timed out after %ds: %r", QUERY_TIMEOUT_SECONDS, question)
            return BrainQueryResult(
                cypher_query_executed=cypher,
                summary=f"Query timed out after {QUERY_TIMEOUT_SECONDS}s.",
                nodes_traversed=0,
                relationships_found=[],
                dependency_chain=None,
            )
        except Neo4jError as exc:
            logger.warning("Cypher execution failed for %r (cypher=%s): %s", question, cypher, exc)
            return BrainQueryResult(
                cypher_query_executed=cypher,
                summary=f"The generated Cypher query failed to execute: {exc}",
                nodes_traversed=0,
                relationships_found=[],
                dependency_chain=None,
            )

        summary = await self._summarize(question, cypher, records)
        return BrainQueryResult(
            cypher_query_executed=cypher,
            summary=summary,
            nodes_traversed=self._count_nodes(records),
            relationships_found=self._extract_relationships(records),
            dependency_chain=self._build_dependency_chain(question, records),
        )
