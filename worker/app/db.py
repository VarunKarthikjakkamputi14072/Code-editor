import asyncpg
from pgvector.asyncpg import register_vector

from app.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.postgres_dsn,
            min_size=2,
            max_size=10,
            init=_init_conn,
        )
    return _pool


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE EXTENSION IF NOT EXISTS vector;

            CREATE TABLE IF NOT EXISTS documents (
                id          BIGSERIAL PRIMARY KEY,
                collection  TEXT NOT NULL DEFAULT 'default',
                chunk_index INT NOT NULL DEFAULT 0,
                content     TEXT NOT NULL,
                metadata    JSONB NOT NULL DEFAULT '{}',
                embedding   VECTOR(768),
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_documents_collection
                ON documents (collection);

            CREATE INDEX IF NOT EXISTS idx_documents_embedding
                ON documents USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);

            CREATE TABLE IF NOT EXISTS jobs (
                job_id      TEXT PRIMARY KEY,
                status      TEXT NOT NULL DEFAULT 'pending',
                query       TEXT,
                answer      TEXT,
                sources     JSONB NOT NULL DEFAULT '[]',
                error       TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)


async def upsert_job(pool: asyncpg.Pool, job_id: str, **kwargs) -> None:
    fields = {k: v for k, v in kwargs.items()}
    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
    values = list(fields.values())
    await pool.execute(
        f"""
        INSERT INTO jobs (job_id, {', '.join(fields)}, updated_at)
        VALUES ($1, {', '.join(f'${i+2}' for i in range(len(fields)))}, NOW())
        ON CONFLICT (job_id) DO UPDATE SET {set_clause}, updated_at = NOW()
        """,
        job_id, *values,
    )


async def insert_document_chunk(
    pool: asyncpg.Pool,
    collection: str,
    chunk_index: int,
    content: str,
    metadata: dict,
    embedding: list[float],
) -> int:
    import json
    row = await pool.fetchrow(
        """
        INSERT INTO documents (collection, chunk_index, content, metadata, embedding)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        collection, chunk_index, content, json.dumps(metadata), embedding,
    )
    return row["id"]


async def similarity_search(
    pool: asyncpg.Pool,
    collection: str,
    embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, content, metadata,
               1 - (embedding <=> $1) AS score
        FROM documents
        WHERE collection = $2
        ORDER BY embedding <=> $1
        LIMIT $3
        """,
        embedding, collection, top_k,
    )
    return [
        {"id": r["id"], "content": r["content"], "metadata": dict(r["metadata"]), "score": float(r["score"])}
        for r in rows
    ]
