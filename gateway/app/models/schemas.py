from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    top_k: int = Field(5, ge=1, le=20)
    collection: str = Field("default", pattern=r"^[a-z0-9_-]+$")


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    collection: str = Field("default", pattern=r"^[a-z0-9_-]+$")


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class QueryResponse(BaseModel):
    job_id: str
    status: JobStatus
    cached: bool = False
    answer: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


class IngestResponse(BaseModel):
    job_id: str
    status: JobStatus


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HealthResponse(BaseModel):
    status: str
    kafka: str
    redis: str
