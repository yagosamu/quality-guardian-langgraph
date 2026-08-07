"""Unit tests for Pydantic models -- no infra needed."""

import pytest
from pydantic import ValidationError

from src.schemas.api import HealthResponse, QueryRequest, QueryResponse, SourceDetail
from src.schemas.domain import CustomerPlan, DependencyChain, OrderStatus, PipelineStatus, Severity


def test_query_request_all_fields():
    req = QueryRequest(question="How many customers?", sources=["ledger"], include_metadata=False)
    assert req.question == "How many customers?"
    assert req.sources == ["ledger"]
    assert req.include_metadata is False


def test_query_request_only_required_fields():
    req = QueryRequest(question="How many customers?")
    assert req.sources is None
    assert req.include_metadata is True


def test_query_request_missing_question_raises():
    with pytest.raises(ValidationError):
        QueryRequest()


def test_query_response_with_source_details():
    resp = QueryResponse(
        question="How many customers?",
        answer="There are 42 customers.",
        sub_questions=["How many customers are there?"],
        sources_consulted=[
            SourceDetail(
                source="ledger",
                data_store="postgresql",
                query_used="SELECT COUNT(*) FROM customers",
                result_summary="42 customers found",
                confidence=0.9,
            )
        ],
        processing_time_ms=123.45,
    )
    assert len(resp.sources_consulted) == 1
    assert resp.sources_consulted[0].confidence == 0.9


def test_source_detail_confidence_rejects_above_one():
    with pytest.raises(ValidationError):
        SourceDetail(
            source="ledger", data_store="postgresql", query_used="q", result_summary="r", confidence=1.5
        )


def test_source_detail_confidence_rejects_below_zero():
    with pytest.raises(ValidationError):
        SourceDetail(
            source="ledger", data_store="postgresql", query_used="q", result_summary="r", confidence=-0.1
        )


@pytest.mark.parametrize(
    "enum_cls,expected_values",
    [
        (CustomerPlan, {"free", "pro", "enterprise"}),
        (OrderStatus, {"pending", "completed", "failed", "refunded"}),
        (PipelineStatus, {"completed", "failed", "warning"}),
        (Severity, {"info", "warning", "critical"}),
    ],
)
def test_enum_values_are_valid(enum_cls, expected_values):
    assert {member.value for member in enum_cls} == expected_values


def test_dependency_chain_with_empty_lists_is_valid():
    chain = DependencyChain(source="orders")
    assert chain.downstream_pipelines == []
    assert chain.downstream_tables == []
    assert chain.downstream_dashboards == []
    assert chain.impacted_teams == []


def test_health_response_accepts_arbitrary_service_names():
    resp = HealthResponse(
        status="healthy",
        services={"postgres": "healthy", "some_future_service": "unhealthy"},
        uptime_seconds=42.0,
        version="1.0.0",
    )
    assert resp.services["some_future_service"] == "unhealthy"
