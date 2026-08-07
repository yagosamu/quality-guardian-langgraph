"""LlamaIndex ingestion pipeline: semantic splitting, metadata enrichment,
embedding, and storage into Qdrant (Memory engine).
"""

import logging
import time

from llama_index.core.extractors import (
    KeywordExtractor,
    QuestionsAnsweredExtractor,
    SummaryExtractor,
    TitleExtractor,
)
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SemanticSplitterNodeParser, SentenceSplitter
from llama_index.core.schema import BaseNode, Document
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient, QdrantClient

from src.ingestion.config import IngestionConfig

logger = logging.getLogger(__name__)


def _build_splitter(config: IngestionConfig, embed_model: OpenAIEmbedding):
    """SemanticSplitterNodeParser is preferred (splits by meaning); if it can't
    be constructed (e.g. embedding backend unavailable), fall back to a plain
    SentenceSplitter for the whole run.
    """
    try:
        return SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=embed_model,
        )
    except Exception as exc:
        logger.warning(
            "SemanticSplitterNodeParser unavailable (%s), falling back to SentenceSplitter",
            exc,
        )
        return SentenceSplitter(chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap)


def build_pipeline(config: IngestionConfig) -> IngestionPipeline:
    """Assemble the ingestion pipeline: split -> enrich metadata -> embed -> store."""
    embed_model = OpenAIEmbedding(model=config.embedding_model, api_key=config.openai_api_key)
    llm = OpenAI(model=config.llm_model, api_key=config.openai_api_key)

    splitter = _build_splitter(config, embed_model)

    title_extractor = TitleExtractor(nodes=3, llm=llm)
    summary_extractor = SummaryExtractor(summaries=["self"], llm=llm)
    keyword_extractor = KeywordExtractor(keywords=5, llm=llm)
    questions_extractor = QuestionsAnsweredExtractor(questions=3, llm=llm)

    client = QdrantClient(host=config.qdrant_host, port=config.qdrant_port)
    aclient = AsyncQdrantClient(host=config.qdrant_host, port=config.qdrant_port)
    vector_store = QdrantVectorStore(
        client=client, aclient=aclient, collection_name=config.qdrant_collection
    )

    return IngestionPipeline(
        transformations=[
            splitter,
            title_extractor,
            summary_extractor,
            keyword_extractor,
            questions_extractor,
            embed_model,
        ],
        vector_store=vector_store,
    )


async def run_pipeline(pipeline: IngestionPipeline, documents: list[Document]) -> list[BaseNode]:
    """Run the pipeline over all documents, returning the indexed nodes."""
    if not documents:
        logger.warning("no documents to ingest, skipping pipeline run")
        return []

    start = time.monotonic()
    nodes = await pipeline.arun(documents=documents, show_progress=True)
    elapsed = time.monotonic() - start
    logger.info(
        "pipeline run complete: documents=%d nodes=%d elapsed=%.1fs",
        len(documents), len(nodes), elapsed,
    )
    return nodes
