"""Access to the W01 Ledger (Postgres): read factual data, write quality scores.

The Hub has no write API, so the Guardian's own writes (health_score,
quality_flag) go straight through SQL too — that's the additive part of W02.
"""

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from . import config

QUALITY_COLUMNS_DDL = """
ALTER TABLE customers ADD COLUMN IF NOT EXISTS health_score NUMERIC(4,3);
ALTER TABLE customers ADD COLUMN IF NOT EXISTS quality_flag VARCHAR(10);
ALTER TABLE customers ADD COLUMN IF NOT EXISTS checked_at TIMESTAMP;
"""

EXPECTED_COLUMNS = {"id", "name", "email", "plan", "company", "created_at"}


@contextmanager
def connect():
    """Yield an autocommit psycopg connection to the Ledger, rows as dicts."""
    with psycopg.connect(config.PG_CONNINFO, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def ensure_quality_columns() -> None:
    """Idempotently add the health_score/quality_flag/checked_at columns."""
    with connect() as conn:
        conn.execute(QUALITY_COLUMNS_DDL)


def get_columns(table: str) -> set[str]:
    """Read the live column set of `table` from information_schema (for check_schema)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        ).fetchall()
    return {row["column_name"] for row in rows}


def read_customers(limit: int | None = None) -> list[dict]:
    """Read the `limit` most recently created customers, with order aggregates.

    Applies the validation window: only the newest rows (id DESC), not the
    whole Ledger — the generator never stops, so validating everything would
    both mask individual reds in the average and make the state unreadable.
    """
    limit = limit or config.WINDOW
    query = """
        SELECT
            c.id,
            c.name,
            c.email,
            c.plan,
            c.company,
            c.created_at,
            COUNT(o.id) AS n_orders,
            COALESCE(SUM(o.amount), 0) AS total_amount,
            COALESCE(SUM(CASE WHEN o.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_orders
        FROM (
            SELECT * FROM customers ORDER BY id DESC LIMIT %s
        ) c
        LEFT JOIN orders o ON o.customer_id = c.id
        GROUP BY c.id, c.name, c.email, c.plan, c.company, c.created_at
        ORDER BY c.id DESC
    """
    with connect() as conn:
        return conn.execute(query, (limit,)).fetchall()


def write_scores(scored: list[tuple[int, float, str]]) -> int:
    """UPDATE health_score/quality_flag/checked_at for each (id, score, flag)."""
    with connect() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            UPDATE customers
            SET health_score = %s, quality_flag = %s, checked_at = NOW()
            WHERE id = %s
            """,
            [(score, flag, id_) for id_, score, flag in scored],
        )
        return cur.rowcount


def count_by_flag() -> dict[str, int]:
    """Distribution of quality_flag across customers (for reporting / W03 handoff)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT quality_flag, COUNT(*) AS n FROM customers GROUP BY quality_flag"
        ).fetchall()
    return {row["quality_flag"]: row["n"] for row in rows}
