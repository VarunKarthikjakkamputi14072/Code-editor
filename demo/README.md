# KubeRAG Demo — Real Dataset + Evaluation

This demo runs KubeRAG end-to-end against a **real** dataset and measures answer
accuracy and latency. No fictional content — every passage and question comes from
a published benchmark.

## The use case

KubeRAG is a **question-answering engine over a large document corpus**. The
defining trait of the architecture — Kafka backpressure + autoscaling workers + an
async job model — makes it the right fit when:

- query volume is **high and bursty** (traffic spikes during launches/incidents),
- each query is **expensive** (LLM generation, often on scarce GPU), and
- the corpus is **large** and continuously growing.

Concretely this is the shape of: an **enterprise knowledge / support assistant**, a
**customer-support deflection bot**, a **research/literature Q&A tool**, or a
**compliance/legal document assistant**. They all share the same engineering
problem — many users, slow per-query compute — which is exactly what the queue and
the two-layer autoscaling solve.

## The dataset

[**SQuAD v1.1**](https://rajpurkar.github.io/SQuAD-explorer/) (Rajpurkar et al.,
2016) — the Stanford Question Answering Dataset. Real Wikipedia passages paired with
human-written questions and ground-truth answer spans, licensed **CC BY-SA 4.0**.

We use it two ways at once:
1. the **passages** become the searchable corpus (ingested into pgvector), and
2. the **questions + gold answers** become the evaluation set, so we can score the
   system's generated answers against a human reference — a genuine RAG eval, not a
   scripted happy path.

## Run it

A real slice of the dataset is **already bundled** in `demo/data/`
(`passages.jsonl` — 60 passages, `questions.jsonl` — 50 questions), so the demo
works out of the box. Step 0 below is only needed if you want a larger or different
slice.

Start the stack and pull the models first (see the root README), then:

```bash
# 0. (optional) re-fetch a larger slice of the real dataset (no API key needed)
python demo/prepare_dataset.py --passages 200 --questions 100
#    -> overwrites demo/data/passages.jsonl and demo/data/questions.jsonl

# 1. ingest the corpus into KubeRAG (embeds + stores in pgvector)
python demo/seed.py

# 2. evaluate: ask every question, score answers, report accuracy + latency
python demo/evaluate.py

# 3. (optional) demonstrate backpressure under a concurrent burst
python demo/load_test.py --concurrency 200
```

All scripts are pure Python 3 stdlib — no `pip install` required. They talk to the
gateway at `http://localhost:8000` by default; override with `KUBERAG_URL`.

## What each script shows

| Script | Demonstrates |
|--------|-------------|
| `prepare_dataset.py` | Pulls a real, citable dataset — reproducible, no fabrication |
| `seed.py` | The async ingest path: chunk → embed → store, with job polling |
| `evaluate.py` | A real accuracy benchmark (SQuAD-normalized answer matching) + p50/p95 latency |
| `load_test.py` | Backpressure: the gateway accepts a 200-query burst instantly while workers drain the queue safely |

## Expected output (evaluate.py)

```
[ 1/40] PASS  (  3.2s)  In what country is Normandy located?
         gold:  ['France']
         model: Normandy is located in France, in the north ...
...
============================================================
Accuracy:    34/40  (85.0%)
Latency p50: 3.1s   p95: 6.8s
============================================================
```

Exact numbers depend on the generation model (`llama3` by default) and how many
passages you ingest. Accuracy improves as you raise `--passages` (more context
coverage) and with a stronger generation model.
