"""A small BibTeX reader for Better BibTeX exports: entries, citekeys, fields."""

from __future__ import annotations

import re
import unicodedata

_ENTRY = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
_LATEX = {
    r"\&": "&",
    r"\%": "%",
    r"\_": "_",
    r"\$": "$",
    r"\#": "#",
    "--": "–",
    "~": " ",
}


def _value(text: str, i: int) -> tuple[str, int]:
    """Read one field value starting at text[i]; returns (raw value, next index)."""
    parts = []
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        c = text[i]
        if c == "{":
            depth, j = 0, i
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            parts.append(text[i + 1 : j])
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < len(text) and not (text[j] == '"' and text[j - 1] != "\\"):
                j += 1
            parts.append(text[i + 1 : j])
            i = j + 1
        else:
            m = re.match(r"[^,#}\s]+", text[i:])
            parts.append(m.group(0) if m else "")
            i += m.end() if m else 1
        while i < len(text) and text[i].isspace():
            i += 1
        if i < len(text) and text[i] == "#":  # string concatenation
            i += 1
            continue
        return "".join(parts), i
    return "".join(parts), i


_ACCENTS = {
    "'": "\u0301",
    "`": "\u0300",
    "^": "\u0302",
    '"': "\u0308",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "c": "\u0327",
}


def _accent(m: re.Match) -> str:
    """\\"{o} -> ö"""
    return unicodedata.normalize("NFC", m.group(2) + _ACCENTS[m.group(1).strip()])


def clean(value: str) -> str:
    """Strip braces and common LaTeX escapes; collapse whitespace."""
    value = re.sub(r"\\(['`^\"~=.]|c\s)\{?([A-Za-z])\}?", _accent, value)
    for k, v in _LATEX.items():
        value = value.replace(k, v)
    value = re.sub(r"\\[a-zA-Z]+\s*\{([^{}]*)\}", r"\1", value)  # \emph{x} -> x
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def parse_bib(text: str) -> list[dict]:
    """Entries as dicts: {'ENTRYTYPE', 'ID', field: cleaned value}."""
    entries = []
    for m in _ENTRY.finditer(text):
        etype = m.group(1).lower()
        if etype in ("comment", "string", "preamble"):
            continue
        i = m.end()
        km = re.match(r"\s*([^,\s]+)\s*,", text[i:])
        if not km:
            continue
        entry = {"ENTRYTYPE": etype, "ID": km.group(1)}
        i += km.end()
        while True:
            fm = re.match(r"\s*([A-Za-z][\w-]*)\s*=\s*", text[i:])
            if not fm:
                break
            raw, i = _value(text, i + fm.end())
            entry[fm.group(1).lower()] = raw
            while i < len(text) and text[i] in " \t\r\n,":
                i += 1
        entries.append(entry)
    return entries


def authors(value: str) -> list[str]:
    """'Last, First and Other, A.' -> ['First Last', 'A. Other']"""
    out = []
    for name in re.split(r"\s+and\s+", clean(value)):
        if "," in name:
            last, first = (s.strip() for s in name.split(",", 1))
            name = f"{first} {last}".strip()
        if name:
            out.append(name)
    return out


def pdf_files(value: str) -> list[str]:
    """BBT `file` field: 'a.pdf;b.pdf' or Zotero 'desc:path:mime' triples."""
    out = []
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) >= 3 and bits[-1].startswith("application/"):
            part = ":".join(bits[1:-1])
        if part.lower().endswith(".pdf"):
            out.append(part.replace("\\:", ":"))
    return out


def paper_fields(entry: dict) -> dict:
    """Frontmatter for a paper note from a bib entry."""
    year = clean(entry.get("year", "") or entry.get("date", "")[:4])
    fm = {
        "title": clean(entry.get("title", "")),
        "authors": authors(entry.get("author", "")),
        "year": int(year) if year.isdigit() else None,
        "venue": clean(
            entry.get("journal", "")
            or entry.get("journaltitle", "")
            or entry.get("booktitle", "")
            or entry.get("publisher", "")
        ),
        "doi": clean(entry.get("doi", "")).lower() or None,
        "entry_type": entry["ENTRYTYPE"],
    }
    pdfs = pdf_files(entry.get("file", ""))
    if pdfs:
        fm["pdf"] = pdfs[0]
    return {k: v for k, v in fm.items() if v not in (None, "", [])}
