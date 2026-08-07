"""Health check endpoint -- verifies connectivity to every backing service."""

import asyncio
import logging
import time

import httpx
import psycopg2
from fastapi import APIRouter, Request
from neo4j import AsyncGraphDatabase
from pymongo import MongoClient

from src.api.config import APIConfig
from src.schemas.api import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

HEALTH_CHECK_TIMEOUT_SECONDS = 5
CRITICAL_SERVICES = ("postgres", "qdrant", "neo4j")


async def _check_postgres(config: APIConfig) -> str:
    def _connect() -> None:
        conn = psycopg2.connect(
            host=config.postgres_host,
            port=config.postgres_port,
            dbname=config.postgres_db,
            user=config.postgres_user,
            password=config.postgres_password,
            connect_timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()

    try:
        await asyncio.wait_for(asyncio.to_thread(_connect), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        return "healthy"
    except Exception as exc:
        logger.warning("postgres health check failed: %s", exc)
        return "unhealthy"


async def _check_qdrant(config: APIConfig) -> str:
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
            response = await client.get(f"http://{config.qdrant_host}:{config.qdrant_port}/healthz")
            response.raise_for_status()
        return "healthy"
    except Exception as exc:
        logger.warning("qdrant health check failed: %s", exc)
        return "unhealthy"


async def _check_neo4j(config: APIConfig) -> str:
    driver = AsyncGraphDatabase.driver(config.neo4j_uri, auth=(config.neo4j_user, config.neo4j_password))
    try:
        async def _run() -> None:
            async with driver.session() as session:
                await session.run("RETURN 1")

        await asyncio.wait_for(_run(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        return "healthy"
    except Exception as exc:
        logger.warning("neo4j health check failed: %s", exc)
        return "unhealthy"
    finally:
        await driver.close()


async def _check_mongo(config: APIConfig) -> str:
    def _ping() -> None:
        client = MongoClient(
            host=config.mongo_host,
            port=config.mongo_port,
            serverSelectionTimeoutMS=HEALTH_CHECK_TIMEOUT_SECONDS * 1000,
        )
        try:
            client.admin.command("ping")
        finally:
            client.close()

    try:
        await asyncio.wait_for(asyncio.to_thread(_ping), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        return "healthy"
    except Exception as exc:
        logger.warning("mongo health check failed: %s", exc)
        return "unhealthy"


async def _check_seaweedfs(config: APIConfig) -> str:
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"http://{config.seaweedfs_host}:{config.seaweedfs_master_port}/cluster/status"
            )
            response.raise_for_status()
        return "healthy"
    except Exception as exc:
        logger.warning("seaweedfs health check failed: %s", exc)
        return "unhealthy"


@router.get("/health", response_model=HealthResponse)
async def health_check(req: Request) -> HealthResponse:
    """Check the health of all connected services."""
    config = APIConfig()

    postgres, qdrant, neo4j, mongo, seaweedfs = await asyncio.gather(
        _check_postgres(config),
        _check_qdrant(config),
        _check_neo4j(config),
        _check_mongo(config),
        _check_seaweedfs(config),
    )
    services = {
        "postgres": postgres,
        "qdrant": qdrant,
        "neo4j": neo4j,
        "mongo": mongo,
        "seaweedfs": seaweedfs,
    }

    critical_ok = all(services[name] == "healthy" for name in CRITICAL_SERVICES)
    overall_status = "healthy" if critical_ok else "unhealthy"

    uptime_seconds = time.monotonic() - req.app.state.start_time
    return HealthResponse(
        status=overall_status,
        services=services,
        uptime_seconds=round(uptime_seconds, 2),
        version=req.app.version,
    )
