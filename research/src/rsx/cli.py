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

from rsx import __version__, cite, gates, plan, review
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
app.add_typer(draft_app, name="draft")
app.add_typer(pi_app, name="pi")

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
            f'   pi workflow: subagent({{ workflow: "{WORKFLOWS / a.workflow["script"]}", args: {args} }})'
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
    findings = file.read_text("utf-8") if file else (text or "")
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
    "it names, with its args and cwd set to this folder. Do not write vault files "
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
