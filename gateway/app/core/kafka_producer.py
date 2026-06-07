import json
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import settings

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode(),
            acks="all",
            enable_idempotence=True,
        )
        await _producer.start()
    return _producer


async def stop_producer() -> None:
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None


async def publish(topic: str, payload: dict[str, Any], key: str | None = None) -> None:
    producer = await get_producer()
    key_bytes = key.encode() if key else None
    await producer.send_and_wait(topic, value=payload, key=key_bytes)
