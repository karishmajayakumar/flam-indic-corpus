"""
Rule-based language labelling: exactly one of hi / hi-Latn / en / other.

Why rules, not langdetect/fastText (see plan.md Sec. 3):
- langdetect is unreliable and seed-sensitive on short Hinglish.
- Rules are deterministic, offline, and explainable in the follow-up.

Logic:
- >=20% Devanagari letters           -> hi   (covers Devanagari + English mix)
- else, Latin is the majority script:
    >=15% unambiguous Hindi words    -> hi-Latn
    otherwise                        -> en
- anything else (Bengali, Tamil, too few letters, ...) -> other

Ambiguous words (to, me, he, is, ...) are deliberately excluded from the
Hindi list: they are valid in both English and Roman Hindi, so they are
evidence for neither. Source labels are never trusted.
"""
import re

from .config import CONFIG

# Unambiguous Roman-Hindi words only.
HINDI_LATN_WORDS = {
    "hai", "hain", "ka", "ki", "ke", "ko", "mein", "mai", "mujhe", "aur",
    "nahi", "nahin", "kya", "kab", "kahan", "kaun", "kyun", "kaise",
    "bahut", "accha", "achha", "mera", "meri", "mere", "tera", "teri",
    "uska", "uski", "iska", "iski", "hum", "tum", "aap", "bhi", "toh",
    "abhi", "phir", "agar", "lekin", "kyunki", "liye", "wala", "wali",
    "wale", "raha", "rahe", "rahi", "rahe", "hoga", "hogi", "chahiye",
    "karna", "karke", "diya", "gaya", "gayi", "tha", "thi",
    "se", "ne", "par", "pe", "ho", "ya", "jo", "woh", "yeh", "ye",
    "kuch", "sab", "log", "din", "baat", "kaam", "ghar", "paisa",
    "bhai", "yaar", "matlab", "samajh", "lagta", "chalta", "aaya",
    "apna", "apni", "raat", "kal", "aaj", "baad", "pehle", "baar",
    "jata", "jati", "tumhe", "usse", "isse", "sirf", "shayad",
}

_WORD_RE = re.compile(r"[a-z']+")


def _is_devanagari(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def _is_latin(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def classify_with_scores(text: str) -> dict:
    letters = [c for c in text if c.isalpha()]
    total = len(letters)
    dev = sum(1 for c in letters if _is_devanagari(c))
    lat = sum(1 for c in letters if _is_latin(c))
    dev_ratio = dev / total if total else 0.0
    lat_ratio = lat / total if total else 0.0

    words = _WORD_RE.findall(text.lower())
    hindi_hits = sum(1 for w in words if w in HINDI_LATN_WORDS)
    hindi_ratio = hindi_hits / len(words) if words else 0.0

    if total < CONFIG["min_letters"]:
        label = "other"
    elif dev_ratio >= CONFIG["devanagari_min_ratio"]:
        label = "hi"
    elif lat_ratio > 0.5:
        label = "hi-Latn" if hindi_ratio >= CONFIG["hinglish_min_ratio"] else "en"
    else:
        label = "other"

    return {
        "lang": label,
        "dev_ratio": round(dev_ratio, 3),
        "lat_ratio": round(lat_ratio, 3),
        "hindi_word_ratio": round(hindi_ratio, 3),
        "letters": total,
    }


def classify(text: str) -> str:
    return classify_with_scores(text)["lang"]
