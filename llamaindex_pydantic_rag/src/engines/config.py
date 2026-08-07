"""Shared configuration for the Ledger, Memory, and Brain query engines."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineConfig(BaseSettings):
    """Settings for the query engines, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    openai_api_key: str
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"

    # PostgreSQL (Ledger)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "dataops"
    postgres_user: str = "dataops"
    postgres_password: str = "dataops123"

    # Qdrant (Memory)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "dataops-memory"

    # Neo4j (Brain)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "dataops123"

    @property
    def postgres_connection_string(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
