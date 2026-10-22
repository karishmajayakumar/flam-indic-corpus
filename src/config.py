"""All thresholds in one place. This dict is copied into manifest.json."""

CONFIG = {
    # langid
    "devanagari_min_ratio": 0.20,   # >=20% Devanagari letters -> hi (covers code-mixed)
    "hinglish_min_ratio": 0.15,     # >=15% unambiguous Hindi words (Latin text) -> hi-Latn
    "min_letters": 3,               # fewer letters than this -> other
    # quality (used by quality.py, next step)
    "min_chars": 10,
    "max_digit_symbol_ratio": 0.6,
    "max_urls": 2,
    "max_html_tag_ratio": 0.20,     # a lone <p>..</p> on a short doc is ~0.14; real markup is >0.5
    # dedup (used by dedup.py, next step)
    "shingle_size": 5,
    "minhash_perms": 64,
    "minhash_bands": 16,
    "minhash_rows_per_band": 4,
    "near_dup_jaccard": 0.8,        # tuned on 30 labelled pairs: not-dups reach 0.667, clear dups start 0.833 (tuning/pairs.jsonl)
    # contamination cross-script: only across different scripts, high bar
    "cross_script_min_overlap": 0.8,
    "cross_script_min_shared": 5,
    "cross_script_min_jaccard": 0.5,  # kills subset matches: short eval inside long unrelated doc
    # eval
    "eval_hi": 150,
    "eval_hi_latn": 50,
    "seed": 42,
}
