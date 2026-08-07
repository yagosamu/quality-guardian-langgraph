"""Unit tests for the router's classification/decomposition logic.

The LLM and all 3 sub-engines are mocked -- LedgerEngine's constructor alone
opens a real Postgres connection (SQLDatabase validates via engine.connect()
at construction time), so RouterEngine cannot be instantiated for real without
infra. Patching the engine classes before construction keeps this a true unit
test: no network access, no running services required.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engines.router import ENGINE_NAMES, RouterEngine
from src.schemas.query import BrainQueryResult, LedgerQueryResult, MemoryQueryResult


def _fake_completion(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)


def _fake_engine_result(engine_name: str):
    if engine_name == "ledger":
        return LedgerQueryResult(
            sql_query_executed="SELECT COUNT(*) FROM customers",
            summary="ledger result",
            row_count=1,
            data_points=[],
        )
    if engine_name == "memory":
        return MemoryQueryResult(summary="memory result", sources=["policy.md"], confidence=0.8, relevant_facts=[])
    return BrainQueryResult(
        cypher_query_executed="MATCH (n) RETURN n",
        summary="brain result",
        nodes_traversed=1,
        relationships_found=[],
        dependency_chain=None,
    )


@pytest.fixture
def router(config, monkeypatch) -> RouterEngine:
    """RouterEngine with all 3 sub-engines and the LLM mocked -- no real infra touched."""
    for engine_name in ENGINE_NAMES:
        class_path = f"src.engines.router.{engine_name.capitalize()}Engine"
        mock_instance = MagicMock()
        mock_instance.query = AsyncMock(return_value=_fake_engine_result(engine_name))
        monkeypatch.setattr(class_path, MagicMock(return_value=mock_instance))

    engine = RouterEngine(config)
    engine.llm = MagicMock()
    engine.llm.acomplete = AsyncMock()
    return engine


async def test_customer_question_routes_to_ledger(router):
    router.llm.acomplete.side_effect = [
        _fake_completion(json.dumps({"sub_questions": [{"engine": "ledger", "question": "count customers"}]})),
        _fake_completion("Synthesized answer."),
    ]
    response, sources = await router.query("How many customers are on the enterprise plan?")
    assert response.sources_consulted == ["ledger"]
    assert len(sources) == 1
    assert sources[0].source == "ledger"


async def test_sla_question_routes_to_memory(router):
    router.llm.acomplete.side_effect = [
        _fake_completion(json.dumps({"sub_questions": [{"engine": "memory", "question": "SLA for billing"}]})),
        _fake_completion("Synthesized answer."),
    ]
    response, sources = await router.query("What is the SLA for etl_billing_daily?")
    assert response.sources_consulted == ["memory"]
    assert sources[0].source == "memory"


async def test_ownership_question_routes_to_brain(router):
    router.llm.acomplete.side_effect = [
        _fake_completion(json.dumps({"sub_questions": [{"engine": "brain", "question": "who owns orders"}]})),
        _fake_completion("Synthesized answer."),
    ]
    response, sources = await router.query("Who owns the orders table?")
    assert response.sources_consulted == ["brain"]
    assert sources[0].source == "brain"


async def test_complex_question_decomposes_into_multiple_sub_questions(router):
    router.llm.acomplete.side_effect = [
        _fake_completion(
            json.dumps(
                {
                    "sub_questions": [
                        {"engine": "ledger", "question": "Top customers by revenue?"},
                        {"engine": "brain", "question": "What depends on the orders table?"},
                    ]
                }
            )
        ),
        _fake_completion("Synthesized answer."),
    ]
    response, sources = await router.query(
        "What are the top customers by revenue and what depends on the orders table?"
    )
    assert len(response.sub_questions) == 2
    assert len(sources) == 2


async def test_malformed_llm_response_falls_back_to_all_engines(router):
    router.llm.acomplete.side_effect = [
        _fake_completion("this is not valid JSON at all"),
        _fake_completion("Synthesized answer."),
    ]
    response, sources = await router.query("Some ambiguous question")
    assert set(response.sources_consulted) == set(ENGINE_NAMES)
    assert len(sources) == 3


async def test_sources_filter_bypasses_classification(router):
    # Only one acomplete call expected: synthesis. Classification must be skipped entirely.
    router.llm.acomplete.side_effect = [_fake_completion("Synthesized answer.")]
    response, sources = await router.query("Tell me about customers", sources=["ledger"])
    assert response.sources_consulted == ["ledger"]
    assert router.llm.acomplete.call_count == 1
