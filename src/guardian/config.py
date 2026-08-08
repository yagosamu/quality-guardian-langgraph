"""Configuration for the Quality Guardian agent.

Loads `.env` on import so every entrypoint (CLI, Chainlit, MCP, tests) that
imports this module gets `ANTHROPIC_API_KEY` and friends in the environment
without repeating the load elsewhere.
"""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

# --- Ledger (Postgres of W01) ---
PG_HOST = os.getenv("GUARDIAN_PG_HOST", "localhost")
PG_PORT = os.getenv("GUARDIAN_PG_PORT", "5442")
PG_DB = os.getenv("GUARDIAN_PG_DB", "dataops")
PG_USER = os.getenv("GUARDIAN_PG_USER", "dataops")
PG_PASSWORD = os.getenv("GUARDIAN_PG_PASSWORD", "dataops123")

PG_CONNINFO = (
    f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}?sslmode=disable"
)

# --- Models ---
LLM_MODEL = os.getenv("GUARDIAN_LLM_MODEL", "anthropic:claude-sonnet-4-6")

# Evaluator-optimizer (prompt 05): cheap model proposes fixes, strong model judges them.
GENERATOR_MODEL = os.getenv("GUARDIAN_GENERATOR_MODEL", "anthropic:claude-haiku-4-5")
EVALUATOR_MODEL = os.getenv("GUARDIAN_EVALUATOR_MODEL", "anthropic:claude-sonnet-4-6")

# --- Validation window (N most recent records; the Ledger never stops growing) ---
WINDOW = int(os.getenv("GUARDIAN_WINDOW", "50"))

# --- Graph behavior ---
MAX_RETRIES = int(os.getenv("GUARDIAN_MAX_RETRIES", "2"))
RECURSION_LIMIT = int(os.getenv("GUARDIAN_RECURSION_LIMIT", "25"))
GREEN_AT = float(os.getenv("GUARDIAN_GREEN_AT", "0.8"))
YELLOW_AT = float(os.getenv("GUARDIAN_YELLOW_AT", "0.5"))
