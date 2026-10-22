# PLAN.md: Clean Indic Corpus (4 hours, hard stop)

**One-line pitch:** a two-pass, stdlib-only pipeline. Pass 1 cleans each document as a stream. Pass 2 holds out eval, removes leaks, and dedups. Every input document gets one ledger row, and output is written to a temp folder and then renamed.

## 0. Repo

```
flam/
├── download.sh            # only file that uses the network
├── run.sh                 # ./run.sh <raw_dir> <out_dir>, offline
├── requirements-download.txt   # datasets (download only)
├── src/
│   ├── config.py          # ALL thresholds in one dict (also goes into manifest)
│   ├── reader.py          # file formats, encodings, field sniffing
│   ├── normalize.py
│   ├── langid.py
│   ├── quality.py
│   ├── pii.py
│   ├── dedup.py           # exact + MinHash
│   └── pipeline.py        # pass 1, pass 2, ledger, manifest
├── tests/test_units.py    # normalize, langid, PII, run-twice-and-diff
├── scripts/fill_decisions.py
├── SOURCES.md  DECISIONS.md
└── raw/ out/ (gitignored, except sample)
```

## 1. Timeline (4:00 total, commit after every row)

| Time | Task | Done when |
|---|---|---|
| 0:00-0:15 | Repo, skeleton `run.sh`/`download.sh`, `config.py` | `./run.sh` runs on an empty dir |
| 0:15-0:50 | Download data, fill `SOURCES.md` | >=10k paragraph-docs, >=1,500 Hinglish raw |
| 0:50-1:25 | `reader`, `normalize`, `langid`, tests | Tests pass; 30 docs hand-checked |
| 1:25-2:25 | `quality`, `pii`, `dedup`, `pipeline` | End-to-end run with a ledger |
| 2:25-2:50 | Tune the dedup threshold; review dropped docs | 30 pairs labelled; 3 wrong drops noted |
| 2:50-3:20 | Eval and contamination | `eval.jsonl`, `contamination.jsonl` |
| 3:20-3:45 | `fill_decisions.py`, then `DECISIONS.md` | Numbers come from `manifest.json` |
| 3:45-4:00 | Determinism check, 1,000-row sample, zip | Checklist (Sec. 7) passes |

If you fall behind, cut from Sec. 8 only.

## 2. Data (`download.sh` only; raw saved exactly as downloaded)

1. **Hindi main:** `wikimedia/wikipedia` `20231101.hi`, about 2,500 whole articles (CC BY-SA 4.0). Cap the count: articles become many paragraphs.
2. **Hindi messy:** a web-crawl Hindi source (IndicCorp or OSCAR-style). Check the license before using it. Skip IITB if it is CC BY-NC and you cannot justify it. This source gives your filters real work.
3. **Hinglish:** spend at most 20 minutes on `list_datasets(search="hinglish")` (e.g. L3Cube), and take about 1,500 raw rows. If nothing is usable, list every attempt in `DECISIONS.md`.

Record name, URL, license, download date, count and bytes for each source in `SOURCES.md`. Dates go only there, never in outputs.

**Document = one paragraph.** The pipeline splits raw articles on newlines. Check a real Wikipedia sample first, since paragraphs may be single-`\n` separated. The 10,000 count means paragraph-documents.

## 3. Pipeline

**Pass 1 (streaming, one doc at a time):**
`parse -> normalize -> langid -> quality -> PII -> write to tmp/stage1.jsonl.gz`
Each stage1 row stores `raw_hash` (SHA256 of the un-normalised text) alongside the cleaned text.

**Pass 2 (also streams `stage1.jsonl.gz` line by line; only hashes, MinHash signatures and the 200 eval items live in memory):**
Scan A picks the eval items (bounded heap). Scan B streams the rest for contamination and dedup.
`eval holdout -> contamination vs eval -> exact dedup -> near dedup -> kept`

Every document gets exactly one ledger row: `id, status, stage, reason, dup_of`. This includes `stage=eval_holdout`, so kept + dropped = total.

### Stage rules

- **IDs:** `sha256(source \0 record_index \0 para_index)[:16]`. Never use Python `hash()`, because it is randomized per run. Use `int(id, 16)` if you need a number.
- **Reader:** files in sorted order. Try encodings utf-8-sig, then utf-16, then latin-1. Support `.jsonl`, JSON array, `.csv`/`.tsv`, and `.txt` (blank-line blocks, or one line per doc if there are none). Text field: match `text/content/sentence/hindi/...`, else take the column with the longest average string. Bad records go in a try/except and are logged as `stage=parse`.
- **Normalize (stored text):** NFC; strip ZWSP and BOM only; keep ZWJ/ZWNJ; strip control chars; collapse whitespace; map Devanagari digits to ASCII (stored text gets ASCII digits; record this in `DECISIONS.md`). Do not merge chandrabindu and anusvara, because they distinguish real words. Do not strip HTML here.
- **Quality:** measure HTML-tag ratio and URL count on the raw text, then filter. Drop on high tag ratio, digit/symbol ratio >0.6, U+FFFD, >2 URLs, or under 10 characters. Short proverbs and poems of 10+ characters are deliberately kept.
- **Langid (rule-based):** Count letters by script. Devanagari >=20% of letters means `hi` (covers code-mixed Hindi). Else if Latin is a majority of letters: `hi-Latn` when unambiguous Hindi words (`hai, hain, ka, ki, ke, mein, aur, nahi, kya, bahut...`) make up >=15% of words, otherwise `en`. Anything else (Bengali, Tamil, too few letters) is `other`. Tune the 20% cut using the 30 hand-checked docs. Ignore source labels. Known limit: Marathi and Nepali also come out as `hi`.
- **PII (this order):** email -> Aadhaar -> PAN -> phone. Aadhaar uses digit boundaries and a first digit of 2-9. Phone allows spaces and dashes. Digits are already ASCII after normalize, so detect and replace on the same string (no span mapping). Unit-test that years, prices and plain numbers survive. Note: `+91` plus 10 digits can match Aadhaar first; it is still redacted.
- **Eval holdout:** from clean docs, take the 150 smallest `hi` IDs and 50 smallest `hi-Latn` IDs (a heap, so still streaming). Dedup the 200 among themselves. Purpose: *"Measures LM quality on clean contemporary Hindi/Hinglish prose."*
- **Contamination (train vs eval):** (1) exact: eval `raw_hash` vs train `raw_hash`, (2) normalised: hash of the lowercase normalised text, (3) MinHash near-match. Cross-script: map Devanagari eval tokens and Latin train tokens through a small Hindi word table, and flag overlap >=0.7 for manual review (low recall, say so). Write `contamination.jsonl`, drop leaking train docs (`stage=contamination`), and keep one rejected candidate with the reason.
- **Dedup:** exact = SHA256 of the lowercase normalised key. Near = word 5-gram shingles, MinHash with 64 permutations (`hashlib`), 16 bands x 4 rows, confirmed by true Jaccard. Texts under 5 words use exact only. **Survivor = first doc in sorted file/record order**; the others get `dup_of=<survivor id>`.
- **Determinism:** seed 42, sorted iteration, gzip with `mtime=0`, no timestamps or absolute paths in any output, write to `out.tmp/` then rename.

## 4. Threshold tuning (2:25-2:50)

Pull 30 candidate pairs with Jaccard between 0.5 and 0.95, and label each dup/not-dup by eye. Pick the threshold where precision breaks (expect about 0.8). Save 3 pairs near the threshold. Print 20 quality-dropped docs and save 3 wrong drops for `DECISIONS.md` section 4.

## 5. Outputs

`out/clean/*.jsonl.gz` (`id,text,lang,source`), `out/ledger.csv`, `out/eval.jsonl`, `out/contamination.jsonl`, `out/manifest.json` (sources, input SHA256s, `config` thresholds, per-stage and per-language counts).

`DECISIONS.md` has the brief's 8 sections with `{placeholders}`. `fill_decisions.py` fills every number from `manifest.json`.

## 6. How to explain it (for the interviewer)

| Question | Answer |
|---|---|
| Where do I change a threshold? | `config.py`, one line, and the manifest records it. |
| A new PII type? | `pii.py`, add a regex in order, add a test. |
| A new input format or field name? | `reader.py`. |
| Why two passes? | Eval and dedup need to see all docs; pass 1 stays streaming. |
| Why is restart safe? | Restart-from-scratch: output is renamed only when complete. Not checkpointing. |
| What breaks at 2 TB? | The exact-hash set and MinHash buckets exceed memory. Shard by hash prefix, process shards in parallel. |
| Weak spot? | Cross-script check has low recall, because the transliteration table is small. |

## 7. Final checklist

- [ ] `./run.sh raw out` works with the network off, twice, and `diff -r` is clean
- [ ] Kill mid-run, rerun: identical output, no duplicate rows
- [ ] Ledger rows == input docs, and kept + dropped == total
- [ ] Determinism test is in `tests/`
- [ ] Final kept `hi-Latn` >= 1,000 (after quality, dedup and eval), and `hi` is the majority
- [ ] 1,000-row sample: sort by id, take evenly spaced rows
- [ ] Send repo + `DECISIONS.md` + eval + sample (not the full data)

## 8. Cut list (in order)

1. LSH bands -> compare candidates from an inverted index of shingles.
2. Cross-script -> function-word overlap only.
3. `fill_decisions.py` -> copy numbers by hand from `manifest.json`.

**Never cut:** ledger, PII tests, contamination, determinism check.

## 9. Known nits: check in your run, record in DECISIONS.md (do not pre-fix)

1. **HTML in survivors:** low tag-ratio docs keep their markup, and tags add Latin letters that can skew langid. Grep the 1,000-row sample for `<`/`>`. If found, strip tags in `quality` after the drop decision (about 2 lines), or document it.
2. **Eval may end under 200:** self-dedup of the 200 can shrink it. "About 200" is acceptable. If you refill from the next-smallest IDs, give eval items removed by self-dedup a ledger row (`stage=eval_dedup`) so kept + dropped == total.