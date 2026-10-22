#!/usr/bin/env python3
"""Sample near-duplicate candidate pairs + quality drops for threshold tuning.

Full scan: re-runs Pass-1 logic streaming, computes shingle sets + MinHash
signatures for every stage1 doc, builds LSH band buckets, and evaluates
candidate pairs (star-pairing buckets >20 docs to avoid explosion).
Writes pairs spread across the Jaccard range found, plus quality drops.

Outputs: tuning/pairs.jsonl, tuning/quality_drops.jsonl
Usage: python3 scripts/sample_pairs.py [raw_dir]
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reader import iter_documents
from src.normalize import normalize_text
from src.langid import classify_with_scores
from src.quality import assess
from src.pii import redact
from src.pipeline import doc_id
from src.dedup import make_shingles, make_signature, band_keys, jaccard

raw_dir = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
out_dir = Path("tuning")
out_dir.mkdir(exist_ok=True)
rng = random.Random(42)

docs = []               # all stage1 docs (id, source, text[:300], shingles)
quality_drops = []
drop_count = 0

for doc in iter_documents(raw_dir):
    if doc.get("parse_error"):
        continue
    raw = doc["raw_text"]
    norm = normalize_text(raw)
    lang = classify_with_scores(norm)["lang"]
    if lang not in ("hi", "hi-Latn"):
        continue
    keep, reason, cleaned = assess(raw, norm)
    did = doc_id(doc["source"], doc["record_index"], doc["para_index"])
    if not keep:
        drop_count += 1
        item = {"id": did, "source": doc["source"], "reason": reason, "text": cleaned[:300]}
        if len(quality_drops) < 30:
            quality_drops.append(item)
        else:
            j = rng.randint(0, drop_count - 1)
            if j < 30:
                quality_drops[j] = item
        continue
    text, _ = redact(cleaned)
    docs.append({"id": did, "source": doc["source"], "lang": lang,
                 "text": text, "shingles": make_shingles(text)})

print(f"stage1 docs: {len(docs)}, quality drops seen: {drop_count}")

buckets = defaultdict(list)
for idx, d in enumerate(docs):
    sig = make_signature(d["shingles"])
    if sig:
        for key in band_keys(sig):
            buckets[key].append(idx)

pair_jaccard = {}
for idxs in buckets.values():
    if len(idxs) < 2:
        continue
    if len(idxs) > 20:  # star pairing for huge (mostly exact-duplicate) buckets
        pairs_to_check = [(idxs[0], other) for other in idxs[1:]]
    else:
        pairs_to_check = [(idxs[a], idxs[b]) for a in range(len(idxs)) for b in range(a + 1, len(idxs))]
    for i, j in pairs_to_check:
        key = (min(i, j), max(i, j))
        if key in pair_jaccard:
            continue
        jac = jaccard(docs[i]["shingles"], docs[j]["shingles"])
        if 0.3 < jac < 1.0:
            pair_jaccard[key] = jac

ranked = sorted(pair_jaccard.items(), key=lambda kv: kv[1])
print(f"candidate pairs (0.3<j<1.0): {len(ranked)}")
if ranked:
    print("jaccard range:", round(ranked[0][1], 3), "->", round(ranked[-1][1], 3))
    import collections
    hist = collections.Counter(round(j * 10) / 10 for _, j in ranked)
    print("histogram (floor to 0.1):", dict(sorted(hist.items())))

picked = []
if ranked:
    step = max(1, len(ranked) // 30)
    picked = [ranked[i] for i in range(0, len(ranked), step)][:30]

with (out_dir / "pairs.jsonl").open("w", encoding="utf-8") as f:
    for (i, j), jac in picked:
        a, b = docs[i], docs[j]
        f.write(json.dumps({
            "jaccard": round(jac, 3),
            "a_id": a["id"], "b_id": b["id"], "source": a["source"],
            "a_text": a["text"][:300], "b_text": b["text"][:300],
            "label": "",  # fill by hand: dup / not-dup
        }, ensure_ascii=False) + "\n")

with (out_dir / "quality_drops.jsonl").open("w", encoding="utf-8") as f:
    for item in quality_drops:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"wrote tuning/pairs.jsonl ({len(picked)} pairs) and tuning/quality_drops.jsonl ({len(quality_drops)})")
for (i, j), jac in picked:
    print(f"\nj={jac:.3f} [{docs[i]['source']}]")
    print(" A:", docs[i]["text"][:170])
    print(" B:", docs[j]["text"][:170])
