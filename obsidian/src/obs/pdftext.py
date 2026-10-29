"""PDF text per page, and checking that a quote really occurs in it."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st"}
APPROX = 0.9  # minimum similarity for an approximate match


def pages(pdf: Path, cache: Path | None = None) -> list[str]:
    """Text of each page. pdftotext if installed (better layout), else pypdf."""
    key = hashlib.sha1(f"{pdf.resolve()}:{pdf.stat().st_mtime_ns}".encode()).hexdigest()
    cached = cache / f"{key}.txt" if cache else None
    if cached and cached.exists():
        return cached.read_text(encoding="utf-8").split("\f")
    if shutil.which("pdftotext"):
        out = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(pdf), "-"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        result = out.split("\f")
        if result and not result[-1].strip():
            result = result[:-1]
    else:
        import logging

        from pypdf import PdfReader

        logging.getLogger("pypdf").setLevel(logging.ERROR)

        result = [p.extract_text() or "" for p in PdfReader(str(pdf)).pages]
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text("\f".join(result), encoding="utf-8")
    return result


def normalize(text: str) -> str:
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # hyphenation at line ends
    text = text.lower()
    text = re.sub(r"[^\w%.,]+", " ", text)  # quotes, dashes, symbols -> space
    return re.sub(r"\s+", " ", text).strip()


def has_text(page_texts: list[str]) -> bool:
    """False for image-only scans (no text layer): fewer than ~100 letters a page."""
    letters = sum(len(re.findall(r"[^\W\d_]", t)) for t in page_texts)
    return letters >= 100 * max(1, len(page_texts)) * 0.5


def _compact(text: str) -> str:
    return re.sub(r"[^\w]", "", text)


def find_quote(quote: str, page_texts: list[str]) -> dict:
    """Locate a quote. Returns {status, page (1-based), score}.

    status: found (exact after normalizing), approx (>= APPROX similar),
    not-found, no-text (the PDF is a scan without a text layer: OCR it).
    """
    if not has_text(page_texts):
        return {"status": "no-text", "page": None, "score": 0.0}
    q = normalize(quote)
    if len(q) < 12:
        return {
            "status": "not-found",
            "page": None,
            "score": 0.0,
            "reason": "quote too short to check",
        }
    norm = [normalize(t) for t in page_texts]
    for i, t in enumerate(norm):
        if q in t:
            return {"status": "found", "page": i + 1, "score": 1.0}
    # text spanning a page break
    for i in range(len(norm) - 1):
        if q in norm[i] + " " + norm[i + 1]:
            return {"status": "found", "page": i + 1, "score": 1.0}
    # extraction that lost or invented spaces ("ofLooks", "a n d")
    qc = _compact(q)
    for i, t in enumerate(norm):
        if qc in _compact(t):
            return {"status": "found", "page": i + 1, "score": 1.0}
    best = (0.0, None)
    words = q.split()
    anchor_len = min(4, len(words))
    anchors = {
        " ".join(words[j : j + anchor_len])
        for j in range(0, len(words) - anchor_len + 1, anchor_len)
    }
    for i, t in enumerate(norm):
        for a in anchors:
            for m in re.finditer(re.escape(a), t):
                start = max(0, m.start() - len(q))
                window = t[start : m.start() + 2 * len(q)]
                sm = SequenceMatcher(None, q, window, autojunk=False)
                blocks = sm.get_matching_blocks()
                matched = sum(b.size for b in blocks)
                score = matched / len(q)
                if score > best[0]:
                    best = (score, i + 1)
    if best[0] >= APPROX:
        return {"status": "approx", "page": best[1], "score": round(best[0], 3)}
    return {"status": "not-found", "page": best[1], "score": round(best[0], 3)}
