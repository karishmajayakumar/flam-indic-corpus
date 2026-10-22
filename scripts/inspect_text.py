#!/usr/bin/env python3
"""Run reader -> normalize -> langid over data/raw and inspect results.

Prints per-source/per-language counts, parse errors, and a deterministic
reservoir sample of 10 docs per source for manual checking.
Usage: python3 scripts/inspect_text.py [raw_dir]
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reader import iter_documents
from src.normalize import normalize_text
from src.langid import classify_with_scores

raw_dir = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
rng = random.Random(42)

counts = Counter()
errors = Counter()
seen = Counter()
samples = {}  # source -> reservoir of 10

for doc in iter_documents(raw_dir):
    src = doc["source"]
    if doc.get("parse_error"):
        errors[src] += 1
        continue
    text = normalize_text(doc["raw_text"])
    info = classify_with_scores(text)
    counts[(src, info["lang"])] += 1
    seen[src] += 1

    # reservoir sampling (10 per source)
    bucket = samples.setdefault(src, [])
    n = seen[src]
    item = (info["lang"], info["dev_ratio"], info["hindi_word_ratio"], text[:160])
    if len(bucket) < 10:
        bucket.append(item)
    else:
        j = rng.randint(0, n - 1)
        if j < 10:
            bucket[j] = item

print("=== COUNTS (source, lang) ===")
for (src, lang), c in sorted(counts.items()):
    print(f"{src:25s} {lang:8s} {c}")
print("\n=== TOTALS ===")
for src in sorted(seen):
    print(f"{src:25s} docs={seen[src]} parse_errors={errors[src]}")

print("\n=== SAMPLES (10 per source, for manual check) ===")
for src in sorted(samples):
    print(f"\n--- {src} ---")
    for lang, dev, hin, text in samples[src]:
        print(f"[{lang:8s} dev={dev:.2f} hinw={hin:.2f}] {text!r}")
