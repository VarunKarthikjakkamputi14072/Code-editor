#!/usr/bin/env python3
"""Evaluate KubeRAG against the SQuAD questions and report accuracy + latency.

For each question we submit a query, poll for the generated answer, and score it
with SQuAD-style answer matching (normalized substring containment against any
gold span). Reports per-question results plus aggregate accuracy and p50/p95
end-to-end latency.

This is a real retrieval-augmented-generation eval on a real dataset - not a
canned demo. Run `seed.py` first so the corpus is populated.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import string
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _client import login, poll, request  # noqa: E402

COLLECTION = "squad"
DATA = pathlib.Path(__file__).parent / "data" / "questions.jsonl"

_ARTICLES = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)


def normalize(text: str) -> str:
    """SQuAD normalization: lowercase, drop punctuation/articles, collapse spaces."""
    text = text.lower()
    text = "".join(ch for ch in text if ch not in string.punctuation)
    text = _ARTICLES.sub(" ", text)
    return " ".join(text.split())


def is_correct(answer: str, golds: list[str]) -> bool:
    norm_answer = normalize(answer)
    return any(normalize(g) in norm_answer for g in golds if g.strip())


def main() -> None:
    if not DATA.exists():
        sys.exit("questions.jsonl not found - run: python demo/prepare_dataset.py")

    questions = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    print(f"Evaluating {len(questions)} questions against collection '{COLLECTION}'\n")

    token = login()
    correct = 0
    latencies: list[float] = []

    for i, q in enumerate(questions, 1):
        start = time.time()
        resp = request("POST", "/query",
                       {"query": q["question"], "collection": COLLECTION, "top_k": 5},
                       token=token)
        # A cache hit returns the answer inline; otherwise poll the async job.
        if resp.get("status") == "completed" and resp.get("answer"):
            state = resp
        else:
            state = poll(token, resp["job_id"])
        elapsed = time.time() - start
        latencies.append(elapsed)

        answer = (state.get("answer") or "").strip()
        ok = is_correct(answer, q["answers"])
        correct += ok

        mark = "PASS" if ok else "FAIL"
        print(f"[{i:>2}/{len(questions)}] {mark}  ({elapsed:5.1f}s)  {q['question']}")
        print(f"         gold:  {q['answers']}")
        print(f"         model: {answer[:160]}")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]

    print("\n" + "=" * 60)
    print(f"Accuracy:    {correct}/{len(questions)}  ({100 * correct / len(questions):.1f}%)")
    print(f"Latency p50: {p50:.1f}s   p95: {p95:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
