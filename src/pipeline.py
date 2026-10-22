"""
Two-pass pipeline (plan.md Sec. 3).

Pass 1 (streaming, one doc at a time):
  parse -> normalize -> langid -> quality -> PII -> tmp stage1.jsonl.gz
Pass 2 (also streams stage1 line by line; only hashes, MinHash signatures
        and the 200 eval items live in memory):
  Scan A: eval holdout (bounded heap: 150 smallest hi IDs + 50 smallest hi-Latn)
  Scan B: contamination vs eval -> exact dedup -> near dedup -> kept

Every input document gets exactly one ledger row. Output is written to
<out>.tmp/ and renamed into place only when complete: restart-from-scratch
(all-or-nothing), NOT checkpointing. Same input -> byte-identical output
(gzip mtime=0, sorted iteration, no timestamps/absolute paths in outputs).

Usage: python3 -m src.pipeline <raw_dir> <out_dir>
"""
import csv
import gzip
import hashlib
import heapq
import io
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import CONFIG
from src.reader import iter_documents
from src.normalize import normalize_text
from src.langid import classify_with_scores
from src.quality import assess
from src.pii import redact
from src.dedup import Deduper, make_shingles, make_signature, jaccard, band_keys, skeleton_tokens

EVAL_PURPOSE = "Measures LM quality on clean contemporary Hindi/Hinglish prose."
KEEP_LANGS = ("hi", "hi-Latn")


def doc_id(source: str, record_index: int, para_index: int) -> str:
    h = hashlib.sha256(f"{source}\x00{record_index}\x00{para_index}".encode("utf-8"))
    return h.hexdigest()[:16]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_writer(path: Path):
    raw = path.open("wb")
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
    return io.TextIOWrapper(gz, encoding="utf-8", newline="\n")


def gzip_reader(path: Path):
    return gzip.open(path, "rt", encoding="utf-8", newline="")


class Ledger:
    def __init__(self):
        self.rows = []

    def add(self, doc, status, stage, reason="", dup_of="", lang=""):
        self.rows.append({
            "id": doc["id"], "status": status, "stage": stage,
            "reason": reason, "dup_of": dup_of,
            "_sort": (doc.get("source", ""), doc.get("record_index", 0), doc.get("para_index", 0)),
            "_lang": lang,
        })

    def write(self, path: Path):
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "status", "stage", "reason", "dup_of"])
            for r in sorted(self.rows, key=lambda r: r["_sort"]):
                w.writerow([r["id"], r["status"], r["stage"], r["reason"], r["dup_of"]])

    def counts(self):
        by_stage = Counter(r["stage"] for r in self.rows)
        by_stage_lang = Counter((r["stage"], r["_lang"] or "unknown") for r in self.rows)
        return by_stage, by_stage_lang


def pass1(raw_dir: Path, stage1_path: Path, ledger: Ledger, stats: dict):
    pii_totals = Counter()
    writer = gzip_writer(stage1_path)
    try:
        for doc in iter_documents(raw_dir):
            base = {
                "id": doc_id(doc["source"], doc["record_index"], doc["para_index"]),
                "source": doc["source"],
                "record_index": doc["record_index"],
                "para_index": doc["para_index"],
            }
            if doc.get("parse_error"):
                stats["input_docs"] += 1
                ledger.add(base, "dropped", "parse", doc.get("reason", "parse error"))
                continue
            stats["input_docs"] += 1
            raw_text = doc["raw_text"]
            raw_hash = sha256_text(raw_text)
            normalized = normalize_text(raw_text)
            lang = classify_with_scores(normalized)["lang"]
            if lang not in KEEP_LANGS:
                ledger.add(base, "dropped", "langid", f"lang={lang}", lang=lang)
                continue
            keep, reason, cleaned = assess(raw_text, normalized)
            if not keep:
                ledger.add(base, "dropped", "quality", reason, lang=lang)
                continue
            redacted, pii_counts = redact(cleaned)
            pii_totals.update(pii_counts)
            row = {**base, "text": redacted, "lang": lang, "raw_hash": raw_hash}
            writer.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats["stage1_docs"] += 1
    finally:
        writer.close()
    stats["pii_totals"] = dict(sorted(pii_totals.items()))


def select_eval(stage1_path: Path, ledger: Ledger, stats: dict):
    """Scan A: smallest IDs per language via bounded heap. Returns (eval_rows, eval_candidate_ids)."""
    limits = {"hi": CONFIG["eval_hi"], "hi-Latn": CONFIG["eval_hi_latn"]}
    heaps = {"hi": [], "hi-Latn": []}
    counter = 0
    with gzip_reader(stage1_path) as f:
        for line in f:
            row = json.loads(line)
            lang = row["lang"]
            if lang not in limits:
                continue
            heap = heaps[lang]
            entry = (-int(row["id"], 16), counter, row)  # min-heap on -id: top = largest id
            counter += 1
            if len(heap) < limits[lang]:
                heapq.heappush(heap, entry)
            elif entry[0] > heap[0][0]:
                heapq.heapreplace(heap, entry)

    candidates = []
    for lang in ("hi", "hi-Latn"):
        candidates.extend(e[2] for e in heaps[lang])
    candidates.sort(key=lambda r: r["id"])

    # Dedup the eval set among themselves (sorted order: first wins).
    deduper = Deduper()
    eval_rows, candidate_ids = [], set()
    for row in candidates:
        candidate_ids.add(row["id"])
        shingles = make_shingles(row["text"])
        is_dup, dup_of, method, _ = deduper.add(
            row["id"], sha256_text(row["text"].lower()), shingles, make_signature(shingles))
        if is_dup:
            ledger.add(row, "dropped", "eval_dedup", f"duplicate of eval {dup_of} ({method})",
                       dup_of=dup_of, lang=row["lang"])
        else:
            eval_rows.append(row)
            ledger.add(row, "dropped", "eval_holdout", "held out for eval", lang=row["lang"])
    stats["eval_candidates"] = len(candidates)
    stats["eval_size"] = len(eval_rows)
    return eval_rows, candidate_ids


def _dominant_script(text: str) -> str:
    dev = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    lat = sum(1 for c in text if ("a" <= c <= "z") or ("A" <= c <= "Z"))
    if dev == lat == 0:
        return "other"
    return "dev" if dev >= lat else "lat"


class EvalIndex:
    def __init__(self, eval_rows):
        self.rows = eval_rows
        self.by_raw_hash = {}
        self.by_norm_hash = {}
        self.bands = defaultdict(list)
        self.shingles = {}
        self.skeletons = {}
        self.scripts = {}
        self.skeleton_postings = defaultdict(set)
        for row in eval_rows:
            self.by_raw_hash.setdefault(row["raw_hash"], row["id"])
            self.by_norm_hash.setdefault(sha256_text(row["text"].lower()), row["id"])
            shingles = make_shingles(row["text"])
            self.shingles[row["id"]] = shingles
            sig = make_signature(shingles)
            if sig:
                for key in band_keys(sig):
                    self.bands[key].append(row["id"])
            skel = skeleton_tokens(row["text"])
            self.skeletons[row["id"]] = skel
            self.scripts[row["id"]] = _dominant_script(row["text"])
            for tok in skel:
                self.skeleton_postings[tok].add(row["id"])
        self._by_id = {r["id"]: r for r in eval_rows}

    def check(self, row, shingles, signature, skel_tokens):
        """Return (eval_id, method, score) for a leak, else (None, best_rejected)."""
        if row["raw_hash"] in self.by_raw_hash:
            return self.by_raw_hash[row["raw_hash"]], "exact", 1.0, None
        norm_hash = sha256_text(row["text"].lower())
        if norm_hash in self.by_norm_hash:
            return self.by_norm_hash[norm_hash], "normalized", 1.0, None

        best_rejected = None
        if shingles and signature:
            cand = set()
            for key in band_keys(signature):
                cand.update(self.bands.get(key, ()))
            best_id, best_j = None, 0.0
            for eid in cand:
                j = jaccard(shingles, self.shingles[eid])
                if j > best_j:
                    best_id, best_j = eid, j
            if best_id is not None:
                if best_j >= CONFIG["near_dup_jaccard"]:
                    return best_id, "near", best_j, None
                if best_j >= 0.5:
                    best_rejected = {"eval_id": best_id, "train_id": row["id"],
                                     "method": "near", "score": round(best_j, 3)}

        # Cross-script ONLY: a Devanagari eval item appearing in Latin script
        # in train (or vice versa). Same-script pairs are already covered by
        # exact/normalized/near above - applying the loose skeleton overlap
        # there drops generic paragraphs that merely share common words.
        train_script = _dominant_script(row["text"])
        if skel_tokens and train_script in ("dev", "lat"):
            shared = Counter()
            for tok in skel_tokens:
                for eid in self.skeleton_postings.get(tok, ()):
                    if self.scripts.get(eid) not in ("dev", "lat"):
                        continue
                    if self.scripts[eid] == train_script:
                        continue  # same script: not a cross-script candidate
                    shared[eid] += 1
            for eid, n_shared in shared.items():
                eval_skel = self.skeletons[eid]
                if not eval_skel:
                    continue
                overlap = n_shared / min(len(skel_tokens), len(eval_skel))
                skel_jaccard = n_shared / (len(skel_tokens) + len(eval_skel) - n_shared)
                if (overlap >= CONFIG["cross_script_min_overlap"]
                        and skel_jaccard >= CONFIG["cross_script_min_jaccard"]
                        and n_shared >= CONFIG["cross_script_min_shared"]):
                    return eid, "cross_script", round(overlap, 3), best_rejected
                if overlap >= 0.5 and (best_rejected is None or overlap > best_rejected.get("score", 0)):
                    best_rejected = {"eval_id": eid, "train_id": row["id"],
                                     "method": "cross_script", "score": round(overlap, 3)}
        return None, None, 0.0, best_rejected


def pass2(stage1_path: Path, out_tmp: Path, ledger: Ledger, stats: dict,
          eval_rows, eval_candidate_ids):
    index = EvalIndex(eval_rows)
    deduper = Deduper()
    contamination = {}
    best_rejected = None
    kept = 0

    (out_tmp / "clean").mkdir(parents=True, exist_ok=True)
    writer = gzip_writer(out_tmp / "clean" / "corpus.jsonl.gz")
    try:
        with gzip_reader(stage1_path) as f:
            for line in f:
                row = json.loads(line)
                if row["id"] in eval_candidate_ids:
                    continue
                shingles = make_shingles(row["text"])
                signature = make_signature(shingles)
                skel = skeleton_tokens(row["text"])

                eval_id, method, score, rejected = index.check(row, shingles, signature, skel)
                if rejected and (best_rejected is None or rejected["score"] > best_rejected["score"]):
                    best_rejected = rejected
                if eval_id is not None:
                    entry = contamination.setdefault(eval_id, {"train_ids": [], "methods": []})
                    entry["train_ids"].append(row["id"])
                    if method not in entry["methods"]:
                        entry["methods"].append(method)
                    ledger.add(row, "dropped", "contamination",
                               f"leaks eval via {method} (score={score})",
                               dup_of=eval_id, lang=row["lang"])
                    continue

                is_dup, dup_of, dmethod, _ = deduper.add(
                    row["id"], sha256_text(row["text"].lower()), shingles, signature)
                if is_dup:
                    stage = "exact_dedup" if dmethod == "exact" else "near_dedup"
                    ledger.add(row, "dropped", stage, f"duplicate via {dmethod}",
                               dup_of=dup_of, lang=row["lang"])
                    continue

                writer.write(json.dumps(
                    {"id": row["id"], "text": row["text"], "lang": row["lang"],
                     "source": row["source"]}, ensure_ascii=False) + "\n")
                ledger.add(row, "kept", "kept", "", lang=row["lang"])
                kept += 1
    finally:
        writer.close()

    stats["kept"] = kept
    stats["contamination_affected_eval"] = len(contamination)
    stats["contamination_rejected_example"] = best_rejected

    with (out_tmp / "eval.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in sorted(eval_rows, key=lambda r: r["id"]):
            f.write(json.dumps({"id": row["id"], "text": row["text"], "lang": row["lang"],
                                "source": row["source"], "purpose": EVAL_PURPOSE},
                               ensure_ascii=False) + "\n")

    with (out_tmp / "contamination.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for eval_id in sorted(contamination):
            entry = contamination[eval_id]
            method = entry["methods"][0] if len(entry["methods"]) == 1 else entry["methods"]
            f.write(json.dumps({"eval_id": eval_id, "train_ids": sorted(entry["train_ids"]),
                                "method": method}, ensure_ascii=False) + "\n")
    return contamination


def build_manifest(raw_dir: Path, ledger: Ledger, stats: dict):
    by_stage, by_stage_lang = ledger.counts()
    input_files = []
    for p in sorted(raw_dir.iterdir()):
        if p.is_file():
            input_files.append({"name": p.name, "sha256": sha256_file(p),
                                "bytes": p.stat().st_size})
    return {
        "sources": sorted({f["name"].rsplit(".", 1)[0] for f in input_files}),
        "input_files": input_files,
        "thresholds": CONFIG,
        "eval_purpose": EVAL_PURPOSE,
        "counts": {
            "input_docs": stats.get("input_docs", 0),
            "stage1_docs": stats.get("stage1_docs", 0),
            "kept": stats.get("kept", 0),
            "dropped": stats.get("input_docs", 0) - stats.get("kept", 0),
            "eval_candidates": stats.get("eval_candidates", 0),
            "eval_size": stats.get("eval_size", 0),
            "contamination_affected_eval": stats.get("contamination_affected_eval", 0),
            "by_stage": dict(sorted(by_stage.items())),
            "by_stage_lang": {f"{s}|{l}": c for (s, l), c in sorted(by_stage_lang.items())},
        },
        "pii_totals": stats.get("pii_totals", {}),
        "contamination_rejected_example": stats.get("contamination_rejected_example"),
    }


def run(raw_dir: Path, out_dir: Path):
    tmp_dir = out_dir.with_name(out_dir.name + ".tmp")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    stage1_path = tmp_dir / "_stage1.jsonl.gz"

    ledger = Ledger()
    stats = {"input_docs": 0, "stage1_docs": 0}
    try:
        pass1(raw_dir, stage1_path, ledger, stats)
        print(f"pass1: {stats['input_docs']} input docs -> {stats['stage1_docs']} stage1 docs", flush=True)
        eval_rows, eval_candidate_ids = select_eval(stage1_path, ledger, stats)
        print(f"eval: {stats['eval_size']} items held out", flush=True)
        pass2(stage1_path, tmp_dir, ledger, stats, eval_rows, eval_candidate_ids)
        print(f"pass2: kept {stats['kept']}, contamination affected eval: "
              f"{stats['contamination_affected_eval']}", flush=True)
        ledger.write(tmp_dir / "ledger.csv")
        manifest = build_manifest(raw_dir, ledger, stats)
        with (tmp_dir / "manifest.json").open("w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        stage1_path.unlink()
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Atomic-ish publish: swap tmp into place (restart-from-scratch semantics).
    if out_dir.exists():
        backup = out_dir.with_name(out_dir.name + ".old")
        if backup.exists():
            shutil.rmtree(backup)
        out_dir.rename(backup)
        tmp_dir.rename(out_dir)
        shutil.rmtree(backup)
    else:
        tmp_dir.rename(out_dir)
    print(f"done -> {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python3 -m src.pipeline <raw_dir> <out_dir>", file=sys.stderr)
        raise SystemExit(2)
    run(Path(sys.argv[1]), Path(sys.argv[2]))
