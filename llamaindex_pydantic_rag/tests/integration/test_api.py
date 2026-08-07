"""Integration tests for the FastAPI endpoints (requires the `app` service running)."""

import os

import httpx
import pytest

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


@pytest.mark.integration
class TestAPI:
    async def test_health_endpoint(self):
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE_URL}/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] in ["healthy", "degraded", "unhealthy"]

    async def test_query_endpoint(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{BASE_URL}/api/v1/query", json={"question": "How many customers do we have?"}
            )
            assert r.status_code == 200
            data = r.json()
            assert "answer" in data
            assert "sources_consulted" in data
            assert data["processing_time_ms"] > 0

    async def test_query_with_sources_filter(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{BASE_URL}/api/v1/query",
                json={"question": "Who owns the billing pipeline?", "sources": ["brain"]},
            )
            assert r.status_code == 200
            data = r.json()
            assert all(s["source"] == "brain" for s in data["sources_consulted"])

    async def test_invalid_request(self):
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{BASE_URL}/api/v1/query", json={"wrong_field": "test"})
            assert r.status_code == 422

    async def test_ingest_endpoint(self):
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{BASE_URL}/api/v1/ingest")
            assert r.status_code == 202
