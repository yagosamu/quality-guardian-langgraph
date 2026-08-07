"""FastAPI application factory for the DataOps Knowledge Hub."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import health_router, ingest_router, query_router
from src.engines.config import EngineConfig
from src.engines.router import RouterEngine

# Configured at import time (not just under `if __name__ == "__main__"`) so logging
# works whether the app is launched via `python -m src.api.main` or directly via
# `uvicorn src.api.main:app` -- the latter never executes the __main__ guard.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

APP_DESCRIPTION = """
Enterprise RAG system answering cross-domain questions across three specialized engines:

- **Ledger** (PostgreSQL) -- Text-to-SQL for factual/transactional questions
- **Memory** (Qdrant) -- Semantic vector search over documents and logs
- **Brain** (Neo4j) -- Graph traversal for relationships and lineage

A RouterEngine classifies and decomposes incoming questions, runs the relevant
engines in parallel, and synthesizes a single Pydantic-validated response.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.start_time = time.monotonic()
    logger.info("Initializing RouterEngine...")
    config = EngineConfig()
    app.state.router = RouterEngine(config)
    logger.info("RouterEngine ready.")

    yield

    logger.info("Shutting down RouterEngine...")
    await app.state.router.brain.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="DataOps Knowledge Hub",
        version="1.0.0",
        description=APP_DESCRIPTION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %d (%.2fms)",
            request.method, request.url.path, response.status_code, elapsed_ms,
        )
        return response

    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_exception_handler(request: Request, exc: asyncio.TimeoutError) -> JSONResponse:
        logger.error("Timeout on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=504, content={"detail": "The request timed out."})

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "An internal error occurred."})

    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(ingest_router)

    return app
