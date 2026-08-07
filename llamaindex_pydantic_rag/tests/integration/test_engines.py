"""Integration tests requiring the full infrastructure stack running."""

import pytest

from src.engines.brain import BrainEngine
from src.engines.ledger import LedgerEngine
from src.engines.memory import MemoryEngine
from src.schemas.query import BrainQueryResult, LedgerQueryResult, MemoryQueryResult


@pytest.mark.integration
class TestLedgerEngine:
    async def test_count_query(self, config):
        """Test a simple count query against PostgreSQL."""
        engine = LedgerEngine(config)
        result = await engine.query("How many customers are there?")
        assert isinstance(result, LedgerQueryResult)
        assert "SELECT" in result.sql_query_executed.upper()
        assert result.row_count >= 0

    async def test_aggregation_query(self, config):
        """Test an aggregation query."""
        engine = LedgerEngine(config)
        result = await engine.query("What is the total revenue from completed orders?")
        assert isinstance(result, LedgerQueryResult)
        assert "completed" in result.sql_query_executed.lower()


@pytest.mark.integration
class TestMemoryEngine:
    async def test_policy_query(self, config):
        """Test retrieval of policy documents."""
        engine = MemoryEngine(config)
        result = await engine.query("What is the data retention policy for PII?")
        assert isinstance(result, MemoryQueryResult)
        assert result.confidence > 0.0
        assert len(result.sources) > 0

    async def test_event_query(self, config):
        """Test retrieval of event logs."""
        engine = MemoryEngine(config)
        result = await engine.query("What pipeline failures happened recently?")
        assert isinstance(result, MemoryQueryResult)


@pytest.mark.integration
class TestBrainEngine:
    async def test_ownership_query(self, config):
        """Test graph traversal for ownership."""
        engine = BrainEngine(config)
        result = await engine.query("What pipelines does team-billing own?")
        assert isinstance(result, BrainQueryResult)
        assert "MATCH" in result.cypher_query_executed.upper()

    async def test_dependency_query(self, config):
        """Test dependency chain population."""
        engine = BrainEngine(config)
        result = await engine.query("What would be impacted if the orders table goes down?")
        assert isinstance(result, BrainQueryResult)
        assert result.dependency_chain is not None
