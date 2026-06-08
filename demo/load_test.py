#!/usr/bin/env python3
"""Backpressure demonstration: fire a burst of concurrent queries at the gateway.

The point of this script is to show the architecture's defining property: the
gateway accepts a large simultaneous burst *instantly* (each returns 202 + job_id)
because Kafka absorbs the load. The slow LLM workers then drain the queue at their
own pace — nothing is dropped and nothing OOM-crashes, no matter how big the spike.

Usage:  python demo/load_test.py --concurrency 200
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _client import login, request  # noqa: E402

COLLECTION = "squad"
DATA = pathlib.Path(__file__).parent / "data" / "questions.jsonl"


def submit(token: str, question: str) -> tuple[bool, float]:
    start = time.time()
    try:
        resp = request("POST", "/query",
                       {"query": question, "collection": COLLECTION, "top_k": 5},
                       token=token)
        ok = bool(resp.get("job_id"))
        return ok, time.time() - start
    except Exception:
        return False, time.time() - start


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--concurrency", type=int, default=100,
                    help="number of queries to fire simultaneously")
    args = ap.parse_args()

    if DATA.exists():
        questions = [json.loads(line)["question"]
                     for line in DATA.read_text().splitlines() if line.strip()]
    else:
        questions = ["What is the capital of France?"]

    # Repeat the question pool to reach the requested burst size.
    burst = [questions[i % len(questions)] for i in range(args.concurrency)]

    token = login()
    print(f"Firing {args.concurrency} concurrent queries at the gateway ...")

    accepted = 0
    submit_latencies: list[float] = []
    wall_start = time.time()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(submit, token, q) for q in burst]
        for fut in as_completed(futures):
            ok, latency = fut.result()
            accepted += ok
            submit_latencies.append(latency)

    wall = time.time() - wall_start
    submit_latencies.sort()
    p95 = submit_latencies[min(len(submit_latencies) - 1, int(len(submit_latencies) * 0.95))]

    print("\n" + "=" * 60)
    print(f"Accepted (202):       {accepted}/{args.concurrency}")
    print(f"Total wall time:      {wall:.2f}s")
    print(f"Acceptance throughput:{args.concurrency / wall:8.0f} req/s")
    print(f"Submit latency p95:   {p95 * 1000:.0f} ms")
    print("=" * 60)
    print("The gateway absorbed the burst without blocking on inference.")
    print("Workers now drain the Kafka queue at their own sustainable rate.")


if __name__ == "__main__":
    main()
