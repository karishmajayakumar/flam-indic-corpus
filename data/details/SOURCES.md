# Sources

Download date for all: 2026-10-22. Raw files in `data/raw/`, saved exactly as downloaded
(no splitting/filtering at download time). Reproduce with `./download.sh`.

| # | Name | URL | Config / field | License | Downloaded | Size |
|---|---|---|---|---|---|---|
| 1 | Wikimedia Wikipedia (Hindi) | https://huggingface.co/datasets/wikimedia/wikipedia | `20231101.hi`, `train`, streaming, field `text` | CC BY-SA 3.0 (per HF dataset card) | 2,500 articles | 33.21 MB |
| 2 | FineWeb-2 (Hindi, Devanagari) | https://huggingface.co/datasets/HuggingFaceFW/fineweb-2 | `hin_Deva`, `train`, streaming, field `text` | ODC-By 1.0; also subject to Common Crawl Terms of Use | 6,000 docs | 43.01 MB |
| 3 | PHINC (Hinglish, veezbo mirror) | https://huggingface.co/datasets/veezbo/phinc (original: https://zenodo.org/record/3605597, Srivastava & Singh, WNUT 2020) | `train`, streaming, field `Sentence` (not `English_Translation`) | CC BY 4.0 (verified on Zenodo record 3605597, 2026-10-22; not stated on the HF mirror card) | 3,000 rows | 0.63 MB |

## Verification (2026-10-22, from the downloaded files)

- `wikipedia_hi.jsonl`: 2,500/2,500 articles Devanagari-dominant (>=20% of letters).
  Split on `\n` gives 88,526 non-empty paragraphs (19,026 are >=200 chars) — the
  pipeline must define "document" carefully; see plan.md Sec. 2/9.
- `fineweb2_hin_Deva.jsonl`: 6,000/6,000 docs Devanagari-dominant, median ~1,481 chars.
- `phinc_hinglish.jsonl`: 2,995/3,000 Latin-dominant; ~1,947/3,000 pass a rough
  Hinglish heuristic (>=1 unambiguous Hindi word, >=8% of words) — pipeline
  labels 2,178 `hi-Latn` (config threshold), comfortably above the 1,000 target.
- Raw rows total 11,500; paragraph-documents (Wikipedia paragraphs + FineWeb docs
  + PHINC rows) total 97,526 input documents, far above the 10,000 requirement.

## Not used

- COMI-LINGUA (https://huggingface.co/datasets/LingoIITGN/COMI-LINGUA, CC BY 4.0):
  checked 2026-10-22 — its `Sentences` column is mostly Devanagari Hindi with
  English words, i.e. `hi` not `hi-Latn` under our langid, so it does not solve
  the Hinglish requirement. Kept as a backup Hindi source.
