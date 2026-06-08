import asyncio
import hashlib
import json
import signal

import redis.asyncio as aioredis
import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from app.config import settings
from app.db import close_pool, ensure_schema, get_pool, upsert_job
from app.rag_pipeline import handle_ingest, handle_query

log = structlog.get_logger()
_shutdown = asyncio.Event()

# Idempotency lock TTL: long enough to cover the worst-case generation time.
_LOCK_TTL_SECONDS = 3600


def _handle_signal(sig, frame):
    log.info("shutdown_signal_received", signal=sig)
    _shutdown.set()


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _acquire_lock(redis: aioredis.Redis, job_id: str) -> bool:
    """SETNX-based idempotency lock. Returns True if this worker owns the job."""
    acquired = await redis.setnx(f"kuberag:lock:{job_id}", "1")
    if acquired:
        await redis.expire(f"kuberag:lock:{job_id}", _LOCK_TTL_SECONDS)
    return bool(acquired)


async def _update_redis_status(redis: aioredis.Redis, job_id: str, result: dict) -> None:
    try:
        await redis.setex(
            f"kuberag:job:{job_id}",
            86400,
            json.dumps({**result, "job_id": job_id}),
        )
        if result.get("status") == "completed" and result.get("answer"):
            query = result.get("query", "")
            if query:
                digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()
                await redis.setex(
                    f"kuberag:cache:{digest}",
                    settings.cache_ttl_seconds,
                    json.dumps(result),
                )
    except Exception as exc:
        log.warning("redis_update_failed", error=str(exc))


async def consume_loop(topic: str, handler) -> None:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        max_poll_records=settings.kafka_max_poll_records,
        value_deserializer=lambda v: json.loads(v.decode()),
    )

    while not _shutdown.is_set():
        try:
            await consumer.start()
            log.info("consumer_started", topic=topic)
            break
        except KafkaConnectionError:
            log.warning("kafka_not_ready", topic=topic, retry_in=5)
            await asyncio.sleep(5)

    redis = await _get_redis()
    try:
        async for msg in consumer:
            if _shutdown.is_set():
                break

            payload = msg.value
            job_id = payload.get("job_id", "unknown")
            # Extract trace_id injected by the gateway; fall back to job_id for
            # backwards compatibility. Bind to every log line in this handler.
            trace_id = payload.get("trace_id", job_id)
            bound_log = log.bind(topic=topic, job_id=job_id, trace_id=trace_id, offset=msg.offset)

            bound_log.info("message_received")

            # Fix 3: idempotency lock - SETNX returns False if another worker
            # already claimed this job_id. Commit and skip to avoid duplicate
            # LLM calls and redundant DB writes on at-least-once redelivery.
            if not await _acquire_lock(redis, job_id):
                bound_log.info("job_already_claimed_skipping")
                await consumer.commit()
                continue

            try:
                result = await handler(payload)
                if result:
                    await _update_redis_status(redis, job_id, result)
            except Exception as exc:
                bound_log.error("handler_error", error=str(exc))

            await consumer.commit()
    finally:
        await consumer.stop()
        await redis.aclose()


async def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )

    log.info("worker_starting")
    await ensure_schema()

    await asyncio.gather(
        consume_loop(settings.kafka_query_topic, handle_query),
        consume_loop(settings.kafka_ingest_topic, handle_ingest),
    )

    await close_pool()
    log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
