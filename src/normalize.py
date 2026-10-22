"""
Text normalisation for Hindi / Hinglish.

Rules (see plan.md Sec. 3, DECISIONS.md):
- NFC only. NFC already makes nukta forms consistent.
- Do NOT merge chandrabindu (U+0901) and anusvara (U+0902): they distinguish
  real words. Such folding, if ever wanted, belongs in a comparison key only.
- Strip only ZWSP (U+200B) and BOM (U+FEFF). Keep ZWJ (U+200D) / ZWNJ (U+200C):
  they are meaningful in Devanagari.
- Strip control characters, collapse all whitespace to single spaces.
- Map Devanagari digits (U+0966-U+096F) to ASCII. Stored text therefore has
  ASCII digits, which lets pii.py detect-and-replace on the same string
  (no fragile span mapping between two versions of the text).
- Do NOT strip HTML here: quality.py measures tag ratio on the raw text.
"""
import re
import unicodedata

_DEV_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_DEV_DIGIT_TABLE = str.maketrans(_DEV_DIGITS)
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_DEV_DIGIT_TABLE)
    out = []
    for ch in text:
        if ch in (chr(0x200B), chr(0xFEFF)):  # ZWSP, BOM
            continue
        if unicodedata.category(ch) == "Cc":  # control chars -> space
            out.append(" ")
            continue
        out.append(ch)
    text = "".join(out)
    return _WS_RE.sub(" ", text).strip()


def comparison_key(text: str) -> str:
    """Key for exact dedup / contamination: normalised + lowercased."""
    return normalize_text(text).lower()
