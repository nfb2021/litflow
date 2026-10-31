"""rsx: the orchestrator of the litflow literature workflow.

`rsx next` names the one next step, who does it and the gate that checks it.
Results go to stdout; progress and hints go to stderr.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import typer
from obs.vault import (
    VaultError,
    get_section,
    link,
    parse,
    refuse_lead,
    render,
    set_section,
)

from rsx import __version__, cite, gates, notebook, plan, review
from rsx import project as proj
from rsx.plan import ROLES, Ctx

app = typer.Typer(
    help="rsx: the litflow orchestrator - next step, stage gates, citation check, reviews, Pi setup.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
draft_app = typer.Typer(
    help="The draft: submit it for review, review it.", no_args_is_help=True
)
pi_app = typer.Typer(
    help="Set up Pi to load the litflow skills and agents.", no_args_is_help=True
)
notebook_app = typer.Typer(
    help="The project's Gemini Notebook: connect it, add the included PDFs.",
    no_args_is_help=True,
)
app.add_typer(draft_app, name="draft")
app.add_typer(notebook_app, name="notebook")
app.add_typer(pi_app, name="pi")
snowball_app = typer.Typer(
    help="Citation snowball: seeds -> references, N levels deep, judged and confirmed.",
    no_args_is_help=True,
)
app.add_typer(snowball_app, name="snowball")

ProjectOpt = typer.Option(
    None,
    "--project",
    "-P",
    help="Project folder (default: $RSX_PROJECT, else search upwards from cwd)",
)
JsonOpt = typer.Option(False, "--json", help="JSON output")
ByOpt = typer.Option(..., "--by", help=f"Your role: {', '.join(ROLES[1:])}")

# the repository this rsx runs from (editable install): ~/src/litflow
REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / "research" / "pi" / "workflows"


def info(msg: str) -> None:
    typer.echo(msg, err=True)


def fail(msg: str, code: int = 1) -> None:
    typer.echo(f"error: {msg}", err=True)
    raise typer.Exit(code)


def emit(data) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def today() -> str:
    return dt.date.today().isoformat()


def open_project(path: Path | None) -> proj.Project:
    try:
        return proj.find(path)
    except proj.ProjectError as e:
        fail(str(e))
        raise  # unreachable; for type checkers


def version_cb(value: bool) -> None:
    if value:
        typer.echo(f"rsx {__version__}")
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


def _action_dict(a: plan.Action) -> dict:
    d = a.to_dict()
    if a.workflow:
        d["workflow"] = {
            **a.workflow,
            "script": str(WORKFLOWS / a.workflow["script"]),
            # background children fail in Homebrew's Pi, and a blocking call
            # gives the lead the result instead of a receipt to poll
            "async": False,
        }
    return d


def _print_action(a: plan.Action, n: int | None = None) -> None:
    head = f"[{a.stage}] {a.title}  -> {a.role}"
    typer.echo(head if n is None else f"{n}. {head}")
    typer.echo(f"   why: {a.why}")
    if a.items:
        shown = ", ".join(a.items[:12]) + (" …" if len(a.items) > 12 else "")
        typer.echo(f"   items: {shown}")
    for c in a.commands:
        typer.echo(f"   $ {c}" if not c.startswith("#") else f"   {c}")
    if a.gate:
        typer.echo(f"   done when: `{a.gate}` says pass")
    if a.workflow:
        args = json.dumps(a.workflow["args"])
        typer.echo(
            f'   pi workflow: subagent({{ workflow: "{WORKFLOWS / a.workflow["script"]}", args: {args}, async: false }})'
        )


# --- project --------------------------------------------------------------------
@app.command()
def init(
    path: Path = typer.Argument(..., help="Project folder (created if missing)"),
    title: str = typer.Option(..., "--title", help="Project title / research topic"),
) -> None:
    """Create a project: rsx.toml, vault/, refs.bib, paper/main.typ, reviews/."""
    try:
        p = proj.init(path, title)
    except proj.ProjectError as e:
        fail(str(e))
    info(f"project created at {p.root}")
    info("next: point a Better BibTeX auto-export at refs.bib, then `rsx next`")
    typer.echo(str(p.root))


@app.command("next")
def next_cmd(
    role: str = typer.Option(None, "--role", help="Only actions for this role"),
    project: Path = ProjectOpt,
    as_json: bool = JsonOpt,
) -> None:
    """The next step of the workflow: who does what, with which commands."""
    p = open_project(project)
    actions = plan.plan(p)
    if role:
        actions = [a for a in actions if a.role == role]
    if as_json:
        emit([_action_dict(a) for a in actions])
        return
    if not actions:
        typer.echo(
            f"nothing for {role} now; the next step belongs to another role (`rsx next`)"
        )
        return
    for i, a in enumerate(actions, 1):
        _print_action(a, i if len(actions) > 1 else None)


@app.command()
def status(project: Path = ProjectOpt, as_json: bool = JsonOpt) -> None:
    """The project in one screen: paths, counts, stage, draft state."""
    p = open_project(project)
    x = Ctx.of(p)
    v = x.vault
    nxt = plan.plan(p, x)[0]
    data = {
        "project": str(p.root),
        "title": p.title,
        "vault": p.rel(p.vault_dir),
        "doc": p.rel(p.doc),
        "papers": len(x.papers),
        "included": sum(q.fm.get("screening") == "included" for q in x.papers.values()),
        "claims": len(v.of_type("claim")),
        "verified": sum(
            c.fm.get("verification") == "verified" for c in v.of_type("claim")
        ),
        "questions": len(v.of_type("question")),
        "answered": sum(
            q.fm.get("status") == "answered" for q in v.of_type("question")
        ),
        "notebook": p.notebook or "(not set: rsx notebook use URL|none)",
        "draft": review.draft_state(p),
        "stage": nxt.stage,
        "next": f"{nxt.title} -> {nxt.role}",
    }
    if as_json:
        emit(data)
        return
    typer.echo(f"{p.title}  ({p.root})")
    typer.echo(
        f"  papers {data['papers']} ({data['included']} included)  claims {data['claims']} ({data['verified']} verified)  questions {data['questions']} ({data['answered']} answered)"
    )
    typer.echo(f"  notebook {data['notebook']}")
    d = data["draft"]
    typer.echo(
        f"  draft {data['doc']}: submitted={d['submitted']} review={d['review'] or '-'}"
    )
    typer.echo(f"  stage: {data['stage']}  next: {data['next']}")


@app.command("gate")
def gate_cmd(
    stage: str = typer.Argument(..., help=" | ".join(gates.GATES)),
    paper: str = typer.Option(None, "--paper", help="Only this paper (citekey)"),
    question: str = typer.Option(None, "--question", help="Only this question"),
    project: Path = ProjectOpt,
) -> None:
    """One JSON verdict (pass | blocked) for a stage. Exit 0 either way."""
    p = open_project(project)
    try:
        emit(gates.gate(Ctx.of(p), stage, paper, question))
    except ValueError as e:
        fail(str(e))


# --- protocol ---------------------------------------------------------------------
@app.command()
def protocol(
    settle: bool = typer.Option(
        False, "--settle", help="Mark protocol.md settled (refused while gaps remain)"
    ),
    project: Path = ProjectOpt,
) -> None:
    """Show what protocol.md still lacks; --settle once the user has filled it."""
    p = open_project(project)
    v = p.vault
    path = v.root / "protocol.md"
    gaps = plan.protocol_gaps(v)
    if not settle:
        state = "settled" if plan.protocol_settled(v) else "draft"
        typer.echo(f"{p.rel(path)}: {state}")
        for g in gaps:
            typer.echo(f"  missing: {g}")
        if not gaps and state == "draft":
            typer.echo(
                "  complete: confirm with the user, then `rsx protocol --settle`"
            )
        return
    if gaps:
        fail("not settled, gaps remain:\n  " + "\n  ".join(gaps))
    fm, body = parse(path.read_text("utf-8"))
    fm["status"] = "settled"
    fm["settled"] = today()
    path.write_text(render(fm, body), "utf-8")
    typer.echo(
        f"{p.rel(path)}: settled. Change it from now on only via `obs decision`."
    )


# --- papers -----------------------------------------------------------------------
@app.command()
def extracted(
    key: str = typer.Argument(..., help="Paper citekey"),
    by: str = ByOpt,
    none: bool = typer.Option(
        False, "--none", help="Read it; nothing in it bears on the map's questions"
    ),
    note: str = typer.Option("", "--note", help="What was covered, what was left out"),
    project: Path = ProjectOpt,
) -> None:
    """Mark a paper's extraction done. Refused while its claims have problems."""
    p = open_project(project)
    x = Ctx.of(p)
    try:
        paper = x.vault.get(key, "paper")
    except VaultError as e:
        fail(str(e))
    if paper.fm.get("screening") != "included":
        fail(f"{paper.id} is {paper.fm.get('screening', 'pending')}, not included")
    claims = plan.claims_of(x.vault, paper.id)
    if none and claims:
        fail(f"{paper.id} has {len(claims)} claims; --none means it has none")
    if none and not note:
        fail("--none needs --note: why nothing in it bears on the questions")
    paper.fm["extraction"] = "none" if none else "done"
    problems = [
        pr
        for pr in plan.extraction_problems(x, paper.id)
        if "not marked done" not in pr
    ]
    if problems:
        fail("not done:\n  " + "\n  ".join(problems))
    paper.fm.update({"extracted_by": by, "extracted": today()})
    if note:
        paper.fm["extraction_note"] = note
    x.vault.save(paper)
    typer.echo(
        f"{paper.id}: extraction {paper.fm['extraction']} ({len(claims)} claims)"
    )


@app.command("not-in")
def not_in(
    key: str = typer.Argument(..., help="The cited paper"),
    statement: str = typer.Argument(..., help="The statement it was cited for"),
    note: str = typer.Option(..., "--note", help="What the paper says instead"),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Record that a cited paper was read and does not state the statement."""
    p = open_project(project)
    v = p.vault
    try:
        paper = v.get(key, "paper")
        st = v.get(statement, "statement")
    except VaultError as e:
        fail(str(e))
    if any(
        paper.id in c.links("paper") and st.id in c.links("statement")
        for c in v.of_type("claim")
    ):
        fail(f"{paper.id} has a claim on {st.id}: verify or reject that claim instead")
    ns = list(paper.fm.get("not_stated") or [])
    if st.id not in ns:
        ns.append(st.id)
    paper.fm["not_stated"] = ns
    log = get_section(paper.body, "Not stated")
    paper.body = set_section(
        paper.body,
        "Not stated",
        (log + f"\n- {link(st.id)} ({today()}, {by}): {note.strip()}").strip(),
    )
    v.save(paper)
    typer.echo(f"{paper.id}: does not state {st.id}")


def _search_target(v, key: str, question: str):
    try:
        paper = v.get(key, "paper")
        q = v.get(question, "question")
    except VaultError as e:
        fail(str(e))
    if q.id not in {x.id for x in plan.search_questions(v)}:
        fail(f"{q.id} is not a question papers are searched for")
    return paper, q


def _log_search(paper, line: str) -> None:
    log = get_section(paper.body, "Searched")
    paper.body = set_section(paper.body, "Searched", (log + f"\n- {line}").strip())


@app.command()
def searched(
    key: str = typer.Argument(..., help="Paper citekey"),
    question: str = typer.Argument(..., help="The question it was searched for"),
    found: list[str] = typer.Option(
        None, "--found", help="Claims of this paper that bear on the question"
    ),
    none: bool = typer.Option(
        False, "--none", help="The paper says nothing on the question"
    ),
    note: str = typer.Option("", "--note", help="Words and pages searched"),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Record that a paper was searched for a question: the claims found, or none."""
    if msg := refuse_lead("lit-reader", "Searching a paper"):
        fail(msg)
    p = open_project(project)
    v = p.vault
    paper, q = _search_target(v, key, question)
    if paper.fm.get("screening") != "included":
        fail(f"{paper.id} is {paper.fm.get('screening', 'pending')}, not included")
    found = [c for f in found or [] for c in f.replace(",", " ").split()]
    if bool(found) == none:
        fail("give either --found C-… or --none")
    if none and not note.strip():
        fail("--none needs --note: the words and pages you searched")
    own = {c.id: c for c in plan.claims_of(v, paper.id)}
    for cid in found:
        if cid not in own:
            fail(f"{cid} is not a claim of {paper.id}")
        if own[cid].fm.get("verification") == "rejected":
            fail(f"{cid} was rejected; it cannot answer {q.id}")
    if none and own:
        hint = ", ".join(own)
        info(f"{paper.id} has claims ({hint}); none of them bears on {q.id}?")
    entry = {"by": by, "date": today()}
    entry.update({"none": note.strip()} if none else {"found": found})
    paper.fm["searched"] = {**(paper.fm.get("searched") or {}), q.id: entry}
    what = f"nothing: {note.strip()}" if none else "found " + ", ".join(found)
    _log_search(paper, f"{link(q.id)} ({today()}, {by}): {what}")
    v.save(paper)
    typer.echo(f"{paper.id}: searched for {q.id}, {what}")


@app.command("confirm-none")
def confirm_none(
    key: str = typer.Argument(..., help="Paper citekey"),
    question: str = typer.Argument(..., help="The question it was found silent on"),
    dispute: bool = typer.Option(
        False, "--dispute", help="The paper does bear on the question"
    ),
    note: str = typer.Option(..., "--note", help="What you searched, or what it says"),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Check a reader's 'nothing in this paper' record by searching the paper again."""
    if msg := refuse_lead("lit-verifier", "Checking a search"):
        fail(msg)
    p = open_project(project)
    v = p.vault
    paper, q = _search_target(v, key, question)
    searched = dict(paper.fm.get("searched") or {})
    entry = searched.get(q.id)
    if not entry or "none" not in entry:
        fail(f"{paper.id} has no 'nothing found' record for {q.id}")
    if entry.get("by") == by:
        fail(f"{by} recorded this search; a different agent checks it")
    if dispute:
        del searched[q.id]
        verb = "disputed"
    else:
        searched[q.id] = {**entry, "confirmed_by": by, "confirmed": today()}
        verb = "confirmed"
    paper.fm["searched"] = searched
    _log_search(paper, f"{link(q.id)} ({today()}, {by}): {verb}: {note.strip()}")
    v.save(paper)
    typer.echo(f"{paper.id}: nothing on {q.id} {verb}")


@app.command()
def coverage(
    question: str = typer.Argument(None, help="One question; default: all of them"),
    as_json: bool = typer.Option(False, "--json"),
    project: Path = ProjectOpt,
) -> None:
    """What each included paper holds for a question: found claims, confirmed none, or unsearched."""
    p = open_project(project)
    v = p.vault
    qs = plan.search_questions(v)
    if question:
        qs = [q for q in qs if q.id == question]
        if not qs:
            fail(f"{question} is not a question papers are searched for")
    papers = [x for x in v.of_type("paper") if x.fm.get("screening") == "included"]
    out = {}
    for q in qs:
        rows = {}
        for paper in papers:
            s = (paper.fm.get("searched") or {}).get(q.id)
            if s is None:
                rows[paper.id] = "unsearched"
            elif "none" in s:
                rows[paper.id] = (
                    "none (confirmed)"
                    if s.get("confirmed_by")
                    else "none (unconfirmed)"
                )
            else:
                ok = [
                    c
                    for c in s["found"]
                    if c in v.notes and v.notes[c].fm.get("verification") == "verified"
                ]
                rows[paper.id] = "found " + (", ".join(ok) or "(none verified)")
        out[q.id] = rows
    if as_json:
        typer.echo(json.dumps(out, indent=2))
        return
    for q in qs:
        typer.echo(f"{q.id}: {q.title}")
        for key, row in out[q.id].items():
            typer.echo(f"  {key}: {row}")


@notebook_app.command("use")
def notebook_use(
    notebook_ref: str = typer.Argument(
        ...,
        metavar="NOTEBOOK",
        help="Notebook URL or gnb library ID; 'none' = local PDFs only",
    ),
    project: Path = ProjectOpt,
) -> None:
    """Set the project's Gemini Notebook (the user decides this, not an agent)."""
    p = proj.set_key(open_project(project), "notebook", notebook_ref.strip())
    typer.echo(f"notebook: {p.notebook}")
    if p.notebook != "none":
        info("next: `rsx notebook push` adds the included PDFs")


@notebook_app.command("push")
def notebook_push(
    batch: int = typer.Option(10, help="PDFs per `gnb add` call"),
    mark_only: bool = typer.Option(
        False,
        "--mark-only",
        help="The PDFs are in the notebook already (e.g. `zot push`): only record that",
    ),
    project: Path = ProjectOpt,
) -> None:
    """Add the PDFs of the included papers that are not in the notebook yet."""
    from obs.cli import paper_pdf

    p = open_project(project)
    if p.notebook in ("", "none"):
        fail("no notebook set: `rsx notebook use URL`")
    v = p.vault
    todo = [
        (x, paper_pdf(v, x))
        for x in v.of_type("paper")
        if x.fm.get("screening") == "included" and not x.fm.get("in_notebook")
    ]
    todo = [(x, pdf) for x, pdf in todo if pdf]
    if not todo:
        typer.echo("every included PDF is in the notebook")
        return
    total = len(notebook.in_notebook(v)) + len(todo)
    if total > 50:
        info(f"⚠️  {total} sources: the free plan holds 50 per notebook (Pro: 300)")
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        if not mark_only:
            cmd = [notebook.gnb(), "add", "-n", p.notebook]
            for _, pdf in chunk:
                cmd += ["-f", str(pdf)]
            info(f"gnb add: PDFs {start + 1}-{start + len(chunk)} of {len(todo)}")
            if subprocess.run(cmd).returncode != 0:
                fail(
                    "gnb add failed; rerun `rsx notebook push` (added PDFs are recorded)"
                )
        for x, _ in chunk:
            x.fm["in_notebook"] = today()
            v.save(x)
    typer.echo(f"{len(todo)} PDF(s) in the notebook")


def _lead_lines(lead: dict) -> str:
    tag = (
        "found"
        if lead["status"] == "found"
        else f"weak {lead['score']}, check the page"
    )
    return f'  p. {lead["page"]} ({tag}): "{lead["text"]}"'


@app.command()
def ask(
    questions: list[str] = typer.Argument(
        None,
        help="Questions to ask; default: every one not asked since papers were added",
    ),
    timeout: int = typer.Option(400, help="Seconds to wait for each answer"),
    as_json: bool = JsonOpt,
    project: Path = ProjectOpt,
) -> None:
    """Ask the Gemini Notebook a question across all papers; turn its quotes into leads.

    Each quote is looked up in the local PDF of every included paper. Papers
    it quotes nothing from are recorded as searched with nothing found (by
    "notebook"); a verifier confirms that by searching the PDF itself.
    """
    p = open_project(project)
    if p.notebook in ("", "none"):
        fail("no notebook set: `rsx notebook use URL`")
    v = p.vault
    papers = notebook.in_notebook(v)
    if not papers:
        fail("no included paper is in the notebook yet: `rsx notebook push`")
    open_qs = plan.search_questions(v)
    qs = (
        [q for q in open_qs if q.id in set(questions)]
        if questions
        else [q for q in open_qs if notebook.needs_asking(q, papers)]
    )
    if questions and len(qs) != len(set(questions)):
        fail(
            f"not questions papers are searched for: {', '.join(sorted(set(questions) - {q.id for q in qs}))}"
        )
    texts = notebook.page_texts(v, papers)
    results = {}
    for q in qs:
        info(f"asking the notebook {q.id}: {q.title}")
        try:
            answer = notebook.ask(p.notebook, notebook.prompt(q.title), timeout)
            if notebook.summarised(answer):  # cites sources, quotes none: once more
                info(f"  no quotes in the answer; asking {q.id} again for quotes")
                answer = notebook.ask(
                    p.notebook, notebook.prompt(q.title, strict=True), timeout
                )
        except notebook.NotebookError as e:
            fail(f"{q.id}: {e}")
        unsure = notebook.summarised(answer)
        found = notebook.anchor(notebook.quotes(answer), texts)
        record = {
            "question": q.id,
            "title": q.title,
            "asked": today(),
            "papers": sorted(x.id for x in papers),
            "answer": answer,
            **found,
            "inconclusive": unsure,
        }
        path = notebook.save(p, q.id, record)
        silent = []
        # a summary without quotes says nothing about which papers are silent
        for x in [] if unsure else papers:
            searched = dict(x.fm.get("searched") or {})
            s = searched.get(q.id)
            if x.id in found["leads"]:
                if s and s.get("by") == notebook.BY and "none" in s:
                    del searched[q.id]  # a new answer quotes it after all
                    _log_search(
                        x,
                        f"{link(q.id)} ({today()}, {notebook.BY}): now quoted; `rsx leads {x.id}`",
                    )
                else:
                    continue
            elif s is None:
                silent.append(x.id)
                searched[q.id] = {
                    "by": notebook.BY,
                    "date": today(),
                    "none": f"the notebook quoted nothing from it ({p.rel(path)})",
                }
                _log_search(
                    x, f"{link(q.id)} ({today()}, {notebook.BY}): nothing quoted"
                )
            else:
                continue
            x.fm["searched"] = searched
            v.save(x)
        q.fm["asked"] = {"date": today(), "title": q.title, "papers": record["papers"]}
        v.save(q)
        results[q.id] = {
            **found,
            "silent": silent,
            "inconclusive": unsure,
            "file": p.rel(path),
        }
    if as_json:
        emit(results)
        return
    for qid, r in results.items():
        n = sum(len(ls) for ls in r["leads"].values())
        typer.echo(
            f"{qid}: {n} lead(s) in {len(r['leads'])} paper(s); {len(r['unanchored'])} quote(s) in no PDF"
        )
        for key, ls in r["leads"].items():
            pages = sorted({lead["page"] for lead in ls})
            typer.echo(f"  {key}: {len(ls)} lead(s), p. {', '.join(map(str, pages))}")
        if r["inconclusive"]:
            typer.echo(
                "  the notebook summarised without quotes, twice: readers search every paper"
            )
        if r["silent"]:
            typer.echo(
                f"  nothing quoted from: {', '.join(r['silent'])} (a verifier confirms)"
            )
        typer.echo(f"  answer and leads: {r['file']}")
    if results:
        info("readers: `rsx leads KEY` lists a paper's leads")
    else:
        info("every question was asked since the last papers were added")


@app.command()
def leads(
    key: str = typer.Argument(..., help="Paper citekey"),
    question: str = typer.Option(None, "--question", "-q", help="Only this question"),
    as_json: bool = JsonOpt,
    project: Path = ProjectOpt,
) -> None:
    """What the notebook quoted from a paper, per question, as the page prints it.

    A lead is a pointer, not evidence: read the page, then copy the text into
    `obs claim add`. Quotes found in no PDF may be translated or paraphrased
    passages of this paper; search for them.
    """
    p = open_project(project)
    v = p.vault
    try:
        paper = v.get(key, "paper")
    except VaultError as e:
        fail(str(e))
    out = {}
    for q in plan.search_questions(v):
        if question and q.id != question:
            continue
        rec = notebook.load(p, q.id)
        if rec is None:
            continue
        out[q.id] = {
            "title": q.title,
            "asked": rec["asked"],
            "leads": rec["leads"].get(paper.id, []),
            "unanchored": rec["unanchored"],
        }
    if as_json:
        emit(out)
        return
    if not out:
        typer.echo(
            "no notebook answers yet: `rsx ask` (or the project has no notebook)"
        )
        return
    for qid, r in out.items():
        typer.echo(f"{qid}: {r['title']}  (asked {r['asked']})")
        if r["leads"]:
            for lead in r["leads"]:
                typer.echo(_lead_lines(lead))
        else:
            typer.echo("  the notebook quoted nothing from this paper")
        for u in r["unanchored"]:
            typer.echo(f'  in no PDF (translated or paraphrased?): "{u}"')
    typer.echo(
        f'\nobs claim add -p {paper.id} -s S-… -q "<text of a lead, checked on its page>" -r ROLE --by lit-reader'
    )


@app.command()
def unavailable(
    key: str = typer.Argument(..., help="Citekey of the paper that cannot be obtained"),
    reason: str = typer.Option(..., "--reason", help="Where you looked"),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Exclude a paper no copy of which can be found (it cannot be read or cited)."""
    p = open_project(project)
    v = p.vault
    fm = {
        "screening": "excluded",
        "screening_reason": f"E0: unavailable - {reason.strip()}",
        "screened_by": by,
        "screened": today(),
    }
    paper = v.notes.get(key)
    if paper is not None and paper.type != "paper":
        fail(f"{key} is a {paper.type}, not a paper")
    if paper is None:
        paper = v.create(
            "paper",
            {"title": key, **fm},
            f"\n# {key}\n\nNot obtainable; recorded so citation chains end here.\n",
            note_id=key,
        )
    else:
        if plan.claims_of(v, paper.id):
            fail(f"{paper.id} has claims, so it was readable; do not exclude it")
        paper.fm.update(fm)
        v.save(paper)
    typer.echo(f"{paper.id}: excluded as unavailable")


@app.command()
def relink(
    old: str = typer.Argument(..., help="The key claims cite now"),
    new: str = typer.Argument(..., help="The paper's real citekey"),
    project: Path = ProjectOpt,
) -> None:
    """Point claim citations at a paper's real key (after Better BibTeX picked another)."""
    p = open_project(project)
    v = p.vault
    try:
        v.get(new, "paper")
    except VaultError as e:
        fail(str(e))
    n = 0
    for c in v.of_type("claim"):
        cites = c.fm.get("cites") or []
        if link(old) in cites:
            c.fm["cites"] = list(
                dict.fromkeys(link(new) if x == link(old) else x for x in cites)
            )
            v.save(c)
            n += 1
    typer.echo(f"{n} claim(s) now cite {new}")


# --- reviews ----------------------------------------------------------------------
def _verdict(ok: bool, block: bool) -> str:
    if ok == block:
        fail("pass exactly one of --ok and --block")
    return "ok" if ok else "blocked"


@app.command("review")
def review_cmd(
    question: str = typer.Argument(..., help="Answered question id"),
    ok: bool = typer.Option(False, "--ok", help="The answer holds"),
    block: bool = typer.Option(
        False, "--block", help="The answer is wrong or unsupported"
    ),
    note: str = typer.Option(..., "--note", help="What you checked and what you found"),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Review an answered question. --block sends it back to the frontier."""
    if err := refuse_lead("lit-critic", "Reviewing answers"):
        fail(err)
    p = open_project(project)
    try:
        q = review.review_question(p.vault, question, _verdict(ok, block), note, by)
    except (review.ReviewError, VaultError) as e:
        fail(str(e))
    typer.echo(
        f"{q.id}: {q.fm['review']}" + (" (back on the frontier)" if block else "")
    )


@app.command("cite-check")
def cite_check(
    doc: Path = typer.Argument(None, help="Typst file (default: the project's draft)"),
    require_claims: bool = typer.Option(
        True,
        "--require-claims/--no-require-claims",
        help="Each cited paper needs a `// C-…` claim in its paragraph",
    ),
    project: Path = ProjectOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Check the draft's citations against the vault. Exit 1 on errors."""
    p = open_project(project)
    path = doc or p.doc
    if not path.exists():
        fail(f"{path} does not exist")
    r = cite.check(p.vault, path.read_text("utf-8"), require_claims)
    if as_json:
        emit(r)
    else:
        for i in r["issues"]:
            typer.echo(
                f"{path.name}:{i['line']}: {i['level']} {i['code']}: {i['msg']}"
                + (f"  -> {i['fix']}" if i["fix"] else "")
            )
        info(
            f"{r['paragraphs']} paragraphs, {len(r['cited'])} papers cited, {len(r['claims'])} claims named: {r['errors']} errors, {r['warnings']} warnings"
        )
    if r["errors"]:
        raise typer.Exit(1)


@draft_app.command("submit")
def draft_submit(by: str = ByOpt, project: Path = ProjectOpt) -> None:
    """Check the draft (cite-check, typst compile) and submit it for review."""
    if err := refuse_lead("lit-writer", "Submitting the draft"):
        fail(err)
    p = open_project(project)
    x = Ctx.of(p)
    g = gates.gate(x, "write")
    blocking = [i for i in g["issues"] if not i.startswith("checks pass; submit")]
    if blocking:
        fail("not submitted:\n  " + "\n  ".join(blocking))
    try:
        path = review.submit_draft(p, by, plan.draft_check(x))
    except review.ReviewError as e:
        fail(str(e))
    typer.echo(f"submitted: {path}")
    for w in g.get("warnings", []):
        info(f"warning: {w}")


@draft_app.command("review")
def draft_review(
    ok: bool = typer.Option(False, "--ok", help="The draft holds"),
    block: bool = typer.Option(False, "--block", help="It must be revised"),
    finding: list[str] = typer.Option(
        None, "--finding", "-f", help="One finding, `line N: problem -> fix`; repeat"
    ),
    file: Path = typer.Option(
        None, "--file", help="Findings, one per line, with line numbers"
    ),
    text: str = typer.Option(None, "--text", help="Findings (instead of --file)"),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Review the submitted draft. Findings are required either way."""
    if err := refuse_lead("lit-critic", "Reviewing the draft"):
        fail(err)
    p = open_project(project)
    if file and not file.exists():
        fail(f"{file} does not exist; pass findings with --finding instead")
    findings = "\n".join(
        [*(finding or []), *([file.read_text("utf-8")] if file else []), text or ""]
    ).strip()
    try:
        path = review.review_draft(p, _verdict(ok, block), findings, by)
    except review.ReviewError as e:
        fail(str(e))
    typer.echo(f"reviewed: {path}")


@draft_app.command("show")
def draft_show(project: Path = ProjectOpt) -> None:
    """Submission and review state of the current draft."""
    emit(review.draft_state(open_project(project)))


# --- setup ------------------------------------------------------------------------
def _pi_settings() -> Path:
    base = os.environ.get("PI_CODING_AGENT_DIR") or "~/.pi/agent"
    return Path(base).expanduser() / "settings.json"


TYPST_SKILLS = Path("~/src/claude-skill-typst/skills").expanduser()


@pi_app.command("install")
def pi_install(
    repo: Path = typer.Option(REPO, "--repo", help="The litflow checkout"),
    typst_skills: Path = typer.Option(
        TYPST_SKILLS, "--typst-skills", help="skills/ folder of claude-skill-typst"
    ),
) -> None:
    """Add litflow (skills and agents) and the typst skill to Pi's settings.json."""
    repo = repo.expanduser().resolve()
    if not (repo / "package.json").exists():
        fail(f"{repo} has no package.json: not a litflow checkout")
    path = _pi_settings()
    data = json.loads(path.read_text("utf-8")) if path.exists() else {}
    before = json.dumps(data, sort_keys=True)
    pkgs = data.setdefault("packages", [])
    if str(repo) not in pkgs:
        pkgs.append(str(repo))
    if typst_skills.expanduser().exists():
        skills = data.setdefault("skills", [])
        ts = str(typst_skills.expanduser().resolve())
        if ts not in skills:
            skills.append(ts)
    else:
        info(
            f"no typst skill at {typst_skills}: clone lucifer1004/claude-skill-typst there"
        )
    if json.dumps(data, sort_keys=True) == before:
        typer.echo(f"{path}: already set up")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    typer.echo(
        f"{path}: litflow added (backup: {path.with_suffix('.json.bak').name}). Restart pi or /reload."
    )


LEAD_PROMPT = (
    "/skill:research You are the lead of the litflow project in the current folder. "
    "Run `rsx status`, then repeat: `rsx next --json`, carry out the step it names, "
    "run its gate. Delegate every lit-* step with the subagent tool: the workflow "
    "it names, with its args, async: false and cwd set to this folder. Do not write vault files "
    "yourself; use obs and rsx. Never end a reply with a plan: call the tool. "
    "Stop when rsx next says done or needs the user, and report what is stuck."
)


def _progress(p: proj.Project) -> str:
    """What `rsx drive` compares between rounds: the plan and the files."""
    actions = [(a.stage, a.role, a.title, a.items) for a in plan.plan(p)]
    files = sorted(
        (str(f.relative_to(p.root)), f.stat().st_mtime_ns)
        for f in p.root.rglob("*")
        if f.is_file() and ".rsx" not in f.parts and ".obs" not in f.parts
    )
    return json.dumps([actions, files])


def _model_error(log: Path) -> str | None:
    """The error that ended a Pi run without a model reply, e.g. a timeout."""
    error = None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue  # shell start-up noise
        if isinstance(event, dict) and event.get("type") == "agent_end":
            last = (event.get("messages") or [{}])[-1]
            error = (
                last.get("errorMessage") if last.get("stopReason") == "error" else None
            )
    return error


@app.command()
def drive(
    model: str = typer.Option(
        None, "--model", help="Pi model for the lead, e.g. aqueduct/qwen-3.6-35b"
    ),
    rounds: int = typer.Option(8, "--rounds", help="At most this many Pi runs"),
    pi: str = typer.Option(
        "pi",
        "--pi",
        help="Command that starts Pi; runs in your interactive shell, so a shell function works",
    ),
    project: Path = ProjectOpt,
) -> None:
    """Run the Pi lead again until the workflow is done, needs the user, or stalls.

    Weak models end a run while saying what they will do next; each round
    starts the lead fresh on the same project. Logs: .rsx/drive/.
    """
    p = open_project(project)
    logs = p.root / ".rsx" / "drive"
    logs.mkdir(parents=True, exist_ok=True)
    shell = os.environ.get("SHELL", "/bin/zsh")
    cmd = f"{pi} -p --mode json" + (f" --model {shlex.quote(model)}" if model else "")
    cmd += f" {shlex.quote(LEAD_PROMPT)}"
    stalled = 0
    for n in range(1, rounds + 1):
        first = plan.plan(p)[0]
        if first.stage == "done" or first.role == "human":
            typer.echo(f"{first.stage}: {first.title}")
            return
        before = _progress(p)
        log = logs / f"round-{n:02d}.jsonl"
        info(
            f"round {n}: {first.stage} -> {first.role} ({first.title}); log {p.rel(log)}"
        )
        with log.open("w", encoding="utf-8") as out:
            r = subprocess.run(
                [shell, "-ic", cmd], cwd=p.root, stdout=out, stderr=subprocess.STDOUT
            )
        if r.returncode:
            fail(f"pi exited {r.returncode} in round {n}; see {p.rel(log)}")
        if error := _model_error(log):
            fail(f"the model did not answer in round {n}: {error}; see {p.rel(log)}")
        stalled = 0 if _progress(p) != before else stalled + 1
        if stalled == 2:
            fail(f"no progress in two rounds; still at: {plan.plan(p)[0].title}")
    typer.echo(f"stopped after {rounds} rounds at: {plan.plan(p)[0].title}")


@app.command()
def doctor() -> None:
    """Check the tools the workflow needs. Exit 1 if a required one is missing."""
    required = {
        "obs": "uv tool install --editable ~/src/litflow/obsidian",
        "zot": "uv tool install --editable ~/src/litflow/zotero",
        "gnb": "uv tool install --editable ~/src/litflow/gemini_notebook",
        "typst": "brew install typst",
    }
    optional = {
        "ocrmypdf": "brew install ocrmypdf (scanned PDFs)",
        "pi": "the Pi harness",
    }
    bad = 0
    for cmd, fix in required.items():
        ok = shutil.which(cmd) is not None
        bad += not ok
        typer.echo(
            f"{'ok ' if ok else 'MISSING'} {cmd}" + ("" if ok else f"  -> {fix}")
        )
    for cmd, fix in optional.items():
        ok = shutil.which(cmd) is not None
        typer.echo(f"{'ok ' if ok else 'absent'} {cmd}" + ("" if ok else f"  ({fix})"))
    if shutil.which("zot"):
        r = subprocess.run(
            ["zot", "status"], capture_output=True, text=True, timeout=30
        )
        typer.echo(
            "ok  Zotero answers"
            if r.returncode == 0
            else "WARN Zotero: "
            + (r.stderr.strip().splitlines() or ["not reachable"])[-1]
        )
    s = _pi_settings()
    pkgs = json.loads(s.read_text("utf-8")).get("packages", []) if s.exists() else []
    typer.echo(
        "ok  Pi loads litflow"
        if str(REPO) in pkgs
        else "absent Pi setup  -> rsx pi install"
    )
    if bad:
        raise typer.Exit(1)


# --- setup and the snowball ---------------------------------------------------

CONFIG = {
    "collection": "Zotero collection name (a new name is created on the first fetch)",
    "depth": "levels of references the snowball follows from the seeds (0 = no snowball)",
    "fetch": "zotero (zot add fetches, on the institution's network) or manual (the user adds)",
}


@app.command("config")
def config_cmd(
    key: str = typer.Argument(..., help=f"One of: {', '.join(CONFIG)}"),
    value: str = typer.Argument(None, help="New value; omit to show the current one"),
    project: Path = ProjectOpt,
) -> None:
    """Record a choice the user made: collection, depth or fetch. Agents ask; never pick."""
    p = open_project(project)
    if key not in CONFIG:
        fail(
            f"unknown key {key!r}: {', '.join(f'{k} ({v})' for k, v in CONFIG.items())}"
        )
    if value is None:
        typer.echo(getattr(p, key) or "(not chosen)")
        return
    value = value.strip()
    if key == "depth" and not value.isdigit():
        fail(
            "depth is a whole number: 0 (no snowball), 1 (the seeds' references), 2, ..."
        )
    if key == "fetch" and value not in ("zotero", "manual"):
        fail("fetch is 'zotero' or 'manual'")
    if not value:
        fail(f"{key} cannot be empty")
    p = proj.set_key(p, key, value)
    typer.echo(f"{key}: {getattr(p, key)}")


@app.command("check")
def check_cmd(as_json: bool = JsonOpt, project: Path = ProjectOpt) -> None:
    """The startup check: tools, services, the user's choices, the refs.bib export.
    Exit 1 while an error remains; the workflow waits for a passing check."""
    from rsx import check

    p = open_project(project)
    items = check.run(p)
    rec = check.record(p, items)
    if as_json:
        emit({**rec, "items": items})
    else:
        group = None
        for i in items:
            if i["group"] != group:
                group = i["group"]
                typer.echo(f"{group}:")
            mark = "ok  " if i["ok"] else ("FAIL" if i["level"] == "error" else "warn")
            typer.echo(
                f"  {mark} {i['item']}" + ("" if i["ok"] else f"  -> {i['fix']}")
            )
        typer.echo("startup check passed" if rec["ok"] else "startup check FAILED")
    if not rec["ok"]:
        raise typer.Exit(1)


def _snow(fn, *args):
    from rsx import snowball

    try:
        return fn(*args)
    except snowball.SnowballError as e:
        fail(str(e))


@snowball_app.command("seed")
def snowball_seed(
    dois: list[str] = typer.Argument(..., help="DOIs of the seed papers the user gave"),
    project: Path = ProjectOpt,
) -> None:
    """Record the seed papers (level 0). The user names them."""
    from rsx import snowball

    added = _snow(snowball.seed, open_project(project), dois)
    typer.echo(
        f"{len(added)} seed(s) added" + (f": {', '.join(added)}" if added else "")
    )


@snowball_app.command("fetch")
def snowball_fetch(as_json: bool = JsonOpt, project: Path = ProjectOpt) -> None:
    """Get the papers not in Zotero yet: zot add (fetch = zotero) or a list of
    doi.org links for the user (fetch = manual)."""
    from rsx import snowball

    p = open_project(project)
    r = _snow(snowball.fetch, p)
    if as_json:
        emit(r)
        return
    if not r["todo"]:
        typer.echo("every snowball paper is in Zotero")
    elif r["mode"] == "manual":
        typer.echo(
            f"{len(r['todo'])} paper(s) for the user to add to '{p.collection}':"
        )
        for d in r["todo"]:
            typer.echo(f"  https://doi.org/{d}")
        info("listed in .rsx/to-add.txt; then `rsx snowball sync`")
    else:
        for res in r["results"]:
            typer.echo(f"  {res.get('status', '?'):9} {res.get('input')}")
        _snowball_summary(p)


@snowball_app.command("sync")
def snowball_sync(project: Path = ProjectOpt) -> None:
    """Read the Zotero collection: which snowball papers arrived, which lack a PDF."""
    from rsx import snowball

    p = open_project(project)
    r = _snow(snowball.sync, p)
    typer.echo(
        f"{len(r['arrived'])} paper(s) arrived; {len(r['missing'])} still to add"
    )
    for d in r["missing"]:
        typer.echo(f"  missing  https://doi.org/{d}")
    for d in r["no_pdf"]:
        typer.echo(f"  no PDF   https://doi.org/{d}")


@snowball_app.command("unavailable")
def snowball_unavailable(
    doi: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", help="Why no copy can be had"),
    project: Path = ProjectOpt,
) -> None:
    """A paper nobody can get: never fetched again (its references can still be judged)."""
    from rsx import snowball

    _snow(snowball.unavailable, open_project(project), doi, reason)
    typer.echo(f"{doi}: unavailable")


@snowball_app.command("refs")
def snowball_refs(
    doi: str = typer.Argument(..., help="A snowball paper's DOI"),
    as_json: bool = JsonOpt,
    project: Path = ProjectOpt,
) -> None:
    """A paper's references, numbered, with the reader's decisions if judged."""
    from rsx import snowball

    p = open_project(project)
    s = snowball.load(p)
    d = snowball.norm(doi)
    x = s["papers"].get(d)
    if x is None:
        fail(f"{doi} is not in the snowball: `rsx next` names the papers to judge")
    if x.get("refs"):
        source, rows = x["refs"]["source"], x["refs"]["list"]
    else:
        source, rows = _snow(snowball.references, p, d)
    if as_json:
        emit({"doi": d, "source": source, "refs": rows, "judgement": x.get("refs")})
        return
    typer.echo(f"{d}  level {x['depth']}  {len(rows)} references ({source})")
    for r in rows:
        seen = "in snowball" if r.get("doi") in s["papers"] else ""
        dec = r.get("decision", "")
        why = f" ({r['why']})" if r.get("why") else ""
        typer.echo(
            f"  {r['n']:3} {dec:8}{why} {r.get('doi') or 'no DOI':38} {seen:11} {r['text'][:150]}"
        )
    if not rows:
        info(
            "no reference list in Crossref or the PDF: `rsx snowball no-refs` with the reason"
        )


@snowball_app.command("judge")
def snowball_judge(
    doi: str = typer.Argument(...),
    include: list[str] = typer.Option(
        None, "--include", "-i", help="N, or N=DOI when the list has none, or N=none"
    ),
    exclude: list[str] = typer.Option(None, "--exclude", "-x", help="N:'E2: why'"),
    rest: str = typer.Option(
        None, "--exclude-rest", help="'E2: why' for every reference not named"
    ),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Decide every reference of a paper against protocol.md."""
    from rsx import snowball

    r = _snow(snowball.judge, open_project(project), doi, include, exclude, rest, by)
    inc = sum(x.get("decision") == "include" for x in r["list"])
    typer.echo(
        f"{doi}: {inc} included, {len(r['list']) - inc} excluded; a verifier confirms next"
    )


@snowball_app.command("no-refs")
def snowball_no_refs(
    doi: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason"),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """Record that no reference list can be had (not in Crossref, no PDF)."""
    from rsx import snowball

    _snow(snowball.no_refs, open_project(project), doi, reason, by)
    typer.echo(f"{doi}: no references recorded")


@snowball_app.command("confirm")
def snowball_confirm(
    doi: str = typer.Argument(...),
    include: list[str] = typer.Option(
        None, "--include", "-i", help="Include what the reader excluded: N or N=DOI"
    ),
    exclude: list[str] = typer.Option(
        None, "--exclude", "-x", help="Exclude what the reader included: N:'E2: why'"
    ),
    by: str = ByOpt,
    project: Path = ProjectOpt,
) -> None:
    """The verifier's check of a reader's judgement. Inclusions then enter the snowball."""
    from rsx import snowball

    added = _snow(snowball.confirm, open_project(project), doi, by, include, exclude)
    typer.echo(f"{doi}: confirmed; {len(added)} new paper(s) for the next level")


@snowball_app.command("find")
def snowball_find(
    title: str = typer.Argument(..., help="The reference's text"),
    project: Path = ProjectOpt,
) -> None:
    """Crossref's best matches for a reference without a DOI."""
    from rsx import snowball

    for line in _snow(snowball.find, open_project(project), title):
        typer.echo(line)


def _snowball_summary(p) -> None:
    from rsx import snowball

    s = snowball.load(p)
    w = snowball.open_work(p)
    levels: dict[int, int] = {}
    for x in s["papers"].values():
        levels[x["depth"]] = levels.get(x["depth"], 0) + 1
    typer.echo(
        f"depth {p.depth or '?'}; papers per level: "
        + ", ".join(f"{k}: {v}" for k, v in sorted(levels.items()))
    )
    typer.echo(
        f"to fetch {len(w['fetch'])}, to judge {len(w['judge'])}, to confirm {len(w['confirm'])}, "
        f"not in refs.bib {len(w['bib'])}, without PDF {len(w['no_pdf'])}"
    )
    typer.echo(f"log book: {p.rel(p.vault_dir / 'snowball.md')}")


@snowball_app.command("status")
def snowball_status(project: Path = ProjectOpt) -> None:
    """Papers per level and the open snowball work."""
    _snowball_summary(open_project(project))


@snowball_app.command("log")
def snowball_log(project: Path = ProjectOpt) -> None:
    """Rewrite the log book (vault/snowball.md) and the papers' snowball_cites links."""
    from rsx import snowball

    p = open_project(project)
    snowball.render(p, snowball.load(p))
    typer.echo(p.rel(p.vault_dir / "snowball.md"))
