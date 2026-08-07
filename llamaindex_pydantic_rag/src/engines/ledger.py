"""Ledger engine: Text-to-SQL over PostgreSQL via NLSQLTableQueryEngine."""

import asyncio
import logging

from llama_index.core import SQLDatabase
from llama_index.core.query_engine import NLSQLTableQueryEngine
from llama_index.llms.openai import OpenAI
from sqlalchemy import create_engine

from src.engines._text import clean_llm_text
from src.engines.config import EngineConfig
from src.schemas.query import LedgerQueryResult

logger = logging.getLogger(__name__)

TABLE_DESCRIPTIONS = {
    "customers": (
        "Customer records with name, email, subscription plan (free/pro/enterprise), and "
        "company. Use for questions about customer counts, segments, plans."
    ),
    "orders": (
        "Order transactions with amount in BRL, quantity, status "
        "(pending/completed/failed/refunded), and timestamps. Use for revenue, sales volume, "
        "order status questions."
    ),
    "products": "Product catalog with name, category, price, and SKU. Use for product-related questions.",
}

QUERY_TIMEOUT_SECONDS = 30


class LedgerEngine:
    """Text-to-SQL query engine over PostgreSQL (the Ledger)."""

    def __init__(self, config: EngineConfig):
        self.config = config
        engine = create_engine(config.postgres_connection_string)
        sql_database = SQLDatabase(
            engine,
            include_tables=list(TABLE_DESCRIPTIONS),
            custom_table_info=TABLE_DESCRIPTIONS,
        )
        llm = OpenAI(model=config.llm_model, api_key=config.openai_api_key, timeout=QUERY_TIMEOUT_SECONDS)

        self._query_engine = NLSQLTableQueryEngine(
            sql_database=sql_database,
            tables=list(TABLE_DESCRIPTIONS),
            llm=llm,
            synthesize_response=True,
        )

    async def query(self, question: str) -> LedgerQueryResult:
        try:
            response = await asyncio.wait_for(
                self._query_engine.aquery(question), timeout=QUERY_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error("Ledger query timed out after %ds: %r", QUERY_TIMEOUT_SECONDS, question)
            return LedgerQueryResult(
                sql_query_executed="",
                summary=f"Query timed out after {QUERY_TIMEOUT_SECONDS}s.",
                row_count=0,
                data_points=[],
            )
        except Exception as exc:
            logger.error("Ledger query failed for %r: %s", question, exc)
            return LedgerQueryResult(
                sql_query_executed="",
                summary=f"Failed to generate or execute SQL for this question: {exc}",
                row_count=0,
                data_points=[],
            )

        metadata = response.metadata or {}
        sql_query = metadata.get("sql_query", "")
        raw_result = metadata.get("result", [])

        data_points = []
        if isinstance(raw_result, list):
            for row in raw_result:
                if isinstance(row, dict):
                    data_points.append(row)
                elif isinstance(row, (list, tuple)):
                    data_points.append({f"col_{i}": v for i, v in enumerate(row)})

        return LedgerQueryResult(
            sql_query_executed=sql_query,
            summary=clean_llm_text(str(response)),
            row_count=len(data_points),
            data_points=data_points,
        )
