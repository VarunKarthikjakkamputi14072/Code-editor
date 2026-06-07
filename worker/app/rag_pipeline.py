import json
import structlog

from app.config import settings
from app.db import get_pool, similarity_search, upsert_job, insert_document_chunk
from app.embeddings import embed, generate
from app.chunker import chunk_text

log = structlog.get_logger()


async def handle_query(message: dict) -> dict:
    job_id = message["job_id"]
    query = message["query"]
    top_k = message.get("top_k", 5)
    collection = message.get("collection", "default")

    pool = await get_pool()
    await upsert_job(pool, job_id, status="processing", query=query)

    try:
        query_embedding = await embed(query)
        sources = await similarity_search(pool, collection, query_embedding, top_k)

        context_chunks = [s["content"] for s in sources]
        answer = await generate(query, context_chunks)

        await upsert_job(
            pool, job_id,
            status="completed",
            answer=answer,
            sources=json.dumps(sources),
        )

        log.info("query_completed", job_id=job_id, sources=len(sources))
        return {"job_id": job_id, "status": "completed", "answer": answer, "sources": sources}

    except Exception as exc:
        log.error("query_failed", job_id=job_id, error=str(exc))
        await upsert_job(pool, job_id, status="failed", error=str(exc))
        raise


async def handle_ingest(message: dict) -> None:
    job_id = message["job_id"]
    text = message["text"]
    metadata = message.get("metadata", {})
    collection = message.get("collection", "default")

    pool = await get_pool()
    await upsert_job(pool, job_id, status="processing")

    try:
        chunks = chunk_text(text)
        log.info("ingesting_chunks", job_id=job_id, count=len(chunks))

        for idx, chunk in enumerate(chunks):
            embedding = await embed(chunk)
            await insert_document_chunk(pool, collection, idx, chunk, metadata, embedding)

        await upsert_job(pool, job_id, status="completed")
        log.info("ingest_completed", job_id=job_id, chunks=len(chunks))

    except Exception as exc:
        log.error("ingest_failed", job_id=job_id, error=str(exc))
        await upsert_job(pool, job_id, status="failed", error=str(exc))
        raise
