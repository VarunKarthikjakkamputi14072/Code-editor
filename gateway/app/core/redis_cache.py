import hashlib
import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _pool


def _cache_key(query: str) -> str:
    digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()
    return f"kuberag:cache:{digest}"


async def get_cached(query: str) -> dict | None:
    redis = await get_redis()
    raw = await redis.get(_cache_key(query))
    if raw:
        return json.loads(raw)
    return None


async def set_cached(query: str, result: dict, ttl: int = settings.cache_ttl_seconds) -> None:
    redis = await get_redis()
    await redis.setex(_cache_key(query), ttl, json.dumps(result))


async def get_job_status(job_id: str) -> dict | None:
    redis = await get_redis()
    raw = await redis.get(f"kuberag:job:{job_id}")
    if raw:
        return json.loads(raw)
    return None


async def set_job_status(job_id: str, status: dict, ttl: int = 86400) -> None:
    redis = await get_redis()
    await redis.setex(f"kuberag:job:{job_id}", ttl, json.dumps(status))


async def incr_rate_limit(key: str, window: int) -> int:
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    results = await pipe.execute()
    return results[0]
