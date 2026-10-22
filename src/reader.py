"""
Streaming reader for raw input.

Supports (see plan.md Sec. 3):
- .jsonl, .json (array), .csv/.tsv, .txt, plus .gz variants of those
- encodings: utf-8-sig, utf-16 (via BOM), latin-1 fallback (per line)
- text-field sniffing: known field names first, else the longest string field
- malformed records are yielded as parse errors, never raised

Document definition:
- wikipedia_* files: one document = one paragraph (split article text on \\n)
- every other row/record: one document = one record
- .txt: blank-line-separated blocks; if the first 100 lines contain no blank
  line, one line = one document

Each yielded dict: {source, record_index, para_index, raw_text}
Parse errors:      {source, record_index, para_index, raw_text: "",
                    parse_error: True, reason: str}
"""
import csv
import gzip
import io
import json
from pathlib import Path

KNOWN_TEXT_FIELDS = [
    "text", "content", "sentence", "hindi", "body", "article",
    "text_content", "passage", "message", "tweet",
]
SUPPORTED = {".jsonl", ".json", ".csv", ".tsv", ".txt"}


def _source_name(path: Path) -> str:
    name = path.name
    for suf in (".jsonl.gz", ".json.gz", ".csv.gz", ".txt.gz", ".jsonl", ".json", ".csv", ".tsv", ".txt", ".gz"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return path.stem


def _iter_decoded_lines(path: Path):
    """Yield str lines, streaming. Handles gzip, UTF-16 BOM, latin-1 fallback."""
    opener = gzip.open if path.name.endswith(".gz") else open
    raw = opener(path, "rb")
    try:
        head = raw.peek(4)[:4] if hasattr(raw, "peek") else b""
        if head[:2] in (b"\xff\xfe", b"\xfe\xff") or head[1:2] == b"\x00" and head[:1] != b"":
            text = io.TextIOWrapper(raw, encoding="utf-16", errors="replace", newline="")
            yield from text
            return
        for bline in raw:
            try:
                yield bline.decode("utf-8-sig")
            except UnicodeDecodeError:
                yield bline.decode("latin-1")
    finally:
        try:
            raw.close()
        except Exception:
            pass


def _pick_text(row) -> str | None:
    if isinstance(row, str):
        return row
    if isinstance(row, (list, tuple)):
        parts = [str(x) for x in row if isinstance(x, str)]
        return " ".join(parts) if parts else None
    if not isinstance(row, dict):
        return None
    lower = {str(k).lower(): k for k in row.keys()}
    for field in KNOWN_TEXT_FIELDS:
        if field in lower:
            val = row[lower[field]]
            if isinstance(val, str) and val.strip():
                return val
    strings = [(k, v) for k, v in row.items() if isinstance(v, str) and v.strip()]
    if strings:
        return max(strings, key=lambda kv: len(kv[1]))[1]
    return None


def _emit_text(source: str, record_index: int, text: str):
    """Yield one or more documents from one record's text."""
    if source.startswith("wikipedia"):
        paras = [p for p in text.split("\n") if p.strip()]
        for para_index, para in enumerate(paras):
            yield {
                "source": source,
                "record_index": record_index,
                "para_index": para_index,
                "raw_text": para,
            }
    else:
        yield {
            "source": source,
            "record_index": record_index,
            "para_index": 0,
            "raw_text": text,
        }


def _iter_jsonl(path: Path, source: str):
    for idx, line in enumerate(_iter_decoded_lines(path)):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as e:
            yield {"source": source, "record_index": idx, "para_index": 0,
                   "raw_text": "", "parse_error": True, "reason": f"json: {e}"}
            continue
        text = _pick_text(row)
        if text is None:
            yield {"source": source, "record_index": idx, "para_index": 0,
                   "raw_text": "", "parse_error": True, "reason": "no text field"}
            continue
        yield from _emit_text(source, idx, text)


def _iter_json_array(path: Path, source: str):
    # JSON arrays are loaded whole (only used for small follow-up files).
    text = "".join(_iter_decoded_lines(path))
    try:
        data = json.loads(text)
    except Exception as e:
        yield {"source": source, "record_index": 0, "para_index": 0,
               "raw_text": "", "parse_error": True, "reason": f"json array: {e}"}
        return
    if not isinstance(data, list):
        data = [data]
    for idx, row in enumerate(data):
        picked = _pick_text(row)
        if picked is None:
            yield {"source": source, "record_index": idx, "para_index": 0,
                   "raw_text": "", "parse_error": True, "reason": "no text field"}
            continue
        yield from _emit_text(source, idx, picked)


def _iter_csv(path: Path, source: str, delimiter: str):
    lines = _iter_decoded_lines(path)
    reader = csv.DictReader(lines, delimiter=delimiter)
    for idx, row in enumerate(reader):
        try:
            text = _pick_text(row)
        except Exception as e:
            text = None
        if text is None:
            yield {"source": source, "record_index": idx, "para_index": 0,
                   "raw_text": "", "parse_error": True, "reason": "no text field"}
            continue
        yield from _emit_text(source, idx, text)


def _iter_txt(path: Path, source: str):
    lines = list(_iter_decoded_lines(path))  # small helper files; ok to buffer lines of one file
    # Decide mode from first 100 lines: blank-line blocks vs one-line-per-doc.
    has_blank = any(not ln.strip() for ln in lines[:100])
    if not has_blank:
        for idx, line in enumerate(lines):
            if line.strip():
                yield {"source": source, "record_index": idx, "para_index": 0,
                       "raw_text": line.strip()}
        return
    block, block_start = [], 0
    for idx, line in enumerate(lines):
        if line.strip():
            if not block:
                block_start = idx
            block.append(line.rstrip("\n"))
        elif block:
            yield {"source": source, "record_index": block_start, "para_index": 0,
                   "raw_text": "\n".join(block)}
            block = []
    if block:
        yield {"source": source, "record_index": block_start, "para_index": 0,
               "raw_text": "\n".join(block)}


def iter_documents(raw_dir):
    """Yield documents from every supported file in raw_dir, sorted by filename."""
    raw_path = Path(raw_dir)
    files = sorted(
        p for p in raw_path.iterdir()
        if p.is_file() and (p.suffix in SUPPORTED or p.name.endswith(".gz"))
    ) if raw_path.is_dir() else []
    for path in files:
        source = _source_name(path)
        suffix = ".jsonl" if path.name.endswith((".jsonl", ".jsonl.gz")) else path.suffix
        if path.name.endswith(".tsv") or path.name.endswith(".tsv.gz"):
            yield from _iter_csv(path, source, "\t")
        elif suffix == ".jsonl":
            yield from _iter_jsonl(path, source)
        elif suffix == ".json":
            yield from _iter_json_array(path, source)
        elif suffix == ".csv":
            yield from _iter_csv(path, source, ",")
        elif suffix == ".txt":
            yield from _iter_txt(path, source)
