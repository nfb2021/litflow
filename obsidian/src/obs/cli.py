"""obs: a research vault for literature work, readable in Obsidian.

Lists and results go to stdout; progress and hints go to stderr.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import typer

from obs import __version__, bib, lint, pdftext, provenance, query, wayfinder
from obs.templates import PROTOCOL, VAULT_README
from obs.vault import (
    DRIFT,
    HUMAN_KINDS,
    MARKER,
    Q_KINDS,
    ROLES,
    SCHEMA,
    SEALED,
    TYPES,
    Vault,
    VaultError,
    link,
    refuse_lead,
    set_section,
    slugify,
)

app = typer.Typer(
    help="obs: research vault - papers, statements, claims with provenance, question maps, lint gate.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
paper_app = typer.Typer(
    help="Papers: one note per paper, keyed by citekey.", no_args_is_help=True
)
statement_app = typer.Typer(
    help="Statements: canonical propositions that papers assert.", no_args_is_help=True
)
claim_app = typer.Typer(
    help="Claims: one paper asserting one statement, with a verbatim quote.",
    no_args_is_help=True,
)
map_app = typer.Typer(
    help="Maps: a destination plus its question tickets.", no_args_is_help=True
)
q_app = typer.Typer(
    help="Questions: tickets on a map, worked one per session.", no_args_is_help=True
)
term_app = typer.Typer(
    help="Glossary terms (concept notes with aliases).", no_args_is_help=True
)
app.add_typer(paper_app, name="paper")
app.add_typer(statement_app, name="statement")
app.add_typer(claim_app, name="claim")
app.add_typer(map_app, name="map")
app.add_typer(q_app, name="q")
app.add_typer(term_app, name="term")

VaultOpt = typer.Option(
    None,
    "--vault",
    "-V",
    help="Vault folder (default: $OBS_VAULT, else search upwards from cwd)",
)
JsonOpt = typer.Option(False, "--json", help="Machine-readable output")


def info(msg: str) -> None:
    typer.echo(msg, err=True)


def fail(msg: str, code: int = 1) -> None:
    typer.echo(f"error: {msg}", err=True)
    raise typer.Exit(code)


def emit(data) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def open_vault(path) -> Vault:
    try:
        return Vault.open(path)
    except VaultError as e:
        fail(str(e))


def today() -> str:
    return dt.date.today().isoformat()


def version_cb(value: bool) -> None:
    if value:
        typer.echo(f"obs {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_cb,
        is_eager=True,
        help="Show the version and exit",
    ),
) -> None:
    pass


# --- init / status / lint ----------------------------------------------------
@app.command()
def init(
    path: Path = typer.Argument(
        ..., help="Folder for the new vault (created if missing)"
    ),
    title: str = typer.Option("Literature research", "--title", help="Project title"),
) -> None:
    """Create a vault: folders, obs.toml, protocol.md and a README for agents."""
    path = path.expanduser().resolve()
    if (path / MARKER).exists():
        fail(f"{path} is already a vault")
    path.mkdir(parents=True, exist_ok=True)
    for folder, _ in TYPES.values():
        (path / folder).mkdir(exist_ok=True)
    (path / MARKER).write_text(
        f'schema = {SCHEMA}\ntitle = "{title}"\ncreated = "{today()}"\n',
        encoding="utf-8",
    )
    if not (path / "protocol.md").exists():
        (path / "protocol.md").write_text(
            PROTOCOL.format(title=title), encoding="utf-8"
        )
    (path / "README.md").write_text(VAULT_README.format(title=title), encoding="utf-8")
    gi = path / ".gitignore"
    if not gi.exists():
        gi.write_text(".obs/\n.obsidian/workspace*.json\n", encoding="utf-8")
    info(f"vault created at {path}")
    typer.echo(str(path))


@app.command()
def status(vault: Path = VaultOpt, as_json: bool = JsonOpt) -> None:
    """Counts per type and the next things to do."""
    v = open_vault(vault)
    counts = {t: len(v.of_type(t)) for t in TYPES}
    papers = v.of_type("paper")
    claims = v.of_type("claim")
    data = {
        "vault": str(v.root),
        "counts": counts,
        "papers_pending_screening": sum(
            p.fm.get("screening", "pending") == "pending" for p in papers
        ),
        "claims_unverified": sum(
            c.fm.get("verification", "unverified") == "unverified" for c in claims
        ),
        "claims_quote_unchecked": sum(c.fm.get("quote_check") is None for c in claims),
        "frontier": [q.id for q in wayfinder.frontier(v)],
        "lint": lint.summary(lint.lint(v)),
    }
    if as_json:
        emit(data)
        return
    typer.echo(f"vault: {data['vault']}")
    typer.echo("  " + "  ".join(f"{t}s: {n}" for t, n in counts.items()))
    typer.echo(
        f"  papers to screen: {data['papers_pending_screening']}  claims unverified: {data['claims_unverified']}  quotes unchecked: {data['claims_quote_unchecked']}"
    )
    typer.echo(f"  frontier: {', '.join(data['frontier']) or '(empty)'}")
    typer.echo(
        f"  lint: {data['lint']['errors']} errors, {data['lint']['warnings']} warnings"
    )


@app.command("lint")
def lint_cmd(
    vault: Path = VaultOpt,
    as_json: bool = JsonOpt,
    gate: bool = typer.Option(
        False, "--gate", help="Print one JSON verdict and exit 0 (for workflow gates)"
    ),
    strict: bool = typer.Option(False, "--strict", help="Warnings also fail"),
    only: list[str] = typer.Option([], "--only", help="Only these issue codes"),
    note: list[str] = typer.Option([], "--note", help="Only issues on these notes"),
) -> None:
    """Check the vault against the research rules. Exit 1 on errors."""
    v = open_vault(vault)
    issues = lint.lint(v)
    if only:
        issues = [i for i in issues if i["code"] in only]
    if note:
        issues = [i for i in issues if i["note"] in note]
    s = lint.summary(issues)
    blocked = s["errors"] > 0 or (strict and s["warnings"] > 0)
    if gate:
        emit({"verdict": "blocked" if blocked else "pass", **s, "issues": issues[:50]})
        return
    if as_json:
        emit({"ok": not blocked, **s, "issues": issues})
    else:
        for i in sorted(
            issues, key=lambda i: (i["level"] != "error", i["code"], i["note"])
        ):
            typer.echo(
                f"{i['level']:7} {i['code']:28} {i['note']}: {i['msg']}"
                + (f"  -> {i['fix']}" if i["fix"] else "")
            )
        info(f"{s['errors']} errors, {s['warnings']} warnings")
    if blocked:
        raise typer.Exit(1)


# --- papers -----------------------------------------------------------------
@paper_app.command("add")
def paper_add(
    citekey: str = typer.Argument(
        ..., help="Citekey, exactly as in the Better BibTeX export"
    ),
    title: str = typer.Option(..., "--title"),
    year: int = typer.Option(None, "--year"),
    author: list[str] = typer.Option([], "--author", "-a", help="Repeat per author"),
    doi: str = typer.Option(None, "--doi"),
    venue: str = typer.Option(None, "--venue"),
    pdf: str = typer.Option(None, "--pdf", help="Local PDF path"),
    vault: Path = VaultOpt,
) -> None:
    """Add one paper by hand. Prefer `obs paper sync refs.bib`."""
    v = open_vault(vault)
    fm = {
        "title": title,
        "authors": author,
        "year": year,
        "venue": venue,
        "doi": doi.lower() if doi else None,
        "pdf": pdf,
    }
    fm = {k: x for k, x in fm.items() if x not in (None, [], "")}
    fm["screening"] = "pending"
    try:
        n = v.create("paper", fm, f"\n# {title}\n\n## Notes\n\n", note_id=citekey)
    except VaultError as e:
        fail(str(e))
    typer.echo(n.id)


@paper_app.command("sync")
def paper_sync(
    bibfile: Path = typer.Argument(..., help="Better BibTeX export (.bib)"),
    vault: Path = VaultOpt,
) -> None:
    """Create paper notes for new bib entries; refresh bib fields of existing ones.

    Never touches screening, notes or claims.
    """
    v = open_vault(vault)
    if not bibfile.exists():
        fail(f"{bibfile} not found")
    entries = bib.parse_bib(bibfile.read_text(encoding="utf-8", errors="replace"))
    created = updated = 0
    for e in entries:
        fields = bib.paper_fields(e)
        key = e["ID"]
        if key in v.notes:
            n = v.notes[key]
            changed = {k: x for k, x in fields.items() if n.fm.get(k) != x}
            if changed:
                n.fm.update(changed)
                v.save(n)
                updated += 1
        else:
            try:
                v.create(
                    "paper",
                    {**fields, "screening": "pending"},
                    f"\n# {fields.get('title', key)}\n\n## Notes\n\n",
                    note_id=key,
                )
            except VaultError as err:
                info(f"skipped {key}: {err}")
                continue
            created += 1
    info(f"{len(entries)} entries: {created} new, {updated} updated")


@paper_app.command("screen")
def paper_screen(
    citekey: str,
    include: bool = typer.Option(None, "--include/--exclude", help="Decision"),
    reason: str = typer.Option(
        ...,
        "--reason",
        help="The protocol criterion, e.g. 'I2: peer-reviewed L-band study'",
    ),
    by: str = typer.Option(..., "--by", help="Who decided (agent role or 'human')"),
    vault: Path = VaultOpt,
) -> None:
    """Record a screening decision against the protocol's criteria."""
    if include is None:
        fail("pass --include or --exclude")
    v = open_vault(vault)
    try:
        n = v.get(citekey, "paper")
    except VaultError as e:
        fail(str(e))
    n.fm.update(
        {
            "screening": "included" if include else "excluded",
            "screening_reason": reason,
            "screened_by": by,
            "screened": today(),
        }
    )
    v.save(n)
    typer.echo(f"{n.id}: {n.fm['screening']}")


# --- statements -------------------------------------------------------------
def _words(text: str) -> set[str]:
    stop = {
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "in",
        "on",
        "to",
        "is",
        "are",
        "with",
        "by",
        "for",
        "as",
        "that",
        "at",
        "be",
        "its",
        "from",
    }
    return {
        w
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in stop and len(w) > 1
    }


def similar(v: Vault, text: str, limit: int = 5) -> list[tuple[float, str, str]]:
    want = _words(text)
    out = []
    for s in v.of_type("statement"):
        have = _words(s.fm.get("text", ""))
        if want and have:
            score = len(want & have) / len(want | have)
            if score > 0:
                out.append((round(score, 2), s.id, s.fm.get("text", "")))
    return sorted(out, reverse=True)[:limit]


@statement_app.command("add")
def statement_add(
    text: str = typer.Argument(
        ..., help="One proposition, one sentence, no citation in it"
    ),
    concept: list[str] = typer.Option([], "--concept", help="Concept note id (repeat)"),
    force: bool = typer.Option(
        False, "--force", help="Create even if a near-duplicate exists"
    ),
    vault: Path = VaultOpt,
) -> None:
    """Add a statement. Refuses near-duplicates: reuse the existing one instead."""
    v = open_vault(vault)
    near = [s for s in similar(v, text) if s[0] >= 0.6]
    if near and not force:
        for score, sid, stext in near:
            info(f"  {sid} ({score}): {stext}")
        fail(
            "near-duplicate statement exists; reuse it, or pass --force if it is a different proposition"
        )
    n = v.create(
        "statement",
        {"text": text, "concepts": [link(c) for c in concept], "created": today()},
        f"\n{text}\n",
    )
    typer.echo(n.id)


@statement_app.command("find")
def statement_find(text: str, vault: Path = VaultOpt, as_json: bool = JsonOpt) -> None:
    """Statements that share words with TEXT (check before adding)."""
    v = open_vault(vault)
    hits = similar(v, text, limit=10)
    if as_json:
        emit([{"score": s, "id": i, "text": t} for s, i, t in hits])
        return
    for s, i, t in hits:
        typer.echo(f"{i}\t{s}\t{t}")


@app.command()
def trace(statement: str, vault: Path = VaultOpt, as_json: bool = JsonOpt) -> None:
    """Provenance of a statement: origins, citation hops, drift, problems."""
    v = open_vault(vault)
    try:
        t = provenance.trace(v, statement)
    except VaultError as e:
        fail(str(e))
    if as_json:
        emit(t)
        return
    typer.echo(provenance.render(t))


# --- claims -----------------------------------------------------------------
def paper_pdf(v: Vault, paper) -> Path | None:
    """The PDF to read for a paper: its OCR copy if `obs ocr` made one."""
    ocr = v.root / ".obs" / "ocr" / f"{paper.id}.pdf"
    if ocr.exists():
        return ocr
    if not paper.fm.get("pdf"):
        return None
    pdf = Path(str(paper.fm["pdf"])).expanduser()
    if not pdf.is_absolute():
        pdf = v.root / pdf
    return pdf if pdf.exists() else None


def _check_claim(v: Vault, c) -> dict:
    paper = v.notes.get((c.links("paper") or [""])[0])
    pdf = paper_pdf(v, paper) if paper else None
    if not pdf:
        return {"status": "no-pdf", "page": None, "score": 0.0}
    try:
        texts = pdftext.pages(pdf, v.root / ".obs" / "cache")
    except Exception as e:  # unreadable PDF: report, don't crash a batch
        return {"status": "no-pdf", "page": None, "score": 0.0, "reason": str(e)}
    return pdftext.find_quote(str(c.fm.get("quote", "")), texts)


def _apply_check(v: Vault, c, r: dict) -> None:
    c.fm["quote_check"] = (
        None
        if r["status"] in ("no-pdf", "no-text")
        else ("not-found" if r["status"] == "not-found" else "found")
    )
    if r["status"] in ("found", "approx"):
        c.fm["quote_page"] = r["page"]
        c.fm["quote_score"] = r["score"]
    if c.fm["quote_check"] is None:
        c.fm.pop("quote_check")
    v.save(c)


@claim_app.command("add")
def claim_add(
    paper: str = typer.Option(
        ..., "--paper", "-p", help="Citekey of the paper making the claim"
    ),
    statement: str = typer.Option(
        ..., "--statement", "-s", help="Statement id (obs statement find / add)"
    ),
    quote: str = typer.Option(
        ..., "--quote", "-q", help="Verbatim sentence(s) from the paper"
    ),
    page: str = typer.Option(
        None, "--page", help="Page the quote is on (as printed in the PDF viewer)"
    ),
    role: str = typer.Option(..., "--role", "-r", help=f"{' | '.join(ROLES)}"),
    cites: list[str] = typer.Option(
        [],
        "--cites",
        "-c",
        help="Citekey (or doi:...) the paper cites for this; repeat",
    ),
    drift: str = typer.Option(
        "none",
        "--drift",
        help=f"How the wording changed vs. what it cites: {' | '.join(DRIFT)}",
    ),
    by: str = typer.Option(..., "--by", help="Who extracted it (agent role/model)"),
    note: str = typer.Option(
        "", "--note", help="Context: conditions, site, sensor, caveats"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Keep the claim even if the quote is not found in the PDF",
    ),
    vault: Path = VaultOpt,
) -> None:
    """Record that PAPER asserts STATEMENT, with the exact quote.

    The quote is looked up in the paper's PDF; a quote that is not there is
    refused (copy the exact wording).
    """
    if err := refuse_lead("lit-reader", "Extracting claims"):
        fail(err)
    v = open_vault(vault)
    if role not in ROLES:
        fail(f"--role must be one of {', '.join(ROLES)}")
    if drift not in DRIFT:
        fail(f"--drift must be one of {', '.join(DRIFT)}")
    if role == "restates" and not cites:
        fail(
            "--role restates needs --cites (what the paper cites for it); use restates-uncited if it cites nothing"
        )
    try:
        p = v.get(paper, "paper")
        s = v.get(statement, "statement")
    except VaultError as e:
        fail(str(e))
    if p.fm.get("screening") == "excluded":
        fail(f"{p.id} is excluded by screening ({p.fm.get('screening_reason')})")
    cite_vals = [c if c.startswith("doi:") else link(c) for c in cites]
    fm = {
        "statement": link(s.id),
        "paper": link(p.id),
        "role": role,
        "quote": quote.strip(),
        "page": page,
        "cites": cite_vals,
        "drift": drift,
        "verification": "unverified",
        "extracted_by": by,
        "extracted": today(),
    }
    body = (
        f"\n> {quote.strip()}\n> — [[{p.id}]], p. {page or '?'}\n\n{note}\n"
        if note
        else f"\n> {quote.strip()}\n> — [[{p.id}]], p. {page or '?'}\n"
    )
    c = v.create("claim", fm, body)
    r = _check_claim(v, c)
    if r["status"] == "not-found" and not force:
        c.path.unlink()
        fail(
            f"quote NOT found in the PDF of {p.id} (best similarity {r['score']}); nothing saved. Copy the exact wording from `obs pdf-text {p.id}`."
        )
    if r["status"] in ("found", "approx") and not page:
        c.fm["page"] = str(r["page"])
    _apply_check(v, c, r)
    typer.echo(c.id)
    if r["status"] == "not-found":
        info(
            "warning: quote not found in the PDF, kept because of --force; lint will block it"
        )
    elif r["status"] == "no-pdf":
        info("note: no PDF on the paper note, quote not checked")
    elif r["status"] == "no-text":
        info(
            f"note: the PDF of {p.id} is a scan without text, quote not checked. Run `obs ocr {p.id}`, then `obs check-quotes {c.id}`"
        )
    elif page and str(r["page"]) != str(page):
        info(f"note: quote found on PDF page {r['page']}, you gave {page}")


@app.command("check-quotes")
def check_quotes(
    claims: list[str] = typer.Argument(None, help="Claim ids (default: all unchecked)"),
    all_: bool = typer.Option(False, "--all", help="Re-check every claim"),
    vault: Path = VaultOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Look for each claim's quote in its paper's PDF text."""
    v = open_vault(vault)
    if claims:
        try:
            todo = [v.get(c, "claim") for c in claims]
        except VaultError as e:
            fail(str(e))
    else:
        todo = [
            c for c in v.of_type("claim") if all_ or c.fm.get("quote_check") is None
        ]
    results = []
    for c in todo:
        r = _check_claim(v, c)
        _apply_check(v, c, r)
        results.append({"claim": c.id, **r})
        if not as_json:
            typer.echo(f"{c.id}\t{r['status']}\tpage {r['page']}\tscore {r['score']}")
    if as_json:
        emit(results)
    if any(r["status"] == "not-found" for r in results):
        raise typer.Exit(1)


@app.command("pdf-text")
def pdf_text(
    citekey: str,
    page: int = typer.Option(None, "--page", help="Only this page (1-based)"),
    grep: str = typer.Option(
        None,
        "--grep",
        "-g",
        help="Only lines containing this text (case-insensitive), with page numbers",
    ),
    vault: Path = VaultOpt,
) -> None:
    """The text of a paper's PDF, page by page: copy quotes from here."""
    v = open_vault(vault)
    try:
        p = v.get(citekey, "paper")
    except VaultError as e:
        fail(str(e))
    pdf = paper_pdf(v, p)
    if not pdf:
        fail(f"{p.id} has no readable PDF (pdf: {p.fm.get('pdf')})")
    texts = pdftext.pages(pdf, v.root / ".obs" / "cache")
    if not pdftext.has_text(texts):
        fail(
            f"the PDF of {p.id} is a scan without a text layer; run `obs ocr {p.id}` first"
        )
    for i, t in enumerate(texts, 1):
        if page and i != page:
            continue
        if grep:
            for line in t.splitlines():
                if grep.lower() in line.lower():
                    typer.echo(f"p{i}: {line.strip()}")
        else:
            typer.echo(f"=== page {i} ===\n{t.strip()}\n")


@app.command()
def ocr(
    citekey: str,
    lang: str = typer.Option(
        "eng", "--lang", "-l", help="Tesseract languages, e.g. deu+eng"
    ),
    vault: Path = VaultOpt,
) -> None:
    """Add a text layer to a scanned PDF (needs ocrmypdf). The original stays untouched."""
    import shutil
    import subprocess

    v = open_vault(vault)
    try:
        p = v.get(citekey, "paper")
    except VaultError as e:
        fail(str(e))
    src = Path(str(p.fm.get("pdf", ""))).expanduser()
    if not p.fm.get("pdf") or not src.exists():
        fail(f"{p.id} has no readable PDF (pdf: {p.fm.get('pdf')})")
    if not shutil.which("ocrmypdf"):
        fail(
            "ocrmypdf is not installed: brew install ocrmypdf tesseract-lang / apt install ocrmypdf tesseract-ocr-deu"
        )
    out = v.root / ".obs" / "ocr" / f"{p.id}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    info(f"OCR of {src.name} ({lang}) ...")
    r = subprocess.run(
        [
            "ocrmypdf",
            "--skip-text",
            "-l",
            lang,
            "--output-type",
            "pdf",
            str(src),
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        fail(f"ocrmypdf failed: {r.stderr.strip()[-500:]}")
    p.fm["ocr"] = f"{lang}, {today()}"
    v.save(p)
    texts = pdftext.pages(out, v.root / ".obs" / "cache")
    typer.echo(
        f"{p.id}: {len(texts)} pages, {sum(len(t) for t in texts)} characters of text"
    )


@app.command()
def verify(
    claim: str,
    verified: bool = typer.Option(
        None, "--verified/--rejected", help="Verdict after reading the source"
    ),
    by: str = typer.Option(
        ..., "--by", help="Verifier (must differ from the extractor)"
    ),
    note: str = typer.Option(
        ..., "--note", help="Why: what the source says, page, conditions"
    ),
    drift: str = typer.Option(
        None, "--drift", help=f"Correct the drift: {' | '.join(DRIFT)}"
    ),
    vault: Path = VaultOpt,
) -> None:
    """Record an independent verifier's verdict on a claim."""
    if verified is None:
        fail("pass --verified or --rejected")
    if err := refuse_lead("lit-verifier", "Verifying claims"):
        fail(err)
    v = open_vault(vault)
    try:
        c = v.get(claim, "claim")
    except VaultError as e:
        fail(str(e))
    if c.fm.get("extracted_by") and c.fm["extracted_by"] == by:
        fail(f"{by} extracted {c.id}; a different agent must verify it")
    if verified and c.fm.get("quote_check") == "not-found":
        fail("the quote was not found in the PDF; it cannot be verified as is")
    if drift:
        if drift not in DRIFT:
            fail(f"--drift must be one of {', '.join(DRIFT)}")
        c.fm["drift"] = drift
    c.fm.update(
        {
            "verification": "verified" if verified else "rejected",
            "verified_by": by,
            "verify_note": note,
            "verified": today(),
        }
    )
    v.save(c)
    typer.echo(f"{c.id}: {c.fm['verification']}")


@app.command()
def reseal(
    note_id: str,
    by: str = typer.Option(..., "--by", help="Who accepts the hand edit"),
    vault: Path = VaultOpt,
) -> None:
    """Accept a hand-edited claim, question or paper, and send it back to be checked.

    A claim loses its verification and has its quote looked up again; a
    question loses its review; a paper loses its search records.
    """
    v = open_vault(vault)
    try:
        n = v.get(note_id)
    except VaultError as e:
        fail(str(e))
    if n.type not in SEALED:
        fail(f"{n.id} is a {n.type}; only claims, questions and papers are sealed")
    if n.type == "claim":
        if n.fm.get("verification") != "unverified":
            n.fm["verification"] = "unverified"
            for f in ("verified_by", "verify_note", "verified"):
                n.fm.pop(f, None)
        _apply_check(v, n, _check_claim(v, n))
    elif n.type == "paper":
        n.fm.pop("searched", None)
    else:
        for f in ("review", "reviewed_by", "reviewed", "review_of"):
            n.fm.pop(f, None)
    n.fm["resealed_by"] = by
    n.fm["resealed"] = today()
    v.save(n)
    again = {"claim": "verified", "paper": "searched"}.get(n.type, "reviewed")
    typer.echo(f"{n.id}: resealed; it must be {again} again")


# --- maps and questions -----------------------------------------------------
@map_app.command("new")
def map_new(
    title: str = typer.Argument(..., help="Short name of the effort"),
    destination: str = typer.Option(
        ..., "--destination", "-d", help="What reaching the end looks like"
    ),
    notes: str = typer.Option(
        "", "--notes", help="Domain, standing preferences, skills to use"
    ),
    vault: Path = VaultOpt,
) -> None:
    """Start a map: a destination its questions find the way to."""
    v = open_vault(vault)
    body = (
        f"\n# {title}\n\n## Destination\n\n{destination}\n\n## Notes\n\n{notes or '_none_'}\n\n"
        "## Decisions so far\n\n_none yet_\n\n## Not yet specified\n\n_nothing yet_\n\n## Out of scope\n\n_none_\n"
    )
    n = v.create("map", {"title": title, "created": today()}, body)
    typer.echo(n.id)


@map_app.command("show")
def map_show(map_id: str, vault: Path = VaultOpt) -> None:
    """The map at low resolution: destination, tickets, frontier, fog."""
    v = open_vault(vault)
    try:
        m = v.get(map_id, "map")
    except VaultError as e:
        fail(str(e))
    wayfinder.refresh_map(v, m)
    typer.echo(wayfinder.render_map(v, m))


@map_app.command("fog")
def map_fog(
    map_id: str,
    text: str = typer.Argument(..., help="The full new 'Not yet specified' section"),
    vault: Path = VaultOpt,
) -> None:
    """Replace the map's 'Not yet specified' section (questions not sharp enough to ticket)."""
    v = open_vault(vault)
    m = v.get(map_id, "map")
    m.body = set_section(m.body, "Not yet specified", text)
    v.save(m)


@q_app.command("add")
def q_add(
    map_id: str = typer.Argument(..., help="Map id"),
    question: str = typer.Argument(
        ..., help="The question, sharp enough to answer in one session"
    ),
    kind: str = typer.Option(
        ..., "--kind", "-k", help=f"{' | '.join(Q_KINDS)} (grilling = needs the human)"
    ),
    blocked_by: list[str] = typer.Option(
        [], "--blocked-by", "-b", help="Question id that must close first; repeat"
    ),
    context: str = typer.Option(
        "", "--context", help="What the answer is for, scope, where to look"
    ),
    vault: Path = VaultOpt,
) -> None:
    """Add a question ticket to a map."""
    v = open_vault(vault)
    if kind not in Q_KINDS:
        fail(f"--kind must be one of {', '.join(Q_KINDS)}")
    try:
        m = v.get(map_id, "map")
        for b in blocked_by:
            v.get(b, "question")
    except VaultError as e:
        fail(str(e))
    fm = {
        "title": question,
        "map": link(m.id),
        "kind": kind,
        "status": "open",
        "blocked_by": [link(b) for b in blocked_by],
        "created": today(),
    }
    body = f"\n# {question}\n\n## Question\n\n{question}\n\n{context}\n\n## Answer\n\n"
    n = v.create("question", fm, body)
    typer.echo(n.id)


@q_app.command("block")
def q_block(
    question: str, blocked_by: list[str] = typer.Argument(...), vault: Path = VaultOpt
) -> None:
    """Add blocking edges after creating tickets (create first, wire second)."""
    v = open_vault(vault)
    q = v.get(question, "question")
    have = set(q.links("blocked_by"))
    for b in blocked_by:
        v.get(b, "question")
        if b != q.id:
            have.add(v.get(b).id)
    q.fm["blocked_by"] = [link(b) for b in sorted(have)]
    v.save(q)


@app.command()
def frontier(
    map_id: str = typer.Argument(None, help="Map id (default: all maps)"),
    vault: Path = VaultOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Open, unblocked, unclaimed questions: what can be worked on now."""
    v = open_vault(vault)
    try:
        qs = wayfinder.frontier(v, map_id)
    except VaultError as e:
        fail(str(e))
    if as_json:
        emit(
            [
                {
                    "id": q.id,
                    "kind": q.fm.get("kind"),
                    "needs_human": q.fm.get("kind") in HUMAN_KINDS,
                    "question": q.title,
                    "map": (q.links("map") or [None])[0],
                }
                for q in qs
            ]
        )
        return
    for q in qs:
        human = "  [needs human]" if q.fm.get("kind") in HUMAN_KINDS else ""
        typer.echo(f"{q.id}\t{q.fm.get('kind')}\t{q.title}{human}")


@q_app.command("claim")
def q_claim(
    question: str, by: str = typer.Option(..., "--by"), vault: Path = VaultOpt
) -> None:
    """Take a frontier ticket before working on it."""
    v = open_vault(vault)
    q = v.get(question, "question")
    if q.fm.get("status", "open") != "open":
        fail(f"{q.id} is {q.fm.get('status')}, not open")
    if wayfinder.blockers_open(v, q):
        fail(f"{q.id} is blocked by {', '.join(wayfinder.blockers_open(v, q))}")
    q.fm.update({"status": "claimed", "claimed_by": by})
    v.save(q)
    typer.echo(f"{q.id}: claimed by {by}")


@q_app.command("release")
def q_release(question: str, vault: Path = VaultOpt) -> None:
    """Give a claimed ticket back to the frontier."""
    v = open_vault(vault)
    q = v.get(question, "question")
    q.fm["status"] = "open"
    q.fm.pop("claimed_by", None)
    v.save(q)


@q_app.command("answer")
def q_answer(
    question: str,
    gist: str = typer.Option(
        ..., "--gist", help="One line for the map's Decisions so far"
    ),
    text: str = typer.Option(None, "--text", help="Full answer (or --file)"),
    file: Path = typer.Option(None, "--file", help="Read the full answer from a file"),
    claims: list[str] = typer.Option(
        [], "--claim", help="Claim id the answer rests on; repeat"
    ),
    statements: list[str] = typer.Option(
        [], "--statement", help="Statement id the answer rests on; repeat"
    ),
    human_said: str = typer.Option(
        None, "--human-said", help="Grilling only: the user's answer, verbatim"
    ),
    by: str = typer.Option(..., "--by"),
    vault: Path = VaultOpt,
) -> None:
    """Close a ticket with its answer and the evidence it rests on."""
    v = open_vault(vault)
    q = v.get(question, "question")
    kind = q.fm.get("kind")
    if kind in HUMAN_KINDS and not human_said:
        fail(
            "this is a grilling question: only the user answers it. Ask them, then pass their words with --human-said"
        )
    full = file.read_text(encoding="utf-8") if file else (text or "")
    if kind in ("research", "query", "falsify") and not (claims or statements):
        fail(
            f"a {kind} answer must cite the claims or statements it rests on (--claim / --statement)"
        )
    try:
        for c in claims:
            v.get(c, "claim")
        for s in statements:
            v.get(s, "statement")
    except VaultError as e:
        fail(str(e))
    answer = full.strip()
    if human_said:
        answer = f"> [!quote] The user said\n> {human_said.strip()}\n\n{answer}".strip()
    q.body = set_section(q.body, "Answer", answer or gist)
    q.fm.update(
        {
            "status": "answered",
            "gist": gist,
            "answered_by": "human" if human_said else by,
            "recorded_by": by,
            "answered": today(),
            "claims": [link(c) for c in claims],
            "statements": [link(s) for s in statements],
        }
    )
    q.fm.pop("claimed_by", None)
    v.save(q)
    for m in q.links("map"):
        if m in v.notes:
            wayfinder.refresh_map(v, v.notes[m])
    typer.echo(f"{q.id}: answered")
    unblocked = [o.id for o in wayfinder.frontier(v) if q.id in o.links("blocked_by")]
    if unblocked:
        info(f"now on the frontier: {', '.join(unblocked)}")


@q_app.command("drop")
def q_drop(
    question: str,
    reason: str = typer.Option(
        ..., "--reason", help="Why it lies beyond the destination"
    ),
    vault: Path = VaultOpt,
) -> None:
    """Rule a ticket out of scope."""
    v = open_vault(vault)
    q = v.get(question, "question")
    q.fm.update({"status": "out-of-scope", "reason": reason})
    v.save(q)
    for m in q.links("map"):
        if m in v.notes:
            wayfinder.refresh_map(v, v.notes[m])
    typer.echo(f"{q.id}: out of scope")


# --- glossary and decisions -------------------------------------------------
@term_app.command("add")
def term_add(
    name: str,
    definition: str = typer.Option(
        ..., "--definition", "-d", help="What the term means in THIS project"
    ),
    alias: list[str] = typer.Option(
        [],
        "--alias",
        help="Synonyms and spellings used in papers (also search terms); repeat",
    ),
    not_: list[str] = typer.Option(
        [], "--not", help="Terms it must not be confused with; repeat"
    ),
    claim: list[str] = typer.Option(
        [], "--claim", help="Claim that defines it; repeat"
    ),
    vault: Path = VaultOpt,
) -> None:
    """Add a glossary term as a concept note (aliases show up in Obsidian)."""
    v = open_vault(vault)
    body = f"\n# {name}\n\n{definition}\n"
    if not_:
        body += (
            "\n## Not to be confused with\n\n"
            + "\n".join(f"- {t}" for t in not_)
            + "\n"
        )
    n = v.create(
        "concept",
        {
            "title": name,
            "aliases": alias,
            "definition": definition,
            "claims": [link(c) for c in claim],
        },
        body,
        note_id=slugify(name),
    )
    typer.echo(n.id)


@app.command()
def glossary(vault: Path = VaultOpt, as_json: bool = JsonOpt) -> None:
    """All terms with their definitions and aliases."""
    v = open_vault(vault)
    terms = sorted(v.of_type("concept"), key=lambda n: n.title.lower())
    if as_json:
        emit(
            [
                {
                    "id": t.id,
                    "term": t.title,
                    "definition": t.fm.get("definition"),
                    "aliases": t.fm.get("aliases", []),
                }
                for t in terms
            ]
        )
        return
    for t in terms:
        aka = (
            f" (aka {', '.join(t.fm.get('aliases', []))})"
            if t.fm.get("aliases")
            else ""
        )
        typer.echo(f"{t.title}{aka}: {t.fm.get('definition', '')}")


@app.command()
def decision(
    title: str,
    decision_: str = typer.Option(..., "--decision", help="What was decided"),
    context: str = typer.Option(..., "--context", help="Why it came up"),
    alternatives: str = typer.Option(
        ..., "--alternatives", help="What else was considered, and why not"
    ),
    by: str = typer.Option(..., "--by", help="'human' for the user's decisions"),
    vault: Path = VaultOpt,
) -> None:
    """Record a hard-to-reverse method decision (e.g. 'exclude preprints')."""
    v = open_vault(vault)
    body = f"\n# {title}\n\n## Context\n\n{context}\n\n## Decision\n\n{decision_}\n\n## Alternatives\n\n{alternatives}\n"
    n = v.create("decision", {"title": title, "decided_by": by, "date": today()}, body)
    typer.echo(n.id)


# --- reading the vault -------------------------------------------------------
@app.command("ls")
def ls(
    type_: str = typer.Argument("all", help=f"{' | '.join(TYPES)} | all"),
    filters: list[str] = typer.Argument(
        None, help="field=value, field!=value, field~text, year>2020"
    ),
    fields: str = typer.Option(
        "", "--fields", "-f", help="Comma-separated frontmatter fields to show"
    ),
    vault: Path = VaultOpt,
    as_json: bool = JsonOpt,
) -> None:
    """List notes, filtered on frontmatter. Example: obs ls claim verification=unverified"""
    v = open_vault(vault)
    if type_ not in (*TYPES, "all"):
        fail(f"type must be one of {', '.join(TYPES)}, all")
    try:
        notes = query.select(v, type_, filters or [])
    except VaultError as e:
        fail(str(e))
    cols = [f for f in fields.split(",") if f]
    if as_json:
        emit(
            [
                {
                    "id": n.id,
                    "type": n.type,
                    **({c: n.fm.get(c) for c in cols} if cols else n.fm),
                }
                for n in notes
            ]
        )
        return
    for n in notes:
        extra = "\t".join(str(n.fm.get(c, "")) for c in cols)
        typer.echo(
            f"{n.id}\t{n.type}\t{n.title[:100]}" + (f"\t{extra}" if extra else "")
        )


@app.command()
def show(
    note_ids: list[str] = typer.Argument(..., metavar="NOTE_ID..."),
    vault: Path = VaultOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Notes with their frontmatter, body and backlinks; several ids in one call."""
    v = open_vault(vault)
    try:
        notes = [v.get(i) for i in note_ids]
    except VaultError as e:
        fail(str(e))
    shown = []
    for n in notes:
        back = [(b.id, b.type, f) for b, f in v.backlinks(n.id)]
        shown.append(
            {
                "id": n.id,
                "type": n.type,
                "path": str(n.path),
                "fm": n.fm,
                "body": n.body,
                "backlinks": [{"id": i, "type": t, "field": f} for i, t, f in back],
            }
        )
    if as_json:
        emit(shown[0] if len(shown) == 1 else shown)
        return
    for n, d in zip(notes, shown, strict=True):
        if len(notes) > 1:
            typer.echo(f"=== {n.id}")
        typer.echo(n.path.read_text(encoding="utf-8"))
        if d["backlinks"]:
            typer.echo("backlinks:")
            for b in d["backlinks"]:
                typer.echo(f"  {b['id']} ({b['type']}, via {b['field']})")


@app.command()
def neighbors(
    note_id: str,
    depth: int = typer.Option(1, "--depth", "-d"),
    vault: Path = VaultOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Notes linked to or from NOTE_ID, up to DEPTH hops."""
    v = open_vault(vault)
    try:
        edges = query.neighbors(v, note_id, depth)
    except VaultError as e:
        fail(str(e))
    if as_json:
        emit(
            {
                k: [{"dir": d, "field": f, "note": o} for d, f, o in e]
                for k, e in edges.items()
            }
        )
        return
    for nid, es in edges.items():
        for d, f, o in es:
            other = v.notes.get(o)
            typer.echo(
                f"{nid} {d} {o}\t({f})\t{other.title[:80] if other else 'MISSING'}"
            )


@app.command("sql")
def sql_cmd(statement: str, vault: Path = VaultOpt, as_json: bool = JsonOpt) -> None:
    """Read-only SQL over tables notes(id,type,title,status,path,body,fm) and links(src,field,dst).

    fm is JSON: json_extract(fm,'$.year'). Example:
    obs sql "select n.id, n.title from notes n join links l on l.dst=n.id where l.field='cites'"
    """
    v = open_vault(vault)
    try:
        cols, rows = query.sql(v, statement)
    except (VaultError, Exception) as e:
        fail(str(e))
    if as_json:
        emit([dict(zip(cols, r, strict=False)) for r in rows])
        return
    typer.echo("\t".join(cols))
    for r in rows:
        typer.echo("\t".join("" if x is None else str(x) for x in r))


if __name__ == "__main__":
    sys.exit(app())
