"""The project's Gemini Notebook finds; the local PDFs judge.

`rsx ask Q-…` asks the notebook once for all included papers and makes it
quote them. Each quote is looked up in the local PDF text of every included
paper ("anchored"): a quote found there is a lead - paper, page and the exact
sentence(s) to copy into a claim. A paper the notebook quotes nothing from is
recorded as searched with nothing found, by "notebook"; a verifier confirms
that by searching the local text, so an absence rests on two different
methods. The notebook's answer itself is never evidence.

Answers and leads are kept in .rsx/notebook/Q-….json.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from obs import pdftext
from obs.vault import Vault

from rsx.project import Project

BY = "notebook"
# a quote this similar to a page (but not found) is a weak lead: check the page
WEAK = 0.6
MIN_CHARS = 25  # shorter quoted strings are terms, not quotes

PROMPT = """{title}

Go through every source, one by one. For each source that addresses this question:
- name the source by its title;
- quote, word for word and in the source's own language, every sentence that addresses the question. Put each quote in double quotation marks ("...") and do not shorten, translate or paraphrase inside the marks.
Then list the sources that do not address the question. Use only the sources."""

# sent once more when an answer quotes nothing: summaries cannot be checked
STRICT = """Your answer had no word-for-word quotes. Answer again: {title}

Give only quotes: for each source that addresses the question, its title, then every sentence that addresses it, copied word for word in the source's own language inside double quotation marks ("..."). No summary, no translation."""

QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”|„([^“”"]+)[“”"]|«([^»]+)»')
CHIP = re.compile(r"\s*\[\d+(?:\s*[-–,]\s*\d+)*\]")  # citation chips: [1], [2-4]
ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*")


class NotebookError(Exception):
    """gnb is missing, failed, or answered nothing."""


def gnb() -> str:
    exe = os.environ.get("RSX_GNB") or shutil.which("gnb")
    if not exe:
        raise NotebookError(
            "gnb not found: uv tool install --editable ~/src/litflow/gemini_notebook"
        )
    return exe


def prompt(title: str, strict: bool = False) -> str:
    return (STRICT if strict else PROMPT).format(title=title.strip())


def summarised(answer: str) -> bool:
    """The answer cites sources ([1]) but quotes none of them."""
    return bool(CHIP.search(answer)) and not quotes(answer)


def quotes(answer: str) -> list[str]:
    """The quoted passages of an answer, chips removed, split at ellipses."""
    out: list[str] = []
    for m in QUOTED.finditer(answer):
        text = CHIP.sub("", next(g for g in m.groups() if g is not None))
        for part in ELLIPSIS.split(text):
            part = part.strip(" ,;")
            if len(part) >= MIN_CHARS and part not in out:
                out.append(part)
    return out


def ask(notebook: str, question: str, timeout: int = 400) -> str:
    """The notebook's answer to a question (runs `gnb ask --json`)."""
    cmd = [gnb(), "ask", "--json", "-n", notebook, "--timeout", str(timeout), question]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 120)
    except subprocess.TimeoutExpired as e:
        raise NotebookError(f"gnb ask did not finish in {timeout + 120} s") from e
    if r.returncode != 0:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-5:])
        raise NotebookError(f"gnb ask failed (exit {r.returncode}):\n{tail}")
    try:
        answer = json.loads(r.stdout)["answer"]
    except (ValueError, KeyError, TypeError) as e:
        raise NotebookError(f"gnb ask printed no JSON answer: {r.stdout[:200]}") from e
    if not str(answer).strip():
        raise NotebookError("the notebook gave an empty answer")
    return str(answer)


def in_notebook(vault: Vault) -> list:
    """Included papers whose PDF was added to the notebook."""
    return [
        p
        for p in vault.of_type("paper")
        if p.fm.get("screening") == "included" and p.fm.get("in_notebook")
    ]


def page_texts(vault: Vault, papers: list) -> dict[str, list[str]]:
    from obs.cli import paper_pdf

    out = {}
    for p in papers:
        pdf = paper_pdf(vault, p)
        if not pdf:
            continue
        try:
            pages = pdftext.pages(pdf, vault.root / ".obs" / "cache")
        except Exception:  # unreadable PDF: no leads from it
            continue
        if pdftext.has_text(pages):
            out[p.id] = pages
    return out


def anchor(quoted: list[str], texts: dict[str, list[str]]) -> dict:
    """Look every quote up in every paper's text.

    Returns {"leads": {key: [lead]}, "unanchored": [quote]}; a lead is
    {page, status: found | weak, score, text (copied from the page), notebook
    (the quote as the notebook gave it)}. A quote can be in several papers:
    papers repeat each other.
    """
    leads: dict[str, list[dict]] = {}
    unanchored = []
    for q in quoted:
        hit = False
        weak = (0.0, None, None)
        for key, pages in texts.items():
            r = pdftext.find_quote(q, pages)
            if r["status"] in ("found", "approx"):
                text, _ = pdftext.excerpt(q, pages[r["page"] - 1])
                leads.setdefault(key, []).append(
                    {
                        "page": r["page"],
                        "status": "found",
                        "score": r["score"],
                        "text": text or q,
                        "notebook": q,
                    }
                )
                hit = True
            elif r["page"] and r["score"] > weak[0]:
                weak = (r["score"], key, r["page"])
        if hit:
            continue
        score, key, page = weak
        if key and score >= WEAK:
            text, _ = pdftext.excerpt(q, texts[key][page - 1])
            leads.setdefault(key, []).append(
                {
                    "page": page,
                    "status": "weak",
                    "score": score,
                    "text": text,
                    "notebook": q,
                }
            )
        else:
            unanchored.append(q)
    for key, ls in leads.items():
        seen, uniq = set(), []
        for lead in sorted(ls, key=lambda x: (x["status"] != "found", x["page"])):
            if lead["text"] not in seen:
                seen.add(lead["text"])
                uniq.append(lead)
        leads[key] = uniq
    return {"leads": leads, "unanchored": unanchored}


def store(project: Project) -> Path:
    return project.root / ".rsx" / "notebook"


def save(project: Project, qid: str, record: dict) -> Path:
    path = store(project) / f"{qid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), "utf-8")
    return path


def load(project: Project, qid: str) -> dict | None:
    path = store(project) / f"{qid}.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def needs_asking(q, papers: list) -> bool:
    """Never asked, asked before the question changed, or before papers were added."""
    asked = q.fm.get("asked") or {}
    return asked.get("title") != q.title or bool(
        {p.id for p in papers} - set(asked.get("papers") or [])
    )
