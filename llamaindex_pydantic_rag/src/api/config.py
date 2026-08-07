"""Configuration for the API layer's health checks.

Separate from src/engines/config.py's EngineConfig (which RouterEngine consumes)
because health checks additionally need MongoDB/SeaweedFS connectivity info that
the engines never touch directly.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class APIConfig(BaseSettings):
    """Connectivity settings for health-checking every backing service."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL (Ledger)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "dataops"
    postgres_user: str = "dataops"
    postgres_password: str = "dataops123"

    # Qdrant (Memory)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # Neo4j (Brain)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "dataops123"

    # MongoDB (Events)
    mongo_host: str = "localhost"
    mongo_port: int = 27017

    # SeaweedFS (Data Lake) -- /cluster/status lives on the master port, not the S3 port
    seaweedfs_host: str = "localhost"
    seaweedfs_master_port: int = 9333
