"""Continuous Faker-based data generator for the DataOps Knowledge Hub.

Populates Postgres (Ledger), MongoDB (Events), and SeaweedFS (Data Lake)
on a fixed interval to simulate a live enterprise operation.
"""

import asyncio
import csv
import io
import logging
import os
import random
import signal
import string
import time
from datetime import datetime, timezone

import boto3
import psycopg2
from faker import Faker
from pymongo import MongoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("data-generator")

fake = Faker("pt_BR")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "dataops")
POSTGRES_USER = os.getenv("POSTGRES_USER", "dataops")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "dataops123")

MONGO_HOST = os.getenv("MONGO_HOST", "mongo")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB_NAME = os.getenv("MONGO_DB", "dataops")

SEAWEEDFS_HOST = os.getenv("SEAWEEDFS_HOST", "seaweedfs")
SEAWEEDFS_PORT = os.getenv("SEAWEEDFS_PORT", "8333")
SEAWEEDFS_BUCKET = os.getenv("SEAWEEDFS_BUCKET", "dataops-lake")

INTERVAL_SECONDS = int(os.getenv("GENERATOR_INTERVAL_SECONDS", "30"))

PIPELINE_NAMES = [
    "etl_billing_daily",
    "etl_orders_hourly",
    "etl_customer_sync",
    "analytics_revenue_agg",
]

PRODUCT_CATEGORIES = ["Analytics", "Integration", "Storage", "Compute"]
PRODUCT_NAME_STEMS = [
    "DataFlow", "MetricStream", "PipelineGuard", "VectorCache", "GraphLink",
    "SyncBridge", "InsightHub", "ArchiveVault", "QueryBoost", "EventRelay",
]

FAILED_ERROR_MESSAGES = [
    "Connection timeout to source DB",
    "Schema mismatch on column revenue",
    "Out of memory during aggregation",
]

USER_ACTIONS = [
    "query_executed",
    "dashboard_viewed",
    "export_requested",
    "schema_browsed",
    "pipeline_triggered",
]

TABLES = ["customers", "orders", "products", "fact_revenue"]

shutdown_event = asyncio.Event()


def _retry(fn, name, retries=3, backoff_base=2):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            wait = backoff_base ** attempt
            logger.warning(
                "%s connection attempt %d/%d failed: %s (retrying in %ds)",
                name, attempt, retries, exc, wait,
            )
            time.sleep(wait)
    raise last_exc


def get_pg_connection():
    return _retry(
        lambda: psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT, dbname=POSTGRES_DB,
            user=POSTGRES_USER, password=POSTGRES_PASSWORD,
        ),
        "postgres",
    )


def get_mongo_client():
    client = _retry(
        lambda: MongoClient(host=MONGO_HOST, port=MONGO_PORT, serverSelectionTimeoutMS=5000),
        "mongo",
    )
    client.admin.command("ping")
    return client


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"http://{SEAWEEDFS_HOST}:{SEAWEEDFS_PORT}",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "dataops"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "dataops123"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )


def _random_hex(n=8):
    return "".join(random.choices("0123456789abcdef", k=n))


def generate_products(conn, count):
    rows = []
    with conn.cursor() as cur:
        for _ in range(count):
            name = f"{random.choice(PRODUCT_NAME_STEMS)} {fake.word().capitalize()}"
            category = random.choice(PRODUCT_CATEGORIES)
            price = round(random.uniform(29, 999), 2)
            sku = f"SKU-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
            cur.execute(
                """
                INSERT INTO products (name, category, price, sku)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (sku) DO NOTHING
                RETURNING id
                """,
                (name, category, price, sku),
            )
            row = cur.fetchone()
            if row:
                rows.append(row[0])
    conn.commit()
    return rows


def generate_customers(conn, count):
    inserted = []
    with conn.cursor() as cur:
        for _ in range(count):
            name = fake.name()
            email = f"{fake.user_name()}{_random_hex(4)}@{fake.free_email_domain()}"
            plan = random.choices(["free", "pro", "enterprise"], weights=[60, 30, 10], k=1)[0]
            company = fake.company()
            cur.execute(
                """
                INSERT INTO customers (name, email, plan, company)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING id
                """,
                (name, email, plan, company),
            )
            row = cur.fetchone()
            if row:
                inserted.append(row[0])
    conn.commit()
    return inserted


def generate_orders(conn, count):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM customers ORDER BY random() LIMIT 200")
        customer_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT id, price FROM products ORDER BY random() LIMIT 200")
        products = cur.fetchall()

    if not customer_ids or not products:
        logger.info("orders skipped: no customers or products yet")
        return 0

    status_choices = ["completed", "pending", "failed", "refunded"]
    status_weights = [70, 15, 10, 5]

    inserted = 0
    with conn.cursor() as cur:
        for _ in range(count):
            customer_id = random.choice(customer_ids)
            product_id, price = random.choice(products)
            quantity = random.randint(1, 5)
            amount = round(float(price) * quantity, 2)
            status = random.choices(status_choices, weights=status_weights, k=1)[0]
            cur.execute(
                """
                INSERT INTO orders (customer_id, product_id, amount, quantity, status)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (customer_id, product_id, amount, quantity, status),
            )
            inserted += 1
    conn.commit()
    return inserted


def bootstrap_products(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM products")
        (count,) = cur.fetchone()
    if count == 0:
        logger.info("bootstrapping initial products")
        generate_products(conn, 8)


def generate_postgres_data(cycle_count):
    conn = get_pg_connection()
    try:
        new_customers = generate_customers(conn, random.randint(2, 5))
        new_products = []
        if cycle_count % 5 == 0:
            new_products = generate_products(conn, random.randint(1, 3))
        new_orders = generate_orders(conn, random.randint(5, 15))
        return {
            "customers": len(new_customers),
            "products": len(new_products),
            "orders": new_orders,
        }
    finally:
        conn.close()


def generate_event_logs(count):
    docs = []
    for _ in range(count):
        pipeline = random.choice(PIPELINE_NAMES)
        status = random.choices(["completed", "failed", "warning"], weights=[85, 10, 5], k=1)[0]
        is_hourly = pipeline == "etl_orders_hourly"
        duration = random.randint(10, 120) if is_hourly else random.randint(30, 600)
        severity = {"completed": "info", "warning": "warning", "failed": "critical"}[status]
        error_message = None
        records_processed = random.randint(1000, 100000)
        if status == "failed":
            error_message = random.choice(FAILED_ERROR_MESSAGES)
            records_processed = 0
        docs.append({
            "pipeline_name": pipeline,
            "status": status,
            "error_message": error_message,
            "severity": severity,
            "duration_seconds": duration,
            "records_processed": records_processed,
            "timestamp": datetime.now(timezone.utc),
        })
    return docs


def generate_user_activity(count):
    docs = []
    for _ in range(count):
        action = random.choice(USER_ACTIONS)
        if action == "query_executed":
            metadata = {
                "query_type": "SELECT",
                "table": random.choice(TABLES),
                "rows_returned": random.randint(1, 5000),
                "execution_time_ms": random.randint(20, 2000),
            }
        elif action == "dashboard_viewed":
            metadata = {"dashboard": random.choice(["Revenue Overview", "Customer Health", "Pipeline Monitor"])}
        elif action == "export_requested":
            metadata = {"format": random.choice(["csv", "xlsx", "pdf"]), "table": random.choice(TABLES)}
        elif action == "schema_browsed":
            metadata = {"schema": random.choice(["public", "analytics"])}
        else:  # pipeline_triggered
            metadata = {"pipeline_name": random.choice(PIPELINE_NAMES)}

        docs.append({
            "user_id": f"usr_{_random_hex()}",
            "action": action,
            "metadata": metadata,
            "session_id": f"sess_{_random_hex()}",
            "timestamp": datetime.now(timezone.utc),
        })
    return docs


def generate_mongo_data(mongo_client):
    db = mongo_client[MONGO_DB_NAME]
    event_logs = generate_event_logs(random.randint(3, 8))
    user_activity = generate_user_activity(random.randint(5, 10))
    if event_logs:
        db.event_logs.insert_many(event_logs)
    if user_activity:
        db.user_activity.insert_many(user_activity)
    return {"event_logs": len(event_logs), "user_activity": len(user_activity)}


def upload_daily_report(s3_client):
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM customers")
            (total_customers,) = cur.fetchone()
            cur.execute("SELECT count(*) FROM orders")
            (total_orders,) = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(amount), 0) FROM orders WHERE status = 'completed'")
            (total_revenue,) = cur.fetchone()
    finally:
        conn.close()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "value"])
    writer.writerow(["total_customers", total_customers])
    writer.writerow(["total_orders", total_orders])
    writer.writerow(["total_completed_revenue", total_revenue])
    writer.writerow(["generated_at", datetime.now(timezone.utc).isoformat()])

    key = f"reports/daily-summary-{today}.csv"
    s3_client.put_object(
        Bucket=SEAWEEDFS_BUCKET,
        Key=key,
        Body=buffer.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    return key


async def run_cycle(cycle_count, mongo_client, s3_client):
    loop = asyncio.get_running_loop()
    tasks = {
        "postgres": loop.run_in_executor(None, generate_postgres_data, cycle_count),
        "mongo": loop.run_in_executor(None, generate_mongo_data, mongo_client),
    }
    if cycle_count % 10 == 0:
        tasks["seaweedfs"] = loop.run_in_executor(None, upload_daily_report, s3_client)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for store, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            logger.error("store=%s cycle=%d error=%s", store, cycle_count, result)
        else:
            logger.info("store=%s cycle=%d records_generated=%s", store, cycle_count, result)


def _handle_shutdown_signal(*_args):
    logger.info("shutdown signal received, finishing current cycle...")
    shutdown_event.set()


async def main():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_shutdown_signal)

    logger.info("connecting to Postgres, MongoDB, and SeaweedFS...")
    bootstrap_conn = get_pg_connection()
    try:
        bootstrap_products(bootstrap_conn)
    finally:
        bootstrap_conn.close()

    mongo_client = get_mongo_client()
    s3_client = get_s3_client()

    logger.info("data generator started, interval=%ds", INTERVAL_SECONDS)

    cycle_count = 0
    try:
        while not shutdown_event.is_set():
            cycle_count += 1
            cycle_start = time.monotonic()
            try:
                await run_cycle(cycle_count, mongo_client, s3_client)
            except Exception:
                logger.exception("cycle %d failed", cycle_count)

            elapsed = time.monotonic() - cycle_start
            remaining = max(0, INTERVAL_SECONDS - elapsed)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
    finally:
        logger.info("shutting down, closing connections")
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
