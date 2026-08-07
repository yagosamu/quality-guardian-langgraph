"""Custom readers that pull unstructured/semi-structured data into LlamaIndex Documents.

Only SeaweedFS (governance docs, data dictionary) and MongoDB (event_logs,
user_activity) feed the Memory engine — PostgreSQL and Neo4j are queried
directly (Text-to-SQL / Cypher) and are never ingested here.
"""

import io
import logging
from datetime import datetime, timedelta, timezone

import boto3
from llama_index.core.schema import Document
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.ingestion.config import IngestionConfig

logger = logging.getLogger(__name__)


class SeaweedFSReader:
    """Reads governance/reference documents from the SeaweedFS S3-compatible data lake."""

    def __init__(self, config: IngestionConfig):
        self.config = config

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=f"http://{self.config.seaweedfs_host}:{self.config.seaweedfs_port}",
            aws_access_key_id="dataops",
            aws_secret_access_key="dataops123",
            region_name="us-east-1",
        )

    def _extract_text(self, key: str, body: bytes, file_type: str) -> str | None:
        if file_type == "pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                logger.warning("pypdf not installed, skipping PDF %s", key)
                return None
            try:
                reader = PdfReader(io.BytesIO(body))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as exc:
                logger.warning("failed to parse PDF %s: %s", key, exc)
                return None
        return body.decode("utf-8", errors="ignore")

    def load_data(self) -> list[Document]:
        documents: list[Document] = []
        try:
            client = self._client()
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.config.seaweedfs_bucket):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    file_name = key.rsplit("/", 1)[-1]
                    file_type = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "unknown"

                    try:
                        body = client.get_object(Bucket=self.config.seaweedfs_bucket, Key=key)["Body"].read()
                    except Exception as exc:
                        logger.warning("failed to download %s from SeaweedFS: %s", key, exc)
                        continue

                    text = self._extract_text(key, body, file_type)
                    if not text or not text.strip():
                        continue

                    upload_date = obj.get("LastModified") or datetime.now(timezone.utc)
                    documents.append(
                        Document(
                            text=text,
                            metadata={
                                "source_type": "seaweedfs",
                                "file_name": file_name,
                                "file_type": file_type,
                                "upload_date": upload_date.isoformat(),
                            },
                        )
                    )
        except Exception as exc:
            logger.warning("SeaweedFS reader unavailable: %s", exc)
            return []
        return documents


class MongoDBReader:
    """Reads recent event_logs and user_activity entries from MongoDB (Memory layer)."""

    def __init__(self, config: IngestionConfig, lookback_hours: int = 24):
        self.config = config
        self.lookback_hours = lookback_hours

    def _client(self) -> MongoClient:
        return MongoClient(
            host=self.config.mongo_host,
            port=self.config.mongo_port,
            serverSelectionTimeoutMS=5000,
        )

    def _event_log_document(self, log: dict) -> Document:
        text = (
            f"Pipeline '{log.get('pipeline_name')}' run at {log.get('timestamp')}: "
            f"status={log.get('status')}, severity={log.get('severity')}, "
            f"duration={log.get('duration_seconds')}s, "
            f"records_processed={log.get('records_processed')}."
        )
        if log.get("error_message"):
            text += f" Error: {log['error_message']}"
        return Document(
            text=text,
            metadata={
                "source_type": "mongodb",
                "collection": "event_logs",
                "pipeline_name": log.get("pipeline_name"),
                "status": log.get("status"),
                "severity": log.get("severity"),
            },
        )

    def _user_activity_document(self, activity: dict) -> Document:
        metadata_str = ", ".join(f"{k}={v}" for k, v in (activity.get("metadata") or {}).items())
        text = (
            f"User {activity.get('user_id')} performed '{activity.get('action')}' "
            f"at {activity.get('timestamp')} (session {activity.get('session_id')})."
        )
        if metadata_str:
            text += f" Details: {metadata_str}."
        return Document(
            text=text,
            metadata={
                "source_type": "mongodb",
                "collection": "user_activity",
                "action": activity.get("action"),
                "user_id": activity.get("user_id"),
            },
        )

    def load_data(self) -> list[Document]:
        documents: list[Document] = []
        client = None
        try:
            client = self._client()
            db = client[self.config.mongo_db]
            since = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)

            for log in db.event_logs.find({"timestamp": {"$gte": since}}):
                documents.append(self._event_log_document(log))

            for activity in db.user_activity.find({"timestamp": {"$gte": since}}):
                documents.append(self._user_activity_document(activity))
        except PyMongoError as exc:
            logger.warning("MongoDB reader unavailable: %s", exc)
            return []
        finally:
            if client is not None:
                client.close()
        return documents
