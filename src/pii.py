"""
PII redaction for Indian identifiers.

Order is deliberate:
  1. EMAIL   - first, so 9876543210@gmail.com is not eaten by the phone rule
  2. PHONE with explicit +91 - before Aadhaar, so +91 numbers are PHONE
  3. AADHAAR - 12 digits, first digit 2-9 (UIDAI), digit boundaries so it
               cannot match inside a longer number
  4. PAN     - [A-Z]{5}[0-9]{4}[A-Z], bounded
  5. PHONE   - Indian mobiles: [6-9] + 9 digits, optional 0/+91 prefix,
               optional space/dash after the 5th digit

Devanagari digits have already been mapped to ASCII by normalize.py, so
detection and replacement happen on the same string.
Years, prices, pincodes, OTPs and other plain numbers must survive - see tests.
"""
import re

_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    ("PHONE", re.compile(r"(?<![0-9])\+91[\s-]?(?:[6-9][0-9]{4})[\s-]?[0-9]{5}(?![0-9])"), "<PHONE>"),
    ("AADHAAR", re.compile(r"(?<![0-9])[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}(?![0-9])"), "<AADHAAR>"),
    ("PAN", re.compile(r"(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])"), "<PAN>"),
    ("PHONE", re.compile(r"(?<![0-9])(?:0)?[6-9][0-9]{4}[\s-]?[0-9]{5}(?![0-9])"), "<PHONE>"),
]


def redact(text: str):
    """Return (redacted_text, counts dict)."""
    counts = {}
    for name, pattern, replacement in _PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts
