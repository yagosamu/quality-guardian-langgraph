"""On-demand ingestion trigger -- re-runs the Memory ingestion pipeline in the background."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks

from src.ingestion.config import IngestionConfig
from src.ingestion.pipeline import build_pipeline, run_pipeline
from src.ingestion.readers import MongoDBReader, SeaweedFSReader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


async def _run_ingestion() -> None:
    config = IngestionConfig()

    seaweedfs_docs = await asyncio.to_thread(SeaweedFSReader(config).load_data)
    mongo_docs = await asyncio.to_thread(MongoDBReader(config).load_data)
    all_documents = seaweedfs_docs + mongo_docs
    logger.info("background ingestion: %d documents to process", len(all_documents))

    pipeline = build_pipeline(config)
    nodes = await run_pipeline(pipeline, all_documents)
    logger.info("background ingestion complete: %d nodes indexed", len(nodes))


@router.post("/ingest", status_code=202)
async def trigger_ingestion(background_tasks: BackgroundTasks) -> dict:
    """Trigger a re-ingestion of all data sources into the Memory engine.

    Runs in the background -- returns immediately.
    """
    background_tasks.add_task(_run_ingestion)
    return {"status": "ingestion_started", "message": "Ingestion is running in the background."}
