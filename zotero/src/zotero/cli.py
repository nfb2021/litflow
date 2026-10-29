"""
`zot` - command-line interface for Zotero, through the Zotero MCP plugin

    zot status
    zot collections [-q TEXT]
    zot search QUERY
    zot add DOI... [-f FILE|-] [-c COLLECTION]     import with PDFs
    zot pdfs -c COLLECTION [--missing]             PDF paths (or items without one)
    zot refs DOI|KEY... [-c COLLECTION]            DOIs of cited references
    zot push -c COLLECTION -n NOTEBOOK             PDFs -> Gemini Notebook (gnb add)

Lists go to stdout (one per line, ready for pipes), progress and summaries to stderr.
"""

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer

from . import __version__
from .client import (
    WRITE_HINT,
    ZoteroError,
    ZoteroMCP,
    collection_items,
    collection_path,
    find_collection,
    pdf_paths,
)

app = typer.Typer(
    help="Import DOIs into Zotero with their PDFs, list PDFs, extract cited references.",
    no_args_is_help=True,
    add_completion=False,
)

ITEM_KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
WRITE_TOOLS = {"add_by_identifier", "create_collection"}
# Gemini Notebook's per-notebook source limit on the free plan
NOTEBOOK_SOURCE_LIMIT = 50
COLLECTION_HELP = "Collection name, path or 8-character key"


def info(message: str = ""):
    """Progress and summaries go to stderr, so stdout stays pipeable"""
    typer.echo(message, err=True)


def _connect() -> ZoteroMCP:
    try:
        return ZoteroMCP().connect()
    except ZoteroError as e:
        info(f"❌ {e}")
        raise typer.Exit(1) from e


def _collection(zot: ZoteroMCP, name_or_key: str, create: bool = False) -> dict:
    """Collection by name/path/key; created when missing and create=True (with its
    parents for 'Parent/Child'); exits otherwise"""
    found = find_collection(zot, name_or_key)
    if found:
        return found
    if not create:
        info(f"❌ Collection '{name_or_key}' not found. See: zot collections")
        raise typer.Exit(1)
    parent, _, name = name_or_key.strip().rpartition("/")
    parent_key = _collection(zot, parent, create=True)["key"] if parent else None
    created = zot.call("create_collection", name=name, parentCollection=parent_key)
    info(f"📁 Created collection '{name_or_key}' ({created['key']})")
    return created


def _read_identifiers(args: list[str], file: Path | None) -> list[str]:
    """Identifiers from arguments and a file ('-' = stdin); '#' starts a comment"""
    lines = list(args)
    if file:
        text = sys.stdin.read() if str(file) == "-" else file.expanduser().read_text()
        lines += text.splitlines()
    ids: dict[str, None] = {}
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line:
            ids.setdefault(line, None)
    return list(ids)


def _fail(e: ZoteroError):
    info(f"❌ {e}")
    raise typer.Exit(1) from e


def _version(value: bool):
    if value:
        typer.echo(f"zot {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version"
    ),
):
    pass


@app.command()
def status():
    """Check that Zotero and the MCP plugin answer, and whether writing is allowed."""
    zot = _connect()
    tools = set(zot.tools())
    server = zot.server_info
    typer.echo(f"✅ Zotero MCP plugin at {zot.url}")
    typer.echo(f"   server: {server.get('name', '?')} {server.get('version', '')}")
    typer.echo(f"   tools:  {len(tools)}")
    try:
        total = zot.call("search_library", limit=1)["pagination"]["total"]
        typer.echo(f"   items:  {total}")
    except (ZoteroError, KeyError, TypeError):
        pass
    if WRITE_TOOLS <= tools:
        typer.echo("✅ Write operations enabled (zot add works)")
    else:
        typer.echo(f"⚠️  Write operations disabled: zot add will fail. {WRITE_HINT}")
        raise typer.Exit(2)


@app.command()
def collections(
    query: str | None = typer.Option(None, "--query", "-q", help="Filter by name"),
):
    """List collections with their keys."""
    zot = _connect()
    try:
        rows = zot.call("get_collections", recursive=True, limit=1000) or []
    except ZoteroError as e:
        _fail(e)
    for c in rows:
        path = collection_path(c)
        if query and query.casefold() not in path.casefold():
            continue
        typer.echo(f"{c['key']}  {path}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Words to search for (title, creators, …)"),
    limit: int = typer.Option(20, "--limit", "-l"),
    fulltext: bool = typer.Option(
        False, "--fulltext", help="Search the PDFs' full text instead"
    ),
):
    """Search the library. Prints KEY  YEAR  [PDF]  TITLE."""
    zot = _connect()
    args = {"fulltext": query} if fulltext else {"q": query}
    try:
        found = zot.call("search_library", limit=limit, **args)
    except ZoteroError as e:
        _fail(e)
    for r in found.get("results", []):
        has_pdf = any(
            a.get("contentType") == "application/pdf"
            for a in r.get("attachments") or []
        )
        year = (r.get("date") or "")[:4] or "    "
        typer.echo(f"{r['key']}  {year}  {'PDF' if has_pdf else '   '}  {r['title']}")
    total = found.get("pagination", {}).get("total")
    if total is not None:
        info(f"{total} match(es)")


def _run_import(zot: ZoteroMCP, ids: list[str], **opts) -> list[dict]:
    """add_by_identifier in chunks of 200, polling background jobs; returns results"""
    results = []
    for start in range(0, len(ids), 200):
        chunk = ids[start : start + 200]
        reply = zot.call("add_by_identifier", identifiers=chunk, **opts)["data"]
        while reply.get("state") == "running":
            info(f"   … {reply.get('done', 0)}/{reply['total']} done")
            time.sleep(3)
            reply = zot.call("add_by_identifier", jobID=reply["jobID"])["data"]
        results.extend(reply.get("results", []))
    return results


@app.command()
def add(
    identifiers: list[str] = typer.Argument(
        None, help="DOIs (also arXiv:…, ISBN, PMID); or use --file"
    ),
    file: Path | None = typer.Option(
        None, "--file", "-f", help="File with one identifier per line ('-' = stdin)"
    ),
    collection: str | None = typer.Option(
        None, "--collection", "-c", help=COLLECTION_HELP + " (created if missing)"
    ),
    no_pdf: bool = typer.Option(False, "--no-pdf", help="Metadata only, no PDFs"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Only show how each identifier is parsed"
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the results as JSON"),
):
    """Import items by DOI with Zotero's own resolvers and fetch their PDFs.

    Identifiers already in the library are not imported again; with -c they are
    filed into the collection too. Prints one line per identifier and lists the
    items that came without a PDF.
    """
    ids = _read_identifiers(identifiers or [], file)
    if not ids:
        raise typer.BadParameter("give identifiers as arguments or with --file")

    zot = _connect()
    try:
        target = (
            _collection(zot, collection, create=not dry_run) if collection else None
        )
        info(f"📥 Importing {len(ids)} identifier(s)…")
        results = _run_import(
            zot,
            ids,
            collectionKey=target["key"] if target else None,
            saveAttachments=not no_pdf,
            fileExisting=bool(target),
            dryRun=dry_run,
        )
        # Attach the local PDF paths (the PDF download finishes during the import)
        for row in results:
            key = (row.get("item") or {}).get("itemKey")
            if key and not dry_run:
                details = zot.call("get_item_details", itemKey=key)
                row["pdfs"] = pdf_paths(details) if isinstance(details, dict) else []
    except ZoteroError as e:
        _fail(e)

    if as_json:
        typer.echo(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for row in results:
            item = row.get("item") or {}
            pdf = "" if dry_run else ("PDF   " if row.get("pdfs") else "no PDF")
            what = item.get("title") or row.get("identifier") or row.get("error", "")
            typer.echo(f"{row['status']:<18} {pdf:<6}  {row['input']}  {what}")

    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    info("\n" + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    if dry_run:
        return
    missing = [r for r in results if r.get("item") and not r.get("pdfs")]
    if missing and not no_pdf:
        info(
            f"⚠️  {len(missing)} item(s) without PDF (no open-access copy found; "
            "try the university network/VPN or add the PDF by hand)"
        )
    if counts.get("error"):
        raise typer.Exit(1)


def _items(zot: ZoteroMCP, keys: list[str], collection: str | None) -> list[dict]:
    """Items from a collection and/or item keys"""
    items = (
        collection_items(zot, _collection(zot, collection)["key"]) if collection else []
    )
    for key in keys:
        details = zot.call("get_item_details", itemKey=key)
        if isinstance(details, dict) and details.get("key"):
            items.append(details)
        else:
            info(f"⚠️  Item {key} not found")
    return items


@app.command()
def pdfs(
    keys: list[str] = typer.Argument(None, help="Item keys (or use -c)"),
    collection: str | None = typer.Option(
        None, "--collection", "-c", help=COLLECTION_HELP
    ),
    missing: bool = typer.Option(
        False, "--missing", help="List the items WITHOUT a PDF instead (DOI  title)"
    ),
    null: bool = typer.Option(
        False, "-0", "--null", help="Separate paths with NUL (for xargs -0)"
    ),
):
    """Print the local PDF paths of a collection's items, one per line."""
    if not (keys or collection):
        raise typer.BadParameter("give item keys or --collection")
    zot = _connect()
    try:
        items = _items(zot, keys or [], collection)
    except ZoteroError as e:
        _fail(e)

    with_pdf = 0
    for item in items:
        paths = pdf_paths(item)
        with_pdf += bool(paths)
        if missing:
            if not paths:
                typer.echo(f"{item.get('DOI') or item['key']}  {item.get('title', '')}")
            continue
        for path in paths[:1]:  # main PDF only
            typer.echo(path, nl=not null)
            if null:
                typer.echo("\0", nl=False)
    info(f"{with_pdf}/{len(items)} item(s) with a PDF")


@app.command()
def refs(
    inputs: list[str] = typer.Argument(None, help="DOIs or item keys (or use -c)"),
    collection: str | None = typer.Option(
        None, "--collection", "-c", help=COLLECTION_HELP
    ),
    source: str = typer.Option(
        "auto",
        help="crossref, pdf, or auto (Crossref first, PDF text when Crossref has none)",
    ),
    min_cited: int = typer.Option(
        1, "--min-cited", "-m", help="Only DOIs cited by at least this many papers"
    ),
    counts: bool = typer.Option(
        False, "--counts", help="Prefix each DOI with how many papers cite it"
    ),
):
    """Print the DOIs of the references cited by papers, one per line.

    Most-cited first. Papers already given as input are left out. Feed the DOIs
    back in for the next round:  zot refs -c X -m 3 | zot add -f - -c X-refs
    """
    from .refs import crossref_references, normalize_doi, pdf_references

    if source not in ("auto", "crossref", "pdf"):
        raise typer.BadParameter("source must be auto, crossref or pdf")
    if not (inputs or collection):
        raise typer.BadParameter("give DOIs, item keys or --collection")

    zot = _connect()
    try:
        # (label, DOI, item key) per paper
        papers = []
        keys = [i for i in inputs or [] if ITEM_KEY_RE.match(i)]
        for item in _items(zot, keys, collection):
            papers.append((item["key"], item.get("DOI", ""), item["key"]))
        for i in inputs or []:
            if not ITEM_KEY_RE.match(i):
                papers.append((i, i, None))

        cited: dict[str, int] = {}
        for label, doi, key in papers:
            found, total = [], 0
            if doi and source in ("auto", "crossref"):
                found, total = crossref_references(doi)
                how = f"Crossref ({len(found)}/{total} with DOI)"
            if not found and key and source in ("auto", "pdf"):
                found = pdf_references(zot, key, doi)
                how = f"PDF text ({len(found)} DOIs)"
            if not found:
                how = "no references found"
            info(f"   {label}: {how}")
            for d in found:
                cited[d] = cited.get(d, 0) + 1
    except ZoteroError as e:
        _fail(e)

    own = {normalize_doi(doi) for _, doi, _ in papers if doi}
    new = sorted(
        (d for d, n in cited.items() if d not in own and n >= min_cited),
        key=lambda d: -cited[d],
    )
    for d in new:
        typer.echo(f"{cited[d]}\t{d}" if counts else d)
    info(f"{len(new)} cited DOI(s) from {len(papers)} paper(s)")


@app.command()
def push(
    collection: str = typer.Option(..., "--collection", "-c", help=COLLECTION_HELP),
    notebook: str = typer.Option(
        ..., "--notebook", "-n", help="Gemini Notebook: gnb library ID or URL"
    ),
    batch: int = typer.Option(10, help="PDFs per gnb add call"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would run"),
):
    """Upload a collection's PDFs to a Gemini Notebook (runs `gnb add -f …`)."""
    gnb = shutil.which("gnb")
    if not gnb and not dry_run:
        info("❌ gnb not found. Install the gemini_notebook skill: see its README")
        raise typer.Exit(1)
    zot = _connect()
    try:
        items = collection_items(zot, _collection(zot, collection)["key"])
    except ZoteroError as e:
        _fail(e)
    paths = [p[0] for p in map(pdf_paths, items) if p]
    info(f"📄 {len(paths)}/{len(items)} item(s) have a PDF")
    if len(paths) > NOTEBOOK_SOURCE_LIMIT:
        info(
            f"⚠️  More than {NOTEBOOK_SOURCE_LIMIT} PDFs: the free plan stops at "
            f"{NOTEBOOK_SOURCE_LIMIT} sources per notebook (Pro allows more)"
        )
    for start in range(0, len(paths), batch):
        chunk = paths[start : start + batch]
        command = [gnb or "gnb", "add", "-n", notebook]
        for path in chunk:
            command += ["-f", path]
        info(f"\n▶ gnb add: PDFs {start + 1}-{start + len(chunk)} of {len(paths)}")
        if dry_run:
            for path in chunk:
                info(f"   {Path(path).name}")
            continue
        if subprocess.run(command).returncode != 0:
            info(
                "❌ gnb add failed; fix the problem and rerun (sources already added stay)"
            )
            raise typer.Exit(1)
