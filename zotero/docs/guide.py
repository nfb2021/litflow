import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Zotero skill guide")


@app.cell(hide_code=True)
def _():
    import subprocess
    import sys

    import marimo as mo

    from zotero.client import (
        ZoteroError,
        ZoteroMCP,
        collection_items,
        collection_path,
        pdf_paths,
    )

    def run_zot(*args, timeout=600):
        """Run `zot ARGS` with this environment's package and return (exit code, output)"""
        result = subprocess.run(
            [sys.executable, "-m", "zotero", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, (result.stdout + result.stderr).strip()

    def show_output(code, output):
        kind = "success" if code == 0 else ("warn" if code == 2 else "danger")
        return mo.callout(mo.md(f"```text\n{output}\n```"), kind=kind)

    return (
        ZoteroError,
        ZoteroMCP,
        collection_items,
        collection_path,
        mo,
        pdf_paths,
        run_zot,
        show_output,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Zotero skill: an interactive guide

    This skill lets **Claude Code** work with your **Zotero** library through the `zot`
    command. It can

    1. **import papers by DOI** (or arXiv / ISBN / PMID), with Zotero fetching the PDFs,
    2. **list the PDFs** of a collection, or the items that are still missing one,
    3. **extract the DOIs those papers cite**, for the next round of reading,
    4. **upload a collection's PDFs to a Gemini Notebook** (via the `gemini_notebook` skill).

    ```text
    DOIs ──zot add──▶ Zotero (+PDFs) ──zot push──▶ Gemini Notebook ──gnb ask──▶ answers
      ▲                    │
      └─────zot refs───────┘
    ```

    `zot` drives your running Zotero through the
    [Zotero MCP plugin](https://github.com/cookjohn/zotero-mcp), so items and PDFs are
    exactly what Zotero's own *Add Item by Identifier* button would produce.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Is everything set up?

    `zot status` checks that Zotero runs, the plugin answers on port 23120, and whether
    **write operations** are on (needed for `zot add`; reading works without them).
    """)
    return


@app.cell(hide_code=True)
def _(run_zot, show_output):
    status_code, status_output = run_zot("status")
    show_output(status_code, status_output)
    return (status_code,)


@app.cell(hide_code=True)
def _(mo, status_code):
    _help = {
        0: "All good.",
        2: "Reading works. For `zot add`, tick **Enable Write Operations** in "
        "Zotero → Settings → Zotero MCP Plugin.",
    }.get(
        status_code,
        "Start Zotero. If it is running, install the plugin: download the `.xpi` from "
        "the [plugin releases](https://github.com/cookjohn/zotero-mcp/releases), then "
        "Zotero → Tools → Add-ons → ⚙ → *Install Add-on From File…* and restart Zotero.",
    )
    mo.md(_help)
    return


@app.cell(hide_code=True)
def _(ZoteroError, ZoteroMCP, collection_path, mo, status_code):
    zot = None
    collections = []
    if status_code in (0, 2):
        try:
            zot = ZoteroMCP().connect()
            collections = zot.call("get_collections", recursive=True, limit=1000) or []
        except ZoteroError:
            zot = None
    picker = mo.ui.dropdown(
        {collection_path(c): c["key"] for c in collections},
        label="Collection",
    )
    mo.vstack(
        [
            mo.md(r"""
    ## 2. A collection's PDFs

    Pick a collection. `zot pdfs -c NAME` prints these paths, one per line, and
    `zot pdfs -c NAME --missing` the items without a PDF.
    """),
            picker if collections else mo.md("*(needs a running Zotero)*"),
        ]
    )
    return picker, zot


@app.cell(hide_code=True)
def _(collection_items, mo, pdf_paths, picker, zot):
    items = collection_items(zot, picker.value) if zot and picker.value else []
    rows = [
        {
            "key": i["key"],
            "year": (i.get("date") or "")[:4],
            "title": i.get("title", ""),
            "DOI": i.get("DOI", ""),
            "PDF": "yes" if pdf_paths(i) else "no",
        }
        for i in items
    ]
    mo.ui.table(rows, selection=None) if rows else mo.md("")
    return (rows,)


@app.cell(hide_code=True)
def _(mo, rows):
    find_refs = mo.ui.run_button(label="Find cited references (asks Crossref)")
    min_cited = mo.ui.slider(1, 10, value=2, label="cited by at least", show_value=True)
    mo.vstack(
        [
            mo.md(r"""
    ## 3. What do these papers cite?

    `zot refs -c NAME -m N` collects the reference lists (from Crossref, or from the PDF
    text when Crossref has none) and prints the DOIs cited by at least *N* papers,
    most-cited first. Pipe them into `zot add` for the next round:

    ```bash
    zot refs -c NAME -m 2 | zot add -f - -c "NAME/round 2"
    ```
    """),
            mo.hstack([min_cited, find_refs], justify="start") if rows else mo.md(""),
        ]
    )
    return find_refs, min_cited


@app.cell(hide_code=True)
def _(find_refs, min_cited, mo, picker, run_zot):
    mo.stop(not find_refs.value)
    _code, _out = run_zot(
        "refs", "-c", picker.value, "-m", str(min_cited.value), "--counts"
    )
    mo.md(f"```text\n{_out}\n```")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Into a Gemini Notebook

    ```bash
    zot push -c NAME -n NOTEBOOK --dry-run   # what would be uploaded
    zot push -c NAME -n NOTEBOOK             # gnb add -f …, 10 PDFs per call
    gnb ask "Which methods do these papers compare?" -n NOTEBOOK
    ```

    A notebook holds about 50 sources on the free plan; `zot push` warns above that.

    ## Asking Claude

    With the skill installed (`ln -s ~/src/litflow/zotero ~/.claude/skills/zotero`), just say
    *"add these DOIs to my Zotero collection X"*, *"which papers in X have no PDF?"*,
    or *"what do the papers in X cite most often? Import the top ones."*
    """)
    return


if __name__ == "__main__":
    app.run()
