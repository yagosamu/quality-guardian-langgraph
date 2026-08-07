"""Entry point for running the ingestion pipeline: `python -m src.ingestion.run`."""

import asyncio
import logging

from src.ingestion.config import IngestionConfig
from src.ingestion.pipeline import build_pipeline, run_pipeline
from src.ingestion.readers import MongoDBReader, SeaweedFSReader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main():
    config = IngestionConfig()

    logger.info("Loading documents from SeaweedFS...")
    seaweedfs_reader = SeaweedFSReader(config)
    seaweedfs_docs = seaweedfs_reader.load_data()
    logger.info(f"  -> {len(seaweedfs_docs)} documents from SeaweedFS")

    logger.info("Loading documents from MongoDB...")
    mongo_reader = MongoDBReader(config)
    mongo_docs = mongo_reader.load_data()
    logger.info(f"  -> {len(mongo_docs)} documents from MongoDB")

    all_documents = seaweedfs_docs + mongo_docs
    logger.info(f"Total documents to ingest: {len(all_documents)}")

    pipeline = build_pipeline(config)
    nodes = await run_pipeline(pipeline, all_documents)
    logger.info(f"Ingestion complete. {len(nodes)} nodes indexed in Qdrant.")


if __name__ == "__main__":
    asyncio.run(main())
