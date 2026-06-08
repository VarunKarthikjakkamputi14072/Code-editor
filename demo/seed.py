#!/usr/bin/env python3
"""Ingest the SQuAD passages into KubeRAG via the gateway API.

Reads demo/data/passages.jsonl (produced by prepare_dataset.py), submits each
passage to POST /ingest, then waits for every ingestion job to complete.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _client import login, poll, request  # noqa: E402

COLLECTION = "squad"
DATA = pathlib.Path(__file__).parent / "data" / "passages.jsonl"


def main() -> None:
    if not DATA.exists():
        sys.exit("passages.jsonl not found — run: python demo/prepare_dataset.py")

    passages = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(passages)} passages from {DATA.name}")

    token = login()
    job_ids: list[str] = []

    for p in passages:
        resp = request("POST", "/ingest", {
            "text": p["text"],
            "metadata": {"id": p["id"], "title": p["title"], "source": "squad-v1.1"},
            "collection": COLLECTION,
        }, token=token)
        job_ids.append(resp["job_id"])

    print(f"Submitted {len(job_ids)} ingestion jobs; waiting for completion ...")

    done = failed = 0
    for jid in job_ids:
        state = poll(token, jid)
        if state.get("status") == "completed":
            done += 1
        else:
            failed += 1
            print(f"  ingest job {jid} -> {state.get('status')}")

    print(f"\nIngestion complete: {done} succeeded, {failed} failed.")
    print(f"Corpus is queryable under collection '{COLLECTION}'.")


if __name__ == "__main__":
    main()
