"""Memory engine: vector similarity search over the existing Qdrant collection."""

import asyncio
import logging

from llama_index.core import VectorStoreIndex
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient, QdrantClient

from src.engines._text import clean_llm_text
from src.engines.config import EngineConfig
from src.schemas.query import MemoryQueryResult

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_SECONDS = 30


class MemoryEngine:
    """Vector search query engine over Qdrant (the Memory), reading the collection
    populated by the ingestion pipeline — never re-ingests.
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        client = QdrantClient(host=config.qdrant_host, port=config.qdrant_port)
        aclient = AsyncQdrantClient(host=config.qdrant_host, port=config.qdrant_port)
        vector_store = QdrantVectorStore(
            client=client, aclient=aclient, collection_name=config.qdrant_collection
        )

        embed_model = OpenAIEmbedding(model=config.embedding_model, api_key=config.openai_api_key)
        llm = OpenAI(model=config.llm_model, api_key=config.openai_api_key, timeout=QUERY_TIMEOUT_SECONDS)

        index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
        self._query_engine = index.as_query_engine(
            llm=llm,
            similarity_top_k=5,
            response_mode="tree_summarize",
        )

    async def query(self, question: str) -> MemoryQueryResult:
        try:
            response = await asyncio.wait_for(
                self._query_engine.aquery(question), timeout=QUERY_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error("Memory query timed out after %ds: %r", QUERY_TIMEOUT_SECONDS, question)
            return MemoryQueryResult(
                summary=f"Query timed out after {QUERY_TIMEOUT_SECONDS}s.",
                sources=[],
                confidence=0.0,
                relevant_facts=[],
            )
        except Exception as exc:
            logger.error("Memory query failed for %r: %s", question, exc)
            return MemoryQueryResult(
                summary=f"Failed to search the Memory index for this question: {exc}",
                sources=[],
                confidence=0.0,
                relevant_facts=[],
            )

        source_nodes = response.source_nodes or []
        sources = []
        scores = []
        relevant_facts = []
        for node in source_nodes:
            file_name = node.metadata.get("file_name") or node.metadata.get("collection", "unknown")
            sources.append(file_name)
            if node.score is not None:
                scores.append(node.score)
            excerpt = node.get_content()[:280].strip()
            if excerpt:
                relevant_facts.append(excerpt)

        confidence = sum(scores) / len(scores) if scores else 0.0

        return MemoryQueryResult(
            summary=clean_llm_text(str(response)),
            sources=list(dict.fromkeys(sources)),
            confidence=min(max(confidence, 0.0), 1.0),
            relevant_facts=relevant_facts,
        )
