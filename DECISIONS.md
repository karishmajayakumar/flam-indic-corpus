# DECISIONS.md — Clean Indic Training Corpus

_All numbers below are from `out/manifest.json` (run of 2026-10-22) unless stated otherwise._

## 1. Sources (download date 2026-10-22 for all; raw saved exactly as downloaded)

| Source | URL | License | Downloaded | Size |
|---|---|---|---|---|
| Wikimedia Wikipedia `20231101.hi` | huggingface.co/datasets/wikimedia/wikipedia | CC BY-SA 3.0 (HF card) | 2,500 articles → 88,526 paragraphs | 33.21 MB |
| FineWeb-2 `hin_Deva` | huggingface.co/datasets/HuggingFaceFW/fineweb-2 | ODC-By 1.0 (+ Common Crawl ToU) | 6,000 docs (streaming; the full folder is 34.3 GB) | 43.01 MB |
| PHINC (veezbo mirror; orig. Zenodo 3605597) | huggingface.co/datasets/veezbo/phinc | CC BY 4.0 (verified on Zenodo; HF card does not state it) | 3,000 rows, field `Sentence` | 0.63 MB |

COMI-LINGUA (CC BY 4.0) was tried as a Hinglish alternative and rejected: its `Sentences` column is mostly Devanagari (`hi` under our rules), not Latin-script Hinglish. A document = one paragraph for Wikipedia articles (split on `\n` in the pipeline, never at download); one row = one document for FineWeb-2/PHINC.

## 2. Funnel (97,526 input documents)

| Stage | Out | Dropped | Per-language kept at the end |
|---|---|---|---|
| Input | 97,526 | — | |
| langid (drop `en`/`other`) | 92,154 | 5,372 (`en` 3,310, `other` 2,062) | |
| quality | 80,581 | 11,573 (too_short 11,459; numeric/symbol 77; markup 24; URLs 12; garbled 1) | |
| eval holdout | 195 eval items | 200 candidates, 5 removed as eval self-duplicates | eval: `hi` 145, `hi-Latn` 50 |
| contamination | −2,849 train | leaks of eval (Sec. 5) | |
| exact dedup | −6,309 | SHA256 of normalised lowercase text | |
| near dedup | −119 | Jaccard ≥ 0.8 (Sec. 3) | |
| **Kept** | **71,104** | | **`hi` 68,965 · `hi-Latn` 2,139** |

PII redacted in kept+eval text: 94 emails, 81 phones, 9 Aadhaars, 0 PAN (none present in the data; PAN is unit-tested).

## 3. Near-duplicates

Method: word 5-gram shingles → MinHash (64 perms, seed 42) → LSH (16 bands × 4 rows) → candidates confirmed with **true** Jaccard. Survivor = first document in sorted file/record order; others point to it in `dup_of`. Texts under 5 words: exact only.

Threshold chosen from data: 1,380 candidate pairs (0.30 < J < 1.0) were found by full LSH scan; 30 spread across the range were labelled by hand (24 not-dup, 6 dup; `tuning/pairs.jsonl`). Non-duplicates reach J=0.667; clear duplicates start at 0.833. **Threshold kept at 0.80** (favours precision: merging two different districts would delete a real fact; keeping two copies of a one-line event costs almost nothing). Three pairs near the threshold:

- J=0.667, **not-dup**: "रायगढा भारत के उड़ीसा प्रान्त का एक जिला है।" vs "गजपति भारत के उड़ीसा प्रान्त का एक जिला है।" — same district template, different districts.
- J=0.700, **dup (missed at 0.8, accepted)**: "1 जनवरी - उत्तर प्रदेश में मूल्य वर्द्धित कर 'वैट' लागू किया गया।" vs "2008 - उत्तर प्रदेश में मूल्य वर्द्धित कर 'वैट' लागू किया गया।" — same event line, only the year prefix differs.
- J=0.833, **dup**: "(2) गौरवमय अतीत के इतिहास और भारतीय संस्कृति की महत्ता" vs the same without "(2)".

Known limit: Jaccard is volatile on very short texts — one true duplicate pair ("| 101 || श्री भट्ट …" with only spacing changed) scored 0.389 and survives. Exact dedup still catches fully identical short texts.

## 4. Filters — three wrongly dropped documents (full records in `tuning/wrong_drops.json`)

1. `<poem>असतो मा सद्गमय।` (Wikipedia, dropped: markup) — a real poem verse; the text is so short that one `<poem>` tag pushes the tag ratio over 0.20.
2. `ॐ शान्तिः शान्तिः शान्तिः ॥</poem>` (Wikipedia, dropped: markup) — closing shanti-mantra verse, same cause.
3. A long FineWeb-2 article on community radio (dropped: too_many_urls) — the >2 URLs are scraped page chrome, not the article body.

Everything else sampled was dropped correctly: 11,459 of 11,573 quality drops are sub-10-character headings/single words (e.g. "सन्दर्भ", "भूगोल"). The poem losses are the deliberate cost of a tag-ratio rule; at scale I would whitelist `<poem>` before measuring.

## 5. Contamination (eval = 195 items, held out after cleaning/PII but **before** dedup)

Methods, in order: (1) exact `raw_hash`, (2) hash of normalised lowercase text, (3) MinHash near-match at the dedup threshold, (4) cross-script consonant-skeleton check (Devanagari ↔ Latin, e.g. भारत/`bharat` → `brt`), gated to different-script pairs only, overlap ≥0.8 **and** skeleton Jaccard ≥0.5 **and** ≥5 shared tokens.

Result: **28 of 195 eval items affected; 2,849 training documents removed** (almost all exact/normalised copies of repeated Wikipedia boilerplate paragraphs). No cross-script leaks survived the gates.

One candidate match rejected: eval "lol, ye kya hai?!" vs a FineWeb-2 film review of *Ek Tha Tiger* (2012). Skeleton overlap was 1.0, but the eval item has only 2 skeleton tokens (`ll`, `ky`), both of which merely occur somewhere in a 300-word review — shared-token count 2 < 5 and skeleton Jaccard ≈ 0.01. Subset match, not a copy. (An earlier version of the cross-script check without these gates dropped 7,773 documents this way; the gates and two regression tests exist because of that run.)

## 6. Reproducibility

`./download.sh` (the only network step; Wikipedia config is a dated dump, FineWeb-2/PHINC are streamed in dataset order and capped) then `./run.sh data/raw out` (offline, stdlib-only pipeline; `datasets` is needed only to download). Before trusting a rebuild, compare the three raw files against the SHA256 hashes in `out/manifest.json` — if they differ, the output will differ. The pipeline is deterministic: sorted file iteration, IDs = `sha256(source, record_index, para_index)`, seed 42, gzip written with `mtime=0`, no timestamps or absolute paths in any output (download dates live only in `SOURCES.md`). Verified: two consecutive runs produce byte-identical `out/` trees (`diff -r`). Restart after a kill = restart from scratch: output is built in `out.tmp/` and renamed into place only when complete, so a partial run can never corrupt or duplicate rows. Python 3.12; `datasets==4.8.4` for downloads.

## 7. Scale (2 TB on object storage)

The first thing that breaks is Pass 2 memory: the deduper keeps the shingle set of every kept document plus all LSH band buckets — fine at 80k documents, impossible at ~10⁹. The fix is to shard by hash prefix of the comparison key (e.g. 256 shards, each processed independently and merged, since duplicates almost always share a prefix bucket via LSH bands), and to keep signatures on disk (e.g. as Parquet) instead of in RAM. Pass 1 already streams, but writing one gzip stage1 file becomes the next bottleneck — partition stage1 by shard from the start and run Pass 2 as a map/reduce over shards.

## 8. Wrap-up

- **Didn't get to, in priority order:** (1) whitelist `<poem>`/strip boilerplate before the URL count (would recover the Sec. 4 losses); (2) a real Devanagari transliterator for the cross-script check — the consonant skeleton has low recall on short Hinglish; (3) refill eval back to exactly 200 after self-dedup (195 now); (4) boilerplate-line filter for FineWeb navigation text that survives inside kept documents.
- **Time spent:** ~2 hours of assisted work in this session (data ~25 min, text modules ~20 min, pipeline + contamination fixes ~45 min, tuning/verification/write-up ~30 min) against the 4-hour budget.
