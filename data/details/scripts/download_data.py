#!/usr/bin/env python3
"""
Download raw data exactly as downloaded (no splitting / filtering).

Sources:
  1. wikimedia/wikipedia  config 20231101.hi   -> data/raw/wikipedia_hi.jsonl       (2500 articles, streaming)
  2. HuggingFaceFW/fineweb-2 config hin_Deva   -> data/raw/fineweb2_hin_Deva.jsonl  (6000 docs, streaming)
  3. veezbo/phinc                               -> data/raw/phinc_hinglish.jsonl     (4000 rows)

Usage:
  python3 scripts/download_data.py [all|wikipedia|fineweb|phinc]
"""
import json
import sys
from pathlib import Path

from datasets import load_dataset

ROOT = Path(__file__).resolve().parents[3]  # flam/ (scripts is under data/details/scripts/)
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

LIMITS = {"wikipedia": 2500, "fineweb": 6000, "phinc": 4000}


def write_jsonl(path: Path, rows, limit: int, source_name: str) -> int:
    tmp = path.with_suffix(".jsonl.tmp")
    n = 0
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            if n >= limit:
                break
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
            if n % 500 == 0:
                print(f"  {source_name}: {n}/{limit}", flush=True)
    tmp.replace(path)
    print(f"DONE {source_name}: {n} rows -> {path} ({path.stat().st_size/1e6:.2f} MB)")
    return n


def download_wikipedia() -> int:
    print("Downloading wikimedia/wikipedia 20231101.hi (streaming, 2500 articles)...")
    ds = load_dataset("wikimedia/wikipedia", "20231101.hi", split="train", streaming=True)
    rows = (
        {"id": r["id"], "url": r["url"], "title": r["title"], "text": r["text"], "source": "wikipedia_hi"}
        for r in ds
    )
    return write_jsonl(RAW / "wikipedia_hi.jsonl", rows, LIMITS["wikipedia"], "wikipedia")


def download_fineweb() -> int:
    print("Downloading HuggingFaceFW/fineweb-2 hin_Deva (streaming, 6000 docs)...")
    ds = load_dataset("HuggingFaceFW/fineweb-2", "hin_Deva", split="train", streaming=True)
    def gen():
        for r in ds:
            # Keep raw fields as downloaded; text is the document.
            yield {
                "id": r.get("id"),
                "url": r.get("url"),
                "text": r.get("text"),
                "dump": r.get("dump"),
                "language": r.get("language"),
                "language_score": r.get("language_score"),
                "source": "fineweb2_hin_Deva",
            }
    return write_jsonl(RAW / "fineweb2_hin_Deva.jsonl", gen(), LIMITS["fineweb"], "fineweb")


def download_phinc() -> int:
    print("Downloading veezbo/phinc (4000 rows)...")
    try:
        ds = load_dataset("veezbo/phinc", split="train", streaming=True)
    except Exception as e:
        print(f"  streaming failed ({e}), falling back to full download (only 13,738 rows)")
        ds = load_dataset("veezbo/phinc", split="train")
    rows = (
        {"Sentence": r.get("Sentence"), "English_Translation": r.get("English_Translation"), "source": "phinc"}
        for r in ds
    )
    return write_jsonl(RAW / "phinc_hinglish.jsonl", rows, LIMITS["phinc"], "phinc")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    total = 0
    if which in ("all", "wikipedia"):
        total += download_wikipedia()
    if which in ("all", "fineweb"):
        total += download_fineweb()
    if which in ("all", "phinc"):
        total += download_phinc()
    print(f"\nTOTAL downloaded rows (this run): {total}")
