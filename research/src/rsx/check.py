"""The startup check: is everything the project needs in place?

`rsx check` looks at four things and stores its verdict in .rsx/check.json:

- tools: the commands the workflow runs;
- services: Zotero with write access, Better BibTeX, the Google login of gnb;
- choices: what only the user decides (collection, notebook, depth, how papers
  are fetched, seed papers); agents ask, they never pick;
- export: the Better BibTeX auto-export of the collection into refs.bib.

The workflow does not start (stage `setup`) until a check of the current
rsx.toml has passed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.request
from datetime import datetime

from rsx import snowball
from rsx.project import MARKER, Project

TOOLS = {
    "obs": "uv tool install --editable ~/src/litflow/obsidian",
    "zot": "uv tool install --editable ~/src/litflow/zotero",
    "gnb": "uv tool install --editable ~/src/litflow/gemini_notebook",
    "typst": "brew install typst",
    "pdftotext": "brew install poppler",
}
OPTIONAL = {"ocrmypdf": "brew install ocrmypdf (only for scanned PDFs)"}
BBT = "http://127.0.0.1:23119/better-bibtex/cayw?probe=true"
NOTEBOOK_LIMIT = 50  # sources per notebook on the free plan

ASK = {
    "collection": (
        'rsx config collection "NAME"',
        "Which Zotero collection holds this project's papers (a new name creates it)?",
    ),
    "notebook": (
        "rsx notebook use URL|none",
        "Which Gemini Notebook should hold the PDFs: an empty one you create, or none?",
    ),
    "depth": (
        "rsx config depth N",
        "How many levels of references should the snowball follow from the seeds (0 = none)?",
    ),
    "fetch": (
        "rsx config fetch zotero|manual",
        "Should Zotero fetch the papers itself (you connect to the institution's network "
        "or VPN first), or should litflow give you the DOIs to add by hand?",
    ),
}


def _item(group, name, ok, fix="", level="error") -> dict:
    return {"group": group, "item": name, "ok": bool(ok), "level": level, "fix": fix}


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def choices(p: Project) -> list[dict]:
    """What the user still has to decide. No services needed (rsx next calls it)."""
    out = []
    for key, (cmd, question) in ASK.items():
        value = getattr(p, key)
        ok = bool(value)
        if key == "depth":
            ok = snowball.depth_of(p) is not None
        if key == "fetch":
            ok = value in ("zotero", "manual")
        out.append(_item("choices", key, ok, f"ask the user: {question} -> {cmd}"))
    if (snowball.depth_of(p) or 0) > 0 and not snowball.load(p)["seeds"]:
        out.append(
            _item(
                "choices",
                "seeds",
                False,
                "ask the user: Which papers start the snowball (DOIs)? -> rsx snowball seed DOI ...",
            )
        )
    return out


def run(p: Project) -> list[dict]:
    out = []
    for cmd, fix in TOOLS.items():
        out.append(_item("tools", cmd, shutil.which(cmd), fix))
    for cmd, fix in OPTIONAL.items():
        out.append(_item("tools", cmd, shutil.which(cmd), fix, "warn"))

    zot = shutil.which("zot")
    r = _run([zot, "status"], 30) if zot else None
    text = (r.stdout + r.stderr) if r else ""
    out.append(
        _item(
            "services",
            "Zotero",
            r is not None and r.returncode == 0,
            "start the Zotero app (with the Zotero MCP plugin)",
        )
    )
    out.append(
        _item(
            "services",
            "Zotero write access",
            "Write operations enabled" in text,
            "Zotero > Settings > Zotero MCP > Enable Write Operations",
        )
    )
    try:
        with urllib.request.urlopen(BBT, timeout=5) as resp:
            bbt = resp.read().decode().strip() == "ready"
    except OSError:
        bbt = False
    out.append(
        _item(
            "services",
            "Better BibTeX",
            bbt,
            "install Better BibTeX in Zotero and restart Zotero",
        )
    )
    if p.notebook not in ("", "none"):
        gnb = shutil.which("gnb")
        r = _run([gnb, "auth", "status"], 30) if gnb else None
        out.append(
            _item(
                "services",
                "Google login (gnb)",
                r is not None and "Authenticated: Yes" in r.stdout,
                "gnb auth setup",
            )
        )

    out += choices(p)

    if p.collection and zot:
        r = _run([zot, "pdfs", "-c", p.collection, "--json"], 300)
        try:
            rows = json.loads(r.stdout) if r and r.returncode == 0 else None
        except ValueError:
            rows = None
        if rows is None:
            out.append(
                _item(
                    "export",
                    f"collection {p.collection}",
                    False,
                    "it does not exist yet: `rsx snowball fetch` creates it with the seeds "
                    "(fetch=zotero), or create it in Zotero; then run rsx check again",
                    "warn",
                )
            )
        else:
            dois = {snowball.norm(x["doi"]) for x in rows if x.get("doi")}
            from obs import bib

            have = set()
            if p.bib.exists():
                have = {
                    snowball.norm(bib.clean(e.get("doi", "")))
                    for e in bib.parse_bib(p.bib.read_text("utf-8"))
                }
            missing = sorted(dois - have)
            out.append(
                _item(
                    "export",
                    "refs.bib auto-export",
                    not missing,
                    f"refs.bib lacks {len(missing)} of the collection's {len(dois)} papers: "
                    f"in Zotero right-click '{p.collection}' > Export Collection > Better BibTeX, "
                    f"tick 'Keep updated', save as {p.bib}",
                )
            )
            no_pdf = [x for x in rows if not x.get("pdf")]
            out.append(
                _item(
                    "export",
                    "PDFs",
                    not no_pdf,
                    f"{len(no_pdf)} of {len(rows)} papers have no PDF: on the institution's "
                    "network or VPN select them in Zotero > Find Available PDF, or add them "
                    "by hand (`zot pdfs -c COLLECTION --missing` lists them)",
                    "warn",
                )
            )
    if p.notebook not in ("", "none"):
        n = sum(1 for x in p.vault.of_type("paper") if x.fm.get("in_notebook"))
        out.append(
            _item(
                "choices",
                "notebook size",
                n <= NOTEBOOK_LIMIT,
                f"{n} PDFs in the notebook; a notebook holds {NOTEBOOK_LIMIT}: use a second one",
                "warn",
            )
        )
    return out


def config_hash(p: Project) -> str:
    return hashlib.sha256((p.root / MARKER).read_bytes()).hexdigest()[:16]


def record(p: Project, items: list[dict]) -> dict:
    ok = all(i["ok"] or i["level"] != "error" for i in items)
    rec = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "ok": ok,
        "config": config_hash(p),
        "problems": [i for i in items if not i["ok"]],
    }
    f = p.root / ".rsx" / "check.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(rec, indent=1) + "\n", "utf-8")
    return rec


def passed(p: Project) -> bool:
    """A check of the current rsx.toml passed."""
    f = p.root / ".rsx" / "check.json"
    if not f.exists():
        return False
    rec = json.loads(f.read_text("utf-8"))
    return bool(rec.get("ok")) and rec.get("config") == config_hash(p)
