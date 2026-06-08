# KubeRAG — Distributed AI Inference Engine

A production-grade, fault-tolerant Retrieval-Augmented Generation platform built on Kubernetes, Kafka, and pgvector. Ingestion, embedding, and LLM inference run as isolated, auto-scaling microservices decoupled by an async message queue.

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │            Kubernetes Cluster            │
                        │                                          │
  Client ──────────────►│  FastAPI Gateway  (Deployment, HPA)     │
                        │       │        │                         │
                        │    Redis     Kafka (StatefulSet)         │
                        │  (cache/    (query-ingestion topic)      │
                        │   jobs)     (doc-ingestion topic)        │
                        │                  │                       │
                        │         Worker Pods (Deployment, HPA)   │
                        │                  │                       │
                        │        PostgreSQL + pgvector             │
                        │         (StatefulSet, IVFFlat)           │
                        │                  │                       │
                        │          Ollama (Deployment)             │
                        │    nomic-embed-text + llama3             │
                        └─────────────────────────────────────────┘
```

### Request Flow

1. **Client** sends `POST /api/v1/query` with a natural-language question.
2. **Gateway** checks Redis for a semantic cache hit (SHA-256 keyed).
3. **Cache miss** → Gateway publishes a message to the `query-ingestion` Kafka topic and returns `202 Accepted` with a `job_id`.
4. **Worker pod** consumes the message, embeds the query via Ollama (`nomic-embed-text`), runs a cosine similarity search against pgvector, then calls `llama3` for generation.
5. Worker writes the result to PostgreSQL, updates Redis (job status + cache), and commits the Kafka offset.
6. **Client** polls `GET /api/v1/query/{job_id}` until `status == "completed"`.

Kafka provides **backpressure**: 1 000 concurrent queries queue safely — workers pull at the rate their resources allow. A crashed worker leaves its offset uncommitted, so another pod in the consumer group retries automatically.

## Services

| Service | Type | Image | Scales |
|---------|------|-------|--------|
| `gateway` | FastAPI API gateway | `kuberag/gateway` | HPA 2–10 pods |
| `worker` | Kafka consumer + RAG pipeline | `kuberag/worker` | HPA 2–20 pods |
| `postgres` | Vector + state storage | `pgvector/pgvector:pg16` | StatefulSet |
| `kafka` | Async message broker (KRaft) | `confluentinc/cp-kafka:7.6.1` | StatefulSet |
| `redis` | Semantic cache + rate limiting | `redis:7-alpine` | Deployment |
| `ollama` | Embedding + generation engine | `ollama/ollama` | Deployment |

## Quick Start — Local (Docker Compose)

```bash
# 1. Start all services
docker compose up --build -d

# 2. Pull Ollama models (run once)
docker compose --profile init run --rm ollama-init

# 3. Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=admin" | jq -r .access_token)

# 4. Ingest a document
curl -s -X POST http://localhost:8000/api/v1/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "KubeRAG is a distributed RAG platform built on Kubernetes and Kafka.", "collection": "demo"}'

# 5. Submit a query
JOB=$(curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is KubeRAG?", "collection": "demo"}' | jq -r .job_id)

# 6. Poll for the result
curl -s http://localhost:8000/api/v1/query/$JOB \
  -H "Authorization: Bearer $TOKEN" | jq .
```

## Demo on a Real Dataset (SQuAD)

Beyond the toy example above, [`demo/`](demo/) runs KubeRAG end-to-end against a
real benchmark — the **Stanford Question Answering Dataset (SQuAD v1.1)** — and
reports answer accuracy and latency. It treats SQuAD's Wikipedia passages as the
corpus and its human-written questions + gold answers as the evaluation set.

```bash
python demo/prepare_dataset.py --passages 50 --questions 40   # fetch real data
python demo/seed.py        # ingest the corpus (chunk → embed → pgvector)
python demo/evaluate.py    # score answers vs. ground truth, report p50/p95 latency
python demo/load_test.py --concurrency 200   # show Kafka backpressure under a burst
```

All demo scripts are pure Python stdlib (no `pip install`). See
[`demo/README.md`](demo/README.md) for the full walkthrough, use-case framing, and
expected output.

## Kubernetes Deployment

### Prerequisites

- `kubectl` configured against a cluster (Minikube, Kind, or cloud)
- `kustomize` (bundled with `kubectl >= 1.14`)

```bash
# 1. Build and push images (replace with your registry)
docker build -t your-registry/kuberag-gateway:latest ./gateway
docker build -t your-registry/kuberag-worker:latest ./worker
docker push your-registry/kuberag-gateway:latest
docker push your-registry/kuberag-worker:latest

# 2. Update image references in k8s/gateway/deployment.yaml and k8s/worker/deployment.yaml

# 3. Rotate the secret key
echo -n "your-strong-secret" | base64
# Paste the output into k8s/secrets.yaml → data.secret-key

# 4. Apply the full stack
kubectl apply -k k8s/

# 5. Watch pods come up
kubectl get pods -n kuberag -w

# 6. Get the gateway external IP (LoadBalancer)
kubectl get svc gateway -n kuberag
```

### Local Cluster (Minikube)

```bash
minikube start --cpus 6 --memory 12g --driver docker
minikube addons enable metrics-server

# Use minikube's Docker daemon so images are available without a registry
eval $(minikube docker-env)
docker build -t kuberag/gateway:latest ./gateway
docker build -t kuberag/worker:latest ./worker

kubectl apply -k k8s/
minikube tunnel   # exposes the LoadBalancer service
```

## API Reference

All endpoints require a `Bearer` token except `/api/v1/health`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/token` | Get JWT (form: username/password) |
| `POST` | `/api/v1/query` | Submit a RAG query → `202` + `job_id` |
| `GET` | `/api/v1/query/{job_id}` | Poll job status / retrieve answer |
| `POST` | `/api/v1/ingest` | Ingest a document → `202` + `job_id` |
| `GET` | `/api/v1/health` | Health probe (Kafka + Redis status) |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/docs` | Swagger UI |

### Query response schema

```json
{
  "job_id": "uuid",
  "status": "pending | processing | completed | failed",
  "cached": false,
  "answer": "...",
  "sources": [
    {"id": 1, "content": "...", "metadata": {}, "score": 0.94}
  ]
}
```

## Configuration

All services are configured via environment variables (or `.env` for local dev):

### Gateway

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka broker address |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `SECRET_KEY` | `change-me` | JWT signing key |
| `RATE_LIMIT_REQUESTS` | `100` | Requests per window per IP |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window |
| `CACHE_TTL_SECONDS` | `3600` | Semantic cache TTL |

### Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka broker address |
| `POSTGRES_DSN` | `postgresql://...` | PostgreSQL connection string |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama service URL |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model name |
| `GEN_MODEL` | `llama3` | Generation model name |
| `CHUNK_SIZE` | `512` | Words per document chunk |
| `CHUNK_OVERLAP` | `64` | Overlap between chunks |

## Observability

- **Metrics** — Prometheus metrics at `GET /metrics` (request count, latency histograms, in-flight requests via `prometheus-fastapi-instrumentator`)
- **Logs** — Structured JSON via `structlog` on all services; ship to Loki or any log aggregator
- **Health** — `GET /api/v1/health` reports Kafka and Redis reachability; wired to Kubernetes readiness/liveness probes

## Project Structure

```
.
├── gateway/                # FastAPI API gateway
│   ├── app/
│   │   ├── api/routes.py   # /query, /ingest, /auth, /health
│   │   ├── core/           # config, Kafka producer, Redis cache, auth
│   │   └── models/schemas.py
│   ├── Dockerfile
│   └── requirements.txt
├── worker/                 # Kafka consumer + RAG pipeline
│   ├── app/
│   │   ├── consumer.py     # Kafka consumer loop (2 topics)
│   │   ├── rag_pipeline.py # embed → search → generate → store
│   │   ├── db.py           # asyncpg + pgvector
│   │   ├── embeddings.py   # Ollama embed/generate with retry
│   │   └── chunker.py      # sliding-window text chunker
│   ├── Dockerfile
│   └── requirements.txt
├── k8s/                    # Kubernetes manifests (Kustomize)
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── secrets.yaml
│   ├── postgres/           # StatefulSet + headless Service
│   ├── kafka/              # StatefulSet (KRaft) + headless Service
│   ├── redis/              # Deployment + Service
│   ├── ollama/             # Deployment + Service
│   ├── gateway/            # Deployment + LoadBalancer + HPA
│   └── worker/             # Deployment + HPA
├── docker-compose.yml      # Local development
├── init.sql                # PostgreSQL schema bootstrap
└── README.md
```
