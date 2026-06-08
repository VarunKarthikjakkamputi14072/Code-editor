#!/usr/bin/env python3
"""Download a slice of the SQuAD v1.1 dev set for the KubeRAG demo.

SQuAD (Rajpurkar et al., 2016 — https://rajpurkar.github.io/SQuAD-explorer/) is
a real reading-comprehension dataset: Wikipedia passages paired with human-written
questions and ground-truth answer spans, licensed CC BY-SA 4.0. We use it as a
realistic, citable corpus *and* as a built-in evaluation set — every ingested
passage comes with questions whose answers we can score against.

Writes two files into demo/data/:
  - passages.jsonl   one Wikipedia passage per line  -> ingested into KubeRAG
  - questions.jsonl  one question + gold answers/line -> used by evaluate.py
"""
from __future__ import annotations

import argparse
import json
import pathlib
import urllib.request

SQUAD_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v1.1.json"
DATA_DIR = pathlib.Path(__file__).parent / "data"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--passages", type=int, default=50,
                    help="number of unique Wikipedia passages to keep")
    ap.add_argument("--questions", type=int, default=40,
                    help="number of evaluation questions to keep")
    ap.add_argument("--url", default=SQUAD_URL, help="source dataset URL")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading SQuAD dev set from {args.url} ...")
    with urllib.request.urlopen(args.url, timeout=60) as resp:
        squad = json.load(resp)

    passages: list[dict] = []
    questions: list[dict] = []
    seen: set[str] = set()

    for article in squad["data"]:
        title = article["title"].replace("_", " ")
        for para in article["paragraphs"]:
            if len(passages) >= args.passages:
                break
            context = para["context"].strip()
            if context in seen:
                continue
            seen.add(context)

            pid = f"squad-{len(passages):04d}"
            passages.append({"id": pid, "title": title, "text": context})

            if len(questions) < args.questions:
                for qa in para["qas"]:
                    golds = sorted({a["text"] for a in qa["answers"]})
                    if not golds:
                        continue
                    questions.append({
                        "id": qa["id"],
                        "passage_id": pid,
                        "title": title,
                        "question": qa["question"],
                        "answers": golds,
                    })
                    if len(questions) >= args.questions:
                        break
        if len(passages) >= args.passages:
            break

    passages_path = DATA_DIR / "passages.jsonl"
    questions_path = DATA_DIR / "questions.jsonl"
    passages_path.write_text("\n".join(json.dumps(p) for p in passages) + "\n")
    questions_path.write_text("\n".join(json.dumps(q) for q in questions) + "\n")

    print(f"Wrote {len(passages):>4} passages  -> {passages_path}")
    print(f"Wrote {len(questions):>4} questions -> {questions_path}")


if __name__ == "__main__":
    main()
