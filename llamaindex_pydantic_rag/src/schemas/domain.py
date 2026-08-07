"""Domain models representing the business entities of the DataOps Knowledge Hub.

Used for structured extraction during ingestion and as output schemas for
the Ledger, Memory, and Brain query engines.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CustomerPlan(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class OrderStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class PipelineStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    WARNING = "warning"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Customer(BaseModel):
    """A customer entity from the Ledger (PostgreSQL)."""

    id: int
    name: str
    email: str
    plan: CustomerPlan
    company: Optional[str] = None
    created_at: datetime


class Order(BaseModel):
    """An order entity from the Ledger (PostgreSQL)."""

    id: int
    customer_id: int
    product_id: int
    amount: float = Field(description="Order total in BRL")
    quantity: int
    status: OrderStatus
    created_at: datetime


class PipelineEvent(BaseModel):
    """A pipeline execution event from Memory (MongoDB)."""

    pipeline_name: str
    status: PipelineStatus
    error_message: Optional[str] = None
    severity: Severity
    duration_seconds: int
    records_processed: int
    timestamp: datetime


class PipelineNode(BaseModel):
    """A pipeline node from the Brain (Neo4j)."""

    name: str
    schedule: str
    owner: str
    sla_minutes: int


class TableNode(BaseModel):
    """A table node from the Brain (Neo4j)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    schema_name: str = Field(alias="schema")
    database: str
    row_count: int


class DependencyChain(BaseModel):
    """Represents downstream dependencies of a pipeline or table."""

    source: str = Field(description="The originating pipeline or table name")
    downstream_pipelines: list[str] = Field(default_factory=list)
    downstream_tables: list[str] = Field(default_factory=list)
    downstream_dashboards: list[str] = Field(default_factory=list)
    impacted_teams: list[str] = Field(default_factory=list)
