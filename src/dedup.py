"""
Exact + near deduplication.

- Exact: SHA256-style key supplied by caller (hash of normalised lowercase text).
- Near: word 5-gram shingles -> MinHash (64 permutations, coefficients derived
  deterministically from seed 42) -> LSH (16 bands x 4 rows) for candidates ->
  confirmed with TRUE Jaccard of shingle sets (never the MinHash estimate).
- Texts under 5 words: exact only (a 5-gram shingle does not exist).
- Survivor: the first document in sorted file/record order (i.e. the first
  one added); later duplicates point at it via dup_of.

Scale note (DECISIONS.md): kept shingle sets live in memory. Fine at this
scale; at 2 TB this is the first thing that breaks (shard by hash prefix).
"""
import hashlib
import random

try:
    from .config import CONFIG
except ImportError:  # pragma: no cover
    from config import CONFIG

_PRIME = (1 << 61) - 1


def _coeffs(n_perms: int):
    rng = random.Random(CONFIG["seed"])
    return [(rng.randrange(1, _PRIME), rng.randrange(0, _PRIME)) for _ in range(n_perms)]


_COEFFS = _coeffs(CONFIG["minhash_perms"])


def make_shingles(text: str) -> set:
    words = text.lower().split()
    n = CONFIG["shingle_size"]
    if len(words) < n:
        return set()
    shingles = set()
    for i in range(len(words) - n + 1):
        gram = "\x1f".join(words[i:i + n])
        h = int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:8], "big")
        shingles.add(h)
    return shingles


def make_signature(shingle_set: set):
    if not shingle_set:
        return None
    sig = []
    for a, b in _COEFFS:
        sig.append(min((a * h + b) % _PRIME for h in shingle_set))
    return tuple(sig)


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


def band_keys(signature):
    rows = CONFIG["minhash_rows_per_band"]
    for band in range(CONFIG["minhash_bands"]):
        yield band, signature[band * rows:(band + 1) * rows]


# --- cross-script (Devanagari <-> Latin) consonant skeleton -----------------
# Aspirates map to their base consonant; vowels, matras, halant and 'h' are
# dropped on BOTH sides, so भारत -> "brt" and "bharat" -> "brt".
_DEV_SKELETON = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n",
    "च": "c", "छ": "c", "ज": "j", "झ": "j", "ञ": "n",
    "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n",
    "त": "t", "थ": "t", "द": "d", "ध": "d", "न": "n",
    "प": "p", "फ": "p", "ब": "b", "भ": "b", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "s", "ष": "s", "स": "s", "ह": "",
}


def skeleton_tokens(text: str) -> set:
    """Consonant-skeleton token set, script-independent (for cross-script check)."""
    tokens = set()
    for raw_tok in text.lower().split():
        if any("ऀ" <= c <= "ॿ" for c in raw_tok):
            skel = "".join(_DEV_SKELETON.get(c, "") for c in raw_tok)
        else:
            skel = "".join(c for c in raw_tok if c.isalpha() and c not in "aeiouh")
        if len(skel) >= 2:
            tokens.add(skel)
    return tokens


class Deduper:
    def __init__(self, threshold: float = None):
        self.threshold = CONFIG["near_dup_jaccard"] if threshold is None else threshold
        self._exact = {}          # exact_key -> survivor doc_id
        self._bands = {}          # (band, rows tuple) -> [doc_id, ...]
        self._shingles = {}       # doc_id -> shingle set (kept docs only)
        self._order = {}          # doc_id -> insertion order
        self._counter = 0

    def add(self, doc_id: str, exact_key: str, shingle_set: set, signature):
        """Return (is_dup, dup_of, method, best_jaccard)."""
        if exact_key in self._exact:
            return True, self._exact[exact_key], "exact", 1.0

        best_id, best_j = None, 0.0
        if shingle_set and signature:
            candidates = set()
            for key in band_keys(signature):
                candidates.update(self._bands.get(key, ()))
            for cand_id in candidates:
                j = jaccard(shingle_set, self._shingles[cand_id])
                if j > best_j or (j == best_j and best_id is not None
                                   and self._order[cand_id] < self._order[best_id]):
                    best_id, best_j = cand_id, j
            if best_id is not None and best_j >= self.threshold:
                return True, best_id, "near", best_j

        # keep: register as a potential survivor
        self._exact[exact_key] = doc_id
        self._order[doc_id] = self._counter
        self._counter += 1
        if shingle_set and signature:
            self._shingles[doc_id] = shingle_set
            for key in band_keys(signature):
                self._bands.setdefault(key, []).append(doc_id)
        return False, None, "", best_j
