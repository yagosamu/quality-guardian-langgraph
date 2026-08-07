"""Router engine: classifies/decomposes a question, runs the Ledger, Memory, and
Brain engines in parallel, and synthesizes one unified, Pydantic-validated answer.

Custom LLM-based classification is used instead of LlamaIndex's SubQuestionQueryEngine
for full control and transparency over which engine was chosen and why — the
sub_questions/sources_consulted fields on SynthesizedResponse exist specifically so
callers can see that reasoning.
"""

import asyncio
import logging
import re
import time
from typing import Literal, Optional

from llama_index.llms.openai import OpenAI
from pydantic import BaseModel

from src.engines._text import clean_llm_text
from src.engines.brain import BrainEngine
from src.engines.config import EngineConfig
from src.engines.ledger import LedgerEngine
from src.engines.memory import MemoryEngine
from src.schemas.api import SourceDetail
from src.schemas.query import SynthesizedResponse

logger = logging.getLogger(__name__)

ROUTER_TIMEOUT_SECONDS = 60

ENGINE_NAMES = ("ledger", "memory", "brain")

DATA_STORE_BY_ENGINE = {
    "ledger": "postgresql",
    "memory": "qdrant",
    "brain": "neo4j",
}

CLASSIFICATION_PROMPT = """You are a query router for a DataOps Knowledge Hub with 3 data stores:

1. LEDGER (PostgreSQL) - Contains: customers, orders, products tables.
   Use for: numerical questions, counts, aggregations, revenue, top-N, filtering by status/plan/date.
   Examples: "How many enterprise customers?", "Total revenue this month?", "Top 5 customers by spend"

2. MEMORY (Qdrant Vector Store) - Contains: data retention policies, SLA definitions, incident runbooks, data dictionaries, pipeline event logs, user activity logs.
   Use for: policy questions, procedure questions, "what happened" questions, historical events, definitions.
   Examples: "What is the retention policy for PII?", "What's the SLA for etl_billing_daily?", "What happened in the last failure?"

3. BRAIN (Neo4j Graph) - Contains: pipelines, tables, dashboards, teams, and their relationships (OWNS, READS_FROM, WRITES_TO, FEEDS, USED_BY).
   Use for: relationship questions, dependency/lineage questions, ownership, impact analysis, "what connects to what".
   Examples: "Who owns the billing pipeline?", "What's impacted if orders table goes down?", "Show lineage of fact_revenue"

Given a user question, respond with ONLY a JSON object (no markdown fences, no explanation):
{"sub_questions": [{"engine": "ledger|memory|brain", "question": "the sub-question for this engine"}]}

Rules:
- Simple questions that clearly belong to one engine: return 1 sub-question.
- Complex questions that span multiple domains: decompose into 2-3 sub-questions, one per relevant engine.
- Never route to more than 3 sub-questions.
- Rephrase each sub-question to be self-contained and specific to that engine's data.

User question: __QUESTION__

JSON:"""

SYNTHESIS_PROMPT = """Given the following sub-question results, synthesize a comprehensive answer to the original question.

Original question: __QUESTION__

Results:
__RESULTS__

Provide a clear, actionable answer that combines insights from all sources. If (and only if) a concrete
recommendation is warranted, end with one final sentence starting exactly with "Recommendation:"."""


class SubQuestionItem(BaseModel):
    engine: Literal["ledger", "memory", "brain"]
    question: str


class SubQuestionPlan(BaseModel):
    sub_questions: list[SubQuestionItem]


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE).strip()


class RouterEngine:
    """Orchestrates LedgerEngine, MemoryEngine, and BrainEngine behind one entry point."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self.llm = OpenAI(model=config.llm_model, api_key=config.openai_api_key)
        self.ledger = LedgerEngine(config)
        self.memory = MemoryEngine(config)
        self.brain = BrainEngine(config)
        self._engines = {"ledger": self.ledger, "memory": self.memory, "brain": self.brain}

    async def _classify(self, question: str) -> list[SubQuestionItem]:
        prompt = CLASSIFICATION_PROMPT.replace("__QUESTION__", question)
        response = await self.llm.acomplete(prompt)
        text = _strip_fences(response.text)
        try:
            plan = SubQuestionPlan.model_validate_json(text)
        except Exception as exc:
            logger.warning("Router classification failed to parse (%s); falling back to all engines", exc)
            return [SubQuestionItem(engine=name, question=question) for name in ENGINE_NAMES]
        return plan.sub_questions[:3]

    async def _run_engine(self, engine_name: str, question: str):
        engine = self._engines[engine_name]
        try:
            result = await engine.query(question)
            return engine_name, question, result, None
        except Exception as exc:
            logger.error("Engine %s failed for question %r: %s", engine_name, question, exc)
            return engine_name, question, None, str(exc)

    def _build_source_detail(
        self, engine_name: str, result, error: Optional[str]
    ) -> SourceDetail:
        if error is not None or result is None:
            return SourceDetail(
                source=engine_name,
                data_store=DATA_STORE_BY_ENGINE[engine_name],
                query_used="N/A",
                result_summary=f"Source unavailable: {error}",
                confidence=0.0,
            )
        if engine_name == "ledger":
            return SourceDetail(
                source="ledger",
                data_store="postgresql",
                query_used=result.sql_query_executed,
                result_summary=result.summary,
                confidence=0.9,  # SQL is deterministic
            )
        if engine_name == "memory":
            return SourceDetail(
                source="memory",
                data_store="qdrant",
                query_used="Vector search (top_k=5)",
                result_summary=result.summary,
                confidence=result.confidence,
            )
        return SourceDetail(
            source="brain",
            data_store="neo4j",
            query_used=result.cypher_query_executed,
            result_summary=result.summary,
            confidence=0.85,  # Cypher is deterministic but synthesis isn't
        )

    async def _synthesize(self, question: str, source_details: list[SourceDetail]) -> str:
        formatted = "\n".join(f"- [{sd.source}] {sd.result_summary}" for sd in source_details)
        prompt = SYNTHESIS_PROMPT.replace("__QUESTION__", question).replace("__RESULTS__", formatted)
        response = await self.llm.acomplete(prompt)
        return clean_llm_text(response.text.strip())

    async def _do_query(
        self, question: str, sources: Optional[list[str]]
    ) -> tuple[SynthesizedResponse, list[SourceDetail]]:
        if sources:
            sub_questions = [
                SubQuestionItem(engine=s, question=question) for s in sources if s in ENGINE_NAMES
            ]
            if not sub_questions:
                sub_questions = [SubQuestionItem(engine="memory", question=question)]
        else:
            sub_questions = await self._classify(question)

        raw_results = await asyncio.gather(
            *(self._run_engine(sq.engine, sq.question) for sq in sub_questions)
        )

        source_details = [
            self._build_source_detail(engine_name, result, error)
            for engine_name, _question, result, error in raw_results
        ]

        answer = await self._synthesize(question, source_details)

        recommendation = None
        if "Recommendation:" in answer:
            answer_part, _, rec_part = answer.partition("Recommendation:")
            answer = answer_part.strip()
            recommendation = rec_part.strip() or None

        successful_confidences = [sd.confidence for sd in source_details if sd.confidence > 0]
        confidence = (
            sum(successful_confidences) / len(successful_confidences) if successful_confidences else 0.0
        )

        response = SynthesizedResponse(
            answer=answer,
            sub_questions=[sq.question for sq in sub_questions],
            sources_consulted=[sq.engine for sq in sub_questions],
            confidence=min(max(confidence, 0.0), 1.0),
            recommendation=recommendation,
        )
        return response, source_details

    async def query(
        self, question: str, sources: Optional[list[str]] = None
    ) -> tuple[SynthesizedResponse, list[SourceDetail]]:
        """Route and execute a question across engines.

        Args:
            question: Natural language question.
            sources: Optional filter -- only use these engines (e.g. ["ledger", "brain"]).
                     If None, an LLM classification step decides which engine(s) to use.

        Returns:
            Tuple of (SynthesizedResponse, list[SourceDetail]) for the API layer to consume.
        """
        start = time.monotonic()
        try:
            response, source_details = await asyncio.wait_for(
                self._do_query(question, sources), timeout=ROUTER_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error("Router query timed out after %ds: %r", ROUTER_TIMEOUT_SECONDS, question)
            response = SynthesizedResponse(
                answer=f"The query took too long to process (>{ROUTER_TIMEOUT_SECONDS}s) and was aborted.",
                sub_questions=[],
                sources_consulted=[],
                confidence=0.0,
                recommendation=None,
            )
            return response, []

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "router query complete: sub_questions=%d elapsed=%.0fms",
            len(response.sub_questions), elapsed_ms,
        )
        return response, source_details
