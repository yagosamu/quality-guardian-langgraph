"""Integration test for the full router flow (classification + parallel execution + synthesis)."""

import pytest

from src.engines.router import RouterEngine
from src.schemas.query import SynthesizedResponse


@pytest.mark.integration
class TestRouterEngine:
    async def test_single_engine_routing(self, config):
        """Simple question routes to one engine."""
        router = RouterEngine(config)
        response, sources = await router.query("How many enterprise customers?")
        assert isinstance(response, SynthesizedResponse)
        assert len(sources) == 1
        assert sources[0].source == "ledger"

    async def test_multi_engine_routing(self, config):
        """Complex question decomposes and routes to multiple engines."""
        router = RouterEngine(config)
        response, sources = await router.query(
            "What are the top customers by revenue, what's the SLA for billing, "
            "and what depends on the orders table?"
        )
        assert isinstance(response, SynthesizedResponse)
        assert len(sources) >= 2
        assert len(response.sub_questions) >= 2

    async def test_forced_routing(self, config):
        """Sources filter bypasses classification."""
        router = RouterEngine(config)
        response, sources = await router.query(
            "Tell me everything about billing", sources=["ledger", "brain"]
        )
        assert all(s.source in ["ledger", "brain"] for s in sources)
