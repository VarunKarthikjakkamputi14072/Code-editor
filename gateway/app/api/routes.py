import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.auth import FAKE_USERS, create_access_token, get_current_user, verify_password
from app.core.config import settings
from app.core.kafka_producer import publish
from app.core.redis_cache import (
    get_cached,
    get_job_status,
    incr_rate_limit,
    set_cached,
    set_job_status,
)
from app.models.schemas import (
    HealthResponse,
    IngestRequest,
    IngestResponse,
    JobStatus,
    QueryRequest,
    QueryResponse,
    TokenResponse,
)

log = structlog.get_logger()
router = APIRouter()


async def _check_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"kuberag:rate:{client_ip}"
    count = await incr_rate_limit(key, settings.rate_limit_window_seconds)
    if count > settings.rate_limit_requests:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post("/auth/token", response_model=TokenResponse, tags=["auth"])
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user = FAKE_USERS.get(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad credentials")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@router.post("/query", response_model=QueryResponse, status_code=status.HTTP_202_ACCEPTED, tags=["rag"])
async def submit_query(
    body: QueryRequest,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    await _check_rate_limit(request)

    cached = await get_cached(body.query)
    if cached:
        log.info("cache_hit", query=body.query[:60])
        return QueryResponse(
            job_id=cached["job_id"],
            status=JobStatus.completed,
            cached=True,
            answer=cached.get("answer"),
            sources=cached.get("sources", []),
        )

    job_id = str(uuid.uuid4())
    # Fix 4: generate a trace_id (or honour one forwarded by an upstream proxy).
    # It travels in the Kafka payload so the worker can bind it to its own logs,
    # making the full request lifecycle searchable by a single ID.
    trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
    log.bind(job_id=job_id, trace_id=trace_id).info("query_submitted")

    payload = {
        "job_id": job_id,
        "trace_id": trace_id,
        "query": body.query,
        "top_k": body.top_k,
        "collection": body.collection,
    }

    await set_job_status(job_id, {"status": JobStatus.pending, "job_id": job_id})
    await publish(settings.kafka_query_topic, payload, key=job_id)

    return QueryResponse(job_id=job_id, status=JobStatus.pending)


@router.get("/query/{job_id}", response_model=QueryResponse, tags=["rag"])
async def get_query_result(
    job_id: str,
    _user: Annotated[dict, Depends(get_current_user)],
):
    state = await get_job_status(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    return QueryResponse(**state)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED, tags=["ingest"])
async def ingest_document(
    body: IngestRequest,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    await _check_rate_limit(request)

    job_id = str(uuid.uuid4())
    trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
    log.bind(job_id=job_id, trace_id=trace_id).info("ingest_submitted")

    payload = {
        "job_id": job_id,
        "trace_id": trace_id,
        "text": body.text,
        "metadata": body.metadata,
        "collection": body.collection,
    }

    await set_job_status(job_id, {"status": JobStatus.pending, "job_id": job_id})
    await publish(settings.kafka_ingest_topic, payload, key=job_id)

    return IngestResponse(job_id=job_id, status=JobStatus.pending)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse, tags=["ops"], include_in_schema=False)
async def health():
    from app.core.redis_cache import get_redis

    kafka_status = "ok"
    redis_status = "ok"

    try:
        redis = await get_redis()
        await redis.ping()
    except Exception:
        redis_status = "unreachable"

    return HealthResponse(status="ok", kafka=kafka_status, redis=redis_status)
