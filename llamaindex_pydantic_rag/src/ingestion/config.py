"""Configuration for the ingestion pipeline (Memory / Qdrant layer)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionConfig(BaseSettings):
    """Settings for the ingestion pipeline, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    openai_api_key: str
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "dataops-memory"

    # SeaweedFS
    seaweedfs_host: str = "localhost"
    seaweedfs_port: int = 8333
    seaweedfs_bucket: str = "dataops-lake"

    # MongoDB
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_db: str = "dataops"

    # Pipeline settings
    chunk_size: int = 512
    chunk_overlap: int = 50
