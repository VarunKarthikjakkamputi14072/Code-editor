-- Bootstrap the kuberag schema.
-- Run automatically on first container start via docker-entrypoint-initdb.d.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    collection  TEXT NOT NULL DEFAULT 'default',
    chunk_index INT  NOT NULL DEFAULT 0,
    content     TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}',
    embedding   VECTOR(768),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents (collection);

-- HNSW index: graph-based, handles continuous inserts without needing REINDEX.
-- IVFFlat computes centroids on existing data, so creating it on an empty table
-- collapses all vectors into one list and destroys search performance.
-- m=16 controls graph connectivity; ef_construction=64 controls build-time recall.
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

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC);
