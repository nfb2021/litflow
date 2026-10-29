"""
Cited references as DOIs: from Crossref's reference lists, or from a PDF's full text.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .client import ZoteroMCP

CROSSREF = "https://api.crossref.org/works/"
USER_AGENT = f"zot/{__version__} (https://github.com/nfb2021/skills)"

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>\\]+", re.IGNORECASE)
DASHES = str.maketrans({c: "-" for c in "‐‑‒–—−"})


def normalize_doi(doi: str) -> str:
    """'https://doi.org/10.1/ABC.' -> '10.1/abc' (DOIs are case-insensitive)"""
    doi = doi.translate(DASHES).strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.IGNORECASE)
    doi = doi.rstrip(".,;:")
    # Drop a closing bracket that belongs to the surrounding text, not the DOI
    for opening, closing in ("()", "[]"):
        while doi.endswith(closing) and doi.count(closing) > doi.count(opening):
            doi = doi[:-1]
    return doi.lower()


def find_dois(text: str) -> list[str]:
    """Unique DOIs in a piece of text, in order of appearance"""
    seen: dict[str, None] = {}
    for match in DOI_RE.findall(text.translate(DASHES)):
        seen.setdefault(normalize_doi(match), None)
    return [d for d in seen if "/" in d and len(d.split("/", 1)[1]) > 1]


def crossref_references(doi: str, timeout: float = 30) -> tuple[list[str], int]:
    """(DOIs of the references Crossref lists for DOI, number of references in total)

    Crossref knows the reference list when the publisher deposits it (most large
    publishers do). Returns ([], 0) when it does not, or when the DOI is unknown.
    """
    url = CROSSREF + urllib.parse.quote(normalize_doi(doi), safe="/")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            message = json.load(response)["message"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError):
        return [], 0
    references = message.get("reference") or []
    dois: dict[str, None] = {}
    for ref in references:
        if ref.get("DOI"):
            dois.setdefault(normalize_doi(ref["DOI"]), None)
        else:
            # Some publishers put the DOI only into the unstructured citation
            for found in find_dois(ref.get("unstructured", "")):
                dois.setdefault(found, None)
    return list(dois), len(references)


def pdf_references(zot: ZoteroMCP, item_key: str, own_doi: str = "") -> list[str]:
    """DOIs printed in an item's PDF full text (indexed by Zotero), minus its own"""
    content = zot.call(
        "get_content",
        itemKey=item_key,
        mode="complete",
        include={"pdf": True, "abstract": False, "notes": False, "attachments": False},
    )
    text = (
        content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    )
    own = normalize_doi(own_doi) if own_doi else ""
    return [d for d in find_dois(text) if d != own]
