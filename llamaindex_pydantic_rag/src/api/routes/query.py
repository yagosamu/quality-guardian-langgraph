"""Main query endpoint -- routes a natural language question through the RouterEngine."""

import time

from fastapi import APIRouter, Request

from src.schemas.api import QueryRequest, QueryResponse

router = APIRouter(prefix="/api/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_knowledge_hub(request: QueryRequest, req: Request) -> QueryResponse:
    """Query the DataOps Knowledge Hub.

    The system automatically routes your question to the appropriate engine(s):
    - **Ledger** (PostgreSQL): factual/numerical questions
    - **Memory** (Qdrant): policies, procedures, historical events
    - **Brain** (Neo4j): relationships, dependencies, lineage

    Complex questions are decomposed into sub-questions and executed in parallel.
    """
    start = time.perf_counter()

    router_engine = req.app.state.router

    synthesized, source_details = await router_engine.query(
        question=request.question,
        sources=request.sources,
    )

    elapsed_ms = (time.perf_counter() - start) * 1000

    return QueryResponse(
        question=request.question,
        answer=synthesized.answer,
        sub_questions=synthesized.sub_questions,
        sources_consulted=source_details,
        recommendation=synthesized.recommendation,
        processing_time_ms=round(elapsed_ms, 2),
    )
