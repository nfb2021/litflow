import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Gemini Notebook skill guide")


@app.cell(hide_code=True)
def _():
    import json
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    import marimo as mo

    from gemini_notebook import config
    from gemini_notebook.ask import FOLLOW_UP_REMINDER, PLACEHOLDER_RE, clean_answer

    LIBRARY_FILE = config.LIBRARY_FILE

    def run_gnb(*args, timeout=900):
        """Run `gnb ARGS` with this environment's package and return (exit code, output)"""
        result = subprocess.run(
            [sys.executable, "-m", "gemini_notebook", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, (result.stdout + result.stderr).strip()

    def show_output(code, output):
        kind = "success" if code == 0 else "danger"
        return mo.callout(mo.md(f"```text\n{output}\n```"), kind=kind)

    return (
        FOLLOW_UP_REMINDER,
        LIBRARY_FILE,
        PLACEHOLDER_RE,
        Path,
        clean_answer,
        config,
        json,
        mo,
        run_gnb,
        show_output,
        shutil,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Gemini Notebook skill: an interactive guide

    This skill lets **Claude Code** use your **Google Gemini Notebook** notebooks
    (formerly NotebookLM, now at `notebook.google.com`). It can

    1. **ask questions** and return answers drawn only from a notebook's sources, with citations,
    2. **add sources** (files, websites / YouTube, pasted text),
    3. **keep a library** of notebooks so Claude picks the right one per topic.

    Gemini Notebook has no public API, so the skill drives a real **Google Chrome** with
    your login. All of it is one command, `gnb`. This notebook walks through how that
    works, and every section with a button runs the real `gnb`.

    > Open it with `uv run --group docs marimo edit docs/guide.py` from the skill folder.
    > Nothing runs against Google until you press a button.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## How it fits together
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.mermaid(
        """
        flowchart LR
            U[You] <-->|plain words| C[Claude Code]
            C -.->|reads| S[SKILL.md]
            C <-->|"gnb ask / add / …"| P[gnb<br/>uv tool]
            P <-->|patchright| B[Google Chrome<br/>headless, your login]
            B <--> G[(Gemini Notebook)]
            P <--> D[(user data folder<br/>login + library)]
        """
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    | Command | Module | Job |
    |---|---|---|
    | `gnb auth …` | `auth.py` | one-time Google login in a visible Chrome; saves cookies to `browser_state/` |
    | `gnb library …` | `library.py` | the library in `library.json` (names, topics, URLs, active notebook) |
    | `gnb ask` | `ask.py` | opens the notebook, types the question, waits for the answer, cleans it up |
    | `gnb add` | `sources.py` | opens the *Add sources* dialog, uploads files / URLs / text, waits for processing |
    | `gnb cleanup` | `cleanup.py` | deletes browser state (and optionally the library) |
    | | `config.py`, `browser.py` | page selectors, data paths and the shared Chrome setup |

    The modules live in `src/gemini_notebook/`; `cli.py` turns them into `gnb` (Typer).

    Every question or upload starts a **fresh** headless Chrome, so there is no memory
    between calls. Claude compensates by putting full context into each question.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1 · Setup check
    """)
    return


@app.cell(hide_code=True)
def _(Path, mo, shutil):
    _chrome = (
        Path("/Applications/Google Chrome.app").exists()
        or shutil.which("google-chrome") is not None
        or shutil.which("google-chrome-stable") is not None
    )
    _uv = shutil.which("uv") is not None
    _gnb = shutil.which("gnb") is not None
    mo.hstack(
        [
            mo.stat(value="found" if _uv else "missing", label="uv", bordered=True),
            mo.stat(
                value="installed" if _gnb else "not on PATH",
                label="gnb",
                caption=None if _gnb else "uv tool install --editable .",
                bordered=True,
            ),
            mo.stat(
                value="found" if _chrome else "missing",
                label="Google Chrome",
                bordered=True,
            ),
        ],
        justify="start",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    status_btn = mo.ui.run_button(label="Check Google login")
    mo.vstack(
        [
            mo.md(
                "The login is a Chrome profile plus a cookie file. It expires after a few "
                "weeks; then run `gnb auth reauth` in a terminal "
                "(it needs a visible browser, so it is not a button here)."
            ),
            status_btn,
        ]
    )
    return (status_btn,)


@app.cell(hide_code=True)
def _(mo, run_gnb, show_output, status_btn):
    mo.stop(not status_btn.value)
    show_output(*run_gnb("auth", "status", timeout=60))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2 · Your notebook library

    Claude does not guess which notebook to use: it looks it up here. Add notebooks by
    telling Claude *"add this notebook to my library: <URL>"*. It then asks the notebook
    what it covers and stores a name, description and topics.
    """)
    return


@app.cell(hide_code=True)
def _(LIBRARY_FILE, json, mo):
    if LIBRARY_FILE.exists():
        _lib = json.loads(LIBRARY_FILE.read_text())
        notebooks = list(_lib.get("notebooks", {}).values())
        active_id = _lib.get("active_notebook_id")
    else:
        notebooks, active_id = [], None

    if notebooks:
        _rows = [
            {
                "active": "★" if nb["id"] == active_id else "",
                "id": nb["id"],
                "name": nb["name"],
                "topics": ", ".join(nb.get("topics", [])),
                "questions asked": nb.get("use_count", 0),
            }
            for nb in notebooks
        ]
        _view = mo.ui.table(_rows, selection=None)
    else:
        _view = mo.callout(
            mo.md(
                "No library yet: `gnb library add URL --name … --description … --topics …`"
            ),
            kind="warn",
        )
    _view
    return (notebooks,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3 · Ask a question

    This is what Claude runs when you ask about a notebook (`gnb ask "…" -n ID`). Behind the button:
    open the notebook → close any popup → remember the last answer on screen →
    type the question → wait until a **new** answer is stable for 3 seconds →
    clean it up (see section 5).
    """)
    return


@app.cell(hide_code=True)
def _(mo, notebooks):
    _options = {f"{nb['name']} ({nb['id']})": nb["url"] for nb in notebooks}
    ask_nb = mo.ui.dropdown(
        options=_options,
        value=next(iter(_options), None),
        label="Notebook from library",
    )
    ask_url = mo.ui.text(
        placeholder="https://notebook.google.com/notebook/…",
        label="…or a notebook URL",
        full_width=True,
    )
    ask_q = mo.ui.text_area(
        placeholder="What are the main findings of these sources?",
        label="Question",
        full_width=True,
    )
    ask_timeout = mo.ui.slider(
        60, 600, step=30, value=240, label="Timeout (s)", show_value=True
    )
    ask_show = mo.ui.checkbox(label="Show browser")
    ask_btn = mo.ui.run_button(label="Ask")
    mo.vstack(
        [
            ask_nb,
            ask_url,
            ask_q,
            mo.hstack([ask_timeout, ask_show], justify="start"),
            ask_btn,
        ]
    )
    return ask_btn, ask_nb, ask_q, ask_show, ask_timeout, ask_url


@app.cell(hide_code=True)
def _(
    FOLLOW_UP_REMINDER,
    ask_btn,
    ask_nb,
    ask_q,
    ask_show,
    ask_timeout,
    ask_url,
    mo,
    run_gnb,
):
    mo.stop(not ask_btn.value)
    _url = ask_url.value.strip() or ask_nb.value
    mo.stop(not _url, mo.callout("Pick a notebook or paste a URL.", kind="warn"))
    mo.stop(not ask_q.value.strip(), mo.callout("Type a question first.", kind="warn"))

    _args = [
        "ask",
        ask_q.value.strip(),
        "-n",
        _url,
        "--timeout",
        str(ask_timeout.value),
    ]
    if ask_show.value:
        _args.append("--show-browser")
    with mo.status.spinner(title="Asking Gemini Notebook…", subtitle="usually 20–90 s"):
        _code, _out = run_gnb(*_args, timeout=ask_timeout.value + 120)

    _parts = _out.split("=" * 60)
    _answer = (
        _parts[2].replace(FOLLOW_UP_REMINDER.strip(), "").strip()
        if len(_parts) >= 3
        else None
    )
    mo.vstack(
        [
            mo.callout(mo.md(_answer), kind="success")
            if _answer
            else mo.callout("No answer – see the log below.", kind="danger"),
            mo.accordion({"gnb log": mo.md(f"```text\n{_out}\n```")}),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4 · Add sources

    The *Add sources* dialog has three paths the skill automates:

    | Type | In the dialog | `gnb add` option |
    |---|---|---|
    | Files (pdf, txt, md, docx, images, audio…) | **Upload files** → native file picker | `--file PATH` (repeatable) |
    | Websites / YouTube | **Websites** → paste links → *Insert* | `--url URL` (repeatable) |
    | Text | **Copied text** → paste → *Insert* | `--text "…"` or `--text-file PATH` |

    Afterwards `gnb add` watches the source list: a row with a checkbox is **ready**,
    a red row with an ⓘ icon has **failed** (paywall, blocked site, private video…).
    """)
    return


@app.cell(hide_code=True)
def _(Path, mo, notebooks):
    _options = {f"{nb['name']} ({nb['id']})": nb["url"] for nb in notebooks}
    add_nb = mo.ui.dropdown(
        options=_options,
        value=next(iter(_options), None),
        label="Notebook from library",
    )
    add_url_nb = mo.ui.text(
        placeholder="https://notebook.google.com/notebook/…",
        label="…or a notebook URL",
        full_width=True,
    )
    add_files = mo.ui.file_browser(
        initial_path=Path.home(), multiple=True, label="Files to upload"
    )
    add_urls = mo.ui.text_area(
        placeholder="One website / YouTube URL per line", label="URLs", full_width=True
    )
    add_text = mo.ui.text_area(
        placeholder="Text to add as a source", label="Pasted text", full_width=True
    )
    add_show = mo.ui.checkbox(label="Show browser")
    add_btn = mo.ui.run_button(label="Add to notebook", kind="warn")
    mo.vstack(
        [
            mo.callout(
                "This really changes the chosen notebook. Sources can only be removed in the web app.",
                kind="warn",
            ),
            add_nb,
            add_url_nb,
            mo.accordion({"Choose files": add_files}),
            add_urls,
            add_text,
            add_show,
            add_btn,
        ]
    )
    return add_btn, add_files, add_nb, add_show, add_text, add_url_nb, add_urls


@app.cell(hide_code=True)
def _(
    add_btn,
    add_files,
    add_nb,
    add_show,
    add_text,
    add_url_nb,
    add_urls,
    mo,
    run_gnb,
    show_output,
):
    mo.stop(not add_btn.value)
    _url = add_url_nb.value.strip() or add_nb.value
    mo.stop(not _url, mo.callout("Pick a notebook or paste a URL.", kind="warn"))

    _args = ["add", "-n", _url]
    for _f in add_files.value:
        if not _f.is_directory:
            _args += ["--file", str(_f.path)]
    for _u in add_urls.value.split():
        _args += ["--url", _u]
    if add_text.value.strip():
        _args += ["--text", add_text.value.strip()]
    mo.stop(
        len(_args) == 3,
        mo.callout("Nothing to add: choose files, URLs or text.", kind="warn"),
    )
    if add_show.value:
        _args.append("--show-browser")

    with mo.status.spinner(
        title="Adding sources…", subtitle="processing can take a few minutes"
    ):
        _result = run_gnb(*_args, timeout=900)
    show_output(*_result)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5 · Under the hood

    ### Reading the answer

    `inner_text()` of an answer bubble is messy: the collapsible *Thoughts* block
    and the citation chips come out as separate lines. `clean_answer()` in
    `ask.py` tidies it up. Edit the raw text and watch the result:
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    raw_answer = mo.ui.text_area(
        value=(
            "Thoughts\nexpand_more\n"
            "The study site is Lehrforst Rosalia\n1\nmore_horiz\n.\n"
            "GPS and Galileo signals were compared\n1\nmore_horiz\n4\nmore_horiz\n."
        ),
        label="Raw text scraped from the page",
        rows=9,
        full_width=True,
    )
    raw_answer
    return (raw_answer,)


@app.cell(hide_code=True)
def _(clean_answer, mo, raw_answer):
    mo.vstack(
        [
            mo.md("**After `clean_answer()`**"),
            mo.plain_text(clean_answer(raw_answer.value)),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Waiting for the *real* answer

    While Gemini works, the newest chat bubble shows progress text such as
    *"Reading through pages..."*. The script keeps polling while that text matches
    `PLACEHOLDER_RE`, and only accepts an answer that differs from the one on screen
    before the question was sent and stays unchanged for 3 polls.

    The chat list is *virtualized* (only visible bubbles exist in the page, in no
    reliable order), so "newest" means **lowest on screen**, not last in the HTML.

    Try some texts:
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    probe = mo.ui.text(
        value="Reading through pages...", label="Bubble text", full_width=True
    )
    probe
    return (probe,)


@app.cell(hide_code=True)
def _(PLACEHOLDER_RE, mo, probe):
    _is_placeholder = bool(PLACEHOLDER_RE.match(probe.value.strip()))
    mo.callout(
        "Placeholder → keep waiting"
        if _is_placeholder
        else "Looks like a real answer → wait until stable, then accept",
        kind="warn" if _is_placeholder else "success",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Finding things on the page

    All CSS selectors live in `src/gemini_notebook/config.py`. When Google changes the page, this is
    the one place to update (open the notebook with *Show browser*, inspect the element,
    adjust the selector):
    """)
    return


@app.cell(hide_code=True)
def _(config, mo):
    _rows = [
        {"name": _k, "selector": ", ".join(_v) if isinstance(_v, list) else _v}
        for _k, _v in vars(config).items()
        if _k.isupper()
        and (
            _k.endswith(("SELECTOR", "SELECTORS", "BUTTON", "INPUT"))
            or _k.startswith("SOURCE_ROW")
        )
    ]
    mo.ui.table(_rows, selection=None, pagination=False)
    return


@app.cell(hide_code=True)
def _(config, mo):
    mo.md(
        rf"""
        ### Staying logged in

        Playwright loses Google's *session* cookies between browser starts, so the skill
        uses both a persistent Chrome profile **and** re-injects the cookies saved at login
        (`browser_state/state.json`) every time. Details: `AUTHENTICATION.md`.

        Everything personal lives in `{config.DATA_DIR}`, outside the repository
        (set `GEMINI_NOTEBOOK_HOME` to use another folder). Treat it like a password.

        ## 6 · Limits and fixes

        | | |
        |---|---|
        | Sources can be added, not removed; no Google Drive / Play Books | use the web app |
        | Only sources are searched, not Studio notes or chat history | add notes as pasted text |
        | ≈50 questions/day on free accounts | wait, or `gnb auth reauth` with another account |
        | Login expires after a few weeks | `gnb auth reauth` |
        | `gnb: command not found` | `uv tool install --editable .` from the skill folder, then `uv tool update-shell` |
        | Something breaks after a Google UI change | rerun with *Show browser*, update `config.py` |

        More: `README.md`, `references/troubleshooting.md`.
        """
    )
    return


if __name__ == "__main__":
    app.run()
