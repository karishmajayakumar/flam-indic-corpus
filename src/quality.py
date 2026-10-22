"""
Low-quality filtering.

Features (HTML ratio, URL count) are measured on the RAW text, before
normalize.py has a chance to remove markup (plan.md Sec. 3). For documents
that survive, markup tags are stripped from the stored text (known nit #1).

Deliberate trade-off (DECISIONS.md): short proverbs/poems of >= min_chars
are kept; only truly tiny fragments are dropped as too_short.
"""
import re
import unicodedata

try:
    from .config import CONFIG
    from .normalize import normalize_text
except ImportError:  # pragma: no cover
    from config import CONFIG
    from normalize import normalize_text

_TAG_RE = re.compile(r"<[^>]{1,200}>")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _digit_symbol_ratio(text: str) -> float:
    """Share of non-space chars that are digits or symbols/punctuation.

    Letters (L*) and combining marks (M*, e.g. Devanagari matras) count as
    letters; everything else that is not whitespace counts against.
    """
    total = 0
    bad = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        cat = unicodedata.category(ch)
        if cat.startswith("L") or cat.startswith("M"):
            continue
        bad += 1
    return bad / total if total else 0.0


def raw_features(raw_text: str) -> dict:
    tag_chars = sum(len(m.group(0)) for m in _TAG_RE.finditer(raw_text))
    return {
        "html_tag_ratio": round(tag_chars / len(raw_text), 4) if raw_text else 0.0,
        "url_count": len(_URL_RE.findall(raw_text)),
        "has_replacement_char": "�" in raw_text,
    }


def assess(raw_text: str, normalized_text: str):
    """Return (keep: bool, reason: str, cleaned_text: str).

    cleaned_text is the normalised text with markup stripped (survivors only).
    """
    feats = raw_features(raw_text)
    if feats["has_replacement_char"]:
        return False, "garbled_encoding", normalized_text
    if len(normalized_text) < CONFIG["min_chars"]:
        return False, "too_short", normalized_text
    if feats["html_tag_ratio"] > CONFIG["max_html_tag_ratio"]:
        return False, "markup", normalized_text
    if feats["url_count"] > CONFIG["max_urls"]:
        return False, "too_many_urls", normalized_text
    if _digit_symbol_ratio(normalized_text) > CONFIG["max_digit_symbol_ratio"]:
        return False, "numeric_or_symbol_heavy", normalized_text

    cleaned = _TAG_RE.sub(" ", normalized_text)
    cleaned = normalize_text(cleaned)  # re-collapse whitespace after stripping
    if len(cleaned) < CONFIG["min_chars"]:
        return False, "too_short_after_markup_strip", cleaned
    return True, "", cleaned
