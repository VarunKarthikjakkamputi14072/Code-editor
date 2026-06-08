# KubeRAG — a RAG system that doesn't fall over under load

This is a "chat with your documents" engine, but the interesting part isn't the
chat — it's everything around it. Ingestion, embedding, and the actual LLM call run
as separate services, with Kafka sitting in the middle so the slow parts can't take
down the fast parts. It runs on Kubernetes and scales the heavy workers up and down
on their own.

## Why I built this

Back in my undergrad I built a small "PDF chatter" — upload a paper, ask it
questions, get answers. It worked fine for me and a few classmates. But it was a
single process: one slow request and everyone waited, and if it crashed mid-answer
the request was just gone.

That bugged me. So KubeRAG is me answering the follow-up question I never got to at
the time: *what does it actually take to run RAG for a lot of people at once?* The
answer turned out to be mostly about decoupling and backpressure, not about the AI
itself — which is the whole point of the project.

## How it works

```
                        ┌─────────────────────────────────────────┐
                        │            Kubernetes Cluster            │
                        │                                          │
  You ──────────────────►  FastAPI Gateway  (Deployment, HPA)     │
                        │       │        │                         │
                        │    Redis     Kafka (StatefulSet)         │
                        │  (cache/    (query + ingest topics)      │
                        │   jobs)            │                     │
                        │         Worker Pods (Deployment, HPA)   │
                        │                  │                       │
                        │        PostgreSQL + pgvector             │
                        │            (StatefulSet)                 │
                        │                  │                       │
                        │          Ollama (Deployment)             │
                        │    nomic-embed-text + llama3             │
                        └─────────────────────────────────────────┘
```

When you ask a question:

1. The **gateway** takes your query and first checks Redis — if someone asked the
   same thing recently, you get the cached answer immediately and we're done.
2. On a cache miss, the gateway drops the query onto a Kafka topic and hands you
   back a `job_id` with `202 Accepted`. It does **not** wait around for the LLM.
3. A **worker** picks the job up, embeds the query, searches pgvector for the most
   relevant chunks, and feeds those plus your question to `llama3`.
4. The worker saves the answer to Postgres, updates Redis, and only then commits
   the Kafka offset.
5. You poll `GET /query/{job_id}` until it says `completed`.

That Kafka-in-the-middle bit is the reason the whole thing exists. If a thousand
people ask questions at the same moment, they queue up safely instead of piling
onto the LLM and OOM-ing it — the workers just pull jobs as fast as they can handle
them. And because a worker only commits its offset *after* it finishes, a crash
mid-answer means another worker just picks the job back up. Nothing's lost.

## What's running

| Service | What it is | How it scales |
|---------|------------|---------------|
| `gateway` | FastAPI front door — auth, rate limiting, cache check, publishes to Kafka | HPA, 2–10 pods |
| `worker` | Pulls from Kafka, runs the RAG pipeline | HPA, 2–20 pods |
| `postgres` | pgvector — stores chunks, embeddings, and job state | StatefulSet |
| `kafka` | The queue that decouples everything (KRaft mode, no ZooKeeper) | StatefulSet |
| `redis` | Semantic cache + rate-limit counters | Deployment |
| `ollama` | Runs the embedding and generation models | Deployment + HPA |

## Try it locally

You don't need Kubernetes to run this — Docker Compose brings up the whole stack:

```bash
# Start everything
docker compose up --build -d

# Pull the Ollama models (only needed once)
docker compose --profile init run --rm ollama-init

# Grab a token (default creds are admin/admin — change these for anything real)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -d "username=admin&password=admin" | jq -r .access_token)

# Add a document
curl -s -X POST http://localhost:8000/api/v1/ingest \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "KubeRAG keeps the API fast by pushing slow LLM work onto a Kafka queue.", "collection": "demo"}'

# Ask something
JOB=$(curl -s -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query": "How does KubeRAG stay fast?", "collection": "demo"}' | jq -r .job_id)

# Get the answer (re-run until status is "completed")
curl -s http://localhost:8000/api/v1/query/$JOB -H "Authorization: Bearer $TOKEN" | jq .
```

> Heads up: by default Ollama runs on **CPU**, so the first real answer can take a
> while. That's expected — see the notes at the bottom on running it properly on a
> GPU.

## See it work on real data

The toy example above is fine for a smoke test, but [`demo/`](demo/) is the real
thing. It loads the **Stanford Question Answering Dataset (SQuAD v1.1)** — actual
Wikipedia passages with human-written questions and known-correct answers — ingests
the passages, asks the questions, and then **scores the answers against ground
truth**. So it's an actual evaluation, not a scripted happy path.

```bash
python demo/seed.py        # ingest the bundled SQuAD passages
python demo/evaluate.py    # ask the questions, score answers, report latency
python demo/load_test.py --concurrency 200   # fire a burst to show backpressure
```

A real slice of the data is already committed under `demo/data/`, so this works out
of the box — no download needed. Everything in `demo/` is plain Python standard
library, nothing to `pip install`. Full walkthrough in [`demo/README.md`](demo/README.md).

## Running it on Kubernetes

```bash
# Build the two app images (point these at your own registry)
docker build -t your-registry/kuberag-gateway:latest ./gateway
docker build -t your-registry/kuberag-worker:latest ./worker
docker push your-registry/kuberag-gateway:latest
docker push your-registry/kuberag-worker:latest

# Update the image names in k8s/gateway/deployment.yaml and k8s/worker/deployment.yaml,
# then set a real JWT secret:
echo -n "something-actually-secret" | base64    # paste into k8s/secrets.yaml

# Apply the whole stack at once
kubectl apply -k k8s/
kubectl get pods -n kuberag -w
```

To try it on your laptop with Minikube instead:

```bash
minikube start --cpus 6 --memory 12g --driver docker
minikube addons enable metrics-server
eval $(minikube docker-env)          # build straight into minikube, skip the registry
docker build -t kuberag/gateway:latest ./gateway
docker build -t kuberag/worker:latest ./worker
kubectl apply -k k8s/
minikube tunnel                      # exposes the gateway LoadBalancer
```

## API

Everything needs a `Bearer` token except `/health`.

| Method | Path | What it does |
|--------|------|-------------|
| `POST` | `/api/v1/auth/token` | Log in, get a JWT |
| `POST` | `/api/v1/query` | Ask a question → `202` + `job_id` |
| `GET` | `/api/v1/query/{job_id}` | Check on a job / get the answer |
| `POST` | `/api/v1/ingest` | Add a document → `202` + `job_id` |
| `GET` | `/api/v1/health` | Health check (Kafka + Redis) |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/docs` | Swagger UI |

A finished query comes back looking like this:

```json
{
  "job_id": "uuid",
  "status": "completed",
  "cached": false,
  "answer": "The Denver Broncos.",
  "sources": [
    {"id": 1, "content": "...", "metadata": {}, "score": 0.94}
  ]
}
```

## Configuration

Everything is set through environment variables (or a `.env` file locally). The
ones you'll actually touch:

**Gateway**

| Variable | Default | Notes |
|----------|---------|-------|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Broker address |
| `REDIS_URL` | `redis://redis:6379/0` | Cache + job store |
| `SECRET_KEY` | `change-me` | **Change this.** JWT signing key |
| `RATE_LIMIT_REQUESTS` | `100` | Per IP, per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window |
| `CACHE_TTL_SECONDS` | `3600` | How long cached answers live |

**Worker**

| Variable | Default | Notes |
|----------|---------|-------|
| `POSTGRES_DSN` | `postgresql://...` | Where chunks + embeddings live |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | The model server |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `GEN_MODEL` | `llama3` | Generation model |
| `CHUNK_SIZE` | `512` | Words per chunk |
| `CHUNK_OVERLAP` | `64` | Overlap between chunks |

## Where things live

```
gateway/   FastAPI app — auth, rate limiting, cache, Kafka producer
worker/    Kafka consumer + the RAG pipeline (embed → search → generate → store)
k8s/       Kubernetes manifests, wired together with Kustomize
demo/      Real-dataset demo + evaluation (SQuAD)
docker-compose.yml   the whole stack for local dev
init.sql             Postgres schema (pgvector, HNSW index, jobs table)
```

## A few honest notes

- **It's slow on CPU.** Ollama defaults to CPU here, which is fine for a demo but
  not for anything real. The Ollama deployment has commented-out
  `nvidia.com/gpu` requests ready to uncomment for a GPU node pool — that's where
  this actually belongs.
- **Auth is intentionally minimal.** There's a single in-memory user to keep the
  focus on the distributed parts. Swapping in a real user table is a small change in
  `gateway/app/core/auth.py`.
- **The numbers in `demo/README.md` are illustrative.** Real accuracy depends on the
  generation model and how many passages you ingest — run `evaluate.py` yourself and
  you'll get your own.
- **What I'd add next:** distributed tracing wired into something like Tempo or
  Datadog (the `trace_id` already flows through Kafka end to end — it just isn't
  exported yet), and a small React UI so you don't have to poll with `curl`.
```
