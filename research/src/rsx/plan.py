"""The workflow as a state machine over the project.

`plan()` reads the vault, refs.bib and the draft and returns the open work in
the order of the method: settle the protocol, map the question, find and screen
papers, extract claims, verify them, chase citations to their origin, answer
the questions, have the answers reviewed, write, have the draft reviewed.
`rsx next` prints the first action; nothing later starts while an earlier stage
has open work, so a small model cannot skip verification or review.

Each action names the role that does it, the exact commands, and the gate
command that must report `pass` before the action counts as done.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from obs import bib, lint, provenance, wayfinder
from obs.vault import Vault, get_section

from rsx import notebook, review
from rsx.project import Project

ROLES = (
    "human",
    "lead",
    "lit-scout",
    "lit-reader",
    "lit-verifier",
    "lit-critic",
    "lit-writer",
)
KIND_ROLE = {
    "research": "lit-scout",
    "query": "lit-reader",
    "falsify": "lit-critic",
    "task": "lead",
}
# who fixes a lint error
FIXER = {
    "quote-not-found": "lit-reader",
    "claim-no-quote": "lit-reader",
    "claim-no-page": "lit-reader",
    "restates-no-cites": "lit-reader",
    "claim-from-excluded": "lit-reader",
    "self-verified": "lit-verifier",
    "verified-by-nobody": "lit-verifier",
    "agent-answered-grilling": "human",
    "answer-without-evidence": "lit-reader",
    "hand-edited": "lead",
}
CRITERION = re.compile(r"^\s*[IE]\d+\b")
# questions every included paper is searched for before its extraction counts
SEARCHED_KINDS = ("research", "query", "falsify")


@dataclass
class Action:
    stage: str
    role: str
    title: str
    why: str
    items: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    gate: str | None = None
    workflow: dict | None = None

    def specialised(self) -> Action:
        """With one item, write it into the commands instead of KEY / Q-…."""
        if len(self.items) != 1:
            return self
        item = self.items[0]
        token = "Q-…" if item.startswith("Q-") else "KEY"

        def sub(text: str) -> str:
            return text.replace(token, item)

        return Action(
            self.stage,
            self.role,
            self.title,
            self.why,
            self.items,
            [sub(c) for c in self.commands],
            sub(self.gate) if self.gate else None,
            self.workflow,
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], {})}


# --- facts about the project ----------------------------------------------------
def protocol_gaps(vault: Vault) -> list[str]:
    """What the user still has to decide: unfilled lines of protocol.md."""
    path = vault.root / "protocol.md"
    if not path.exists():
        return ["protocol.md is missing"]
    text = path.read_text("utf-8")
    sec = get_section(text, "Research question")
    gaps = []
    if not sec.strip() or "_one sentence_" in sec:
        gaps.append("Research question: not filled in")
    for heading in ("Scope", "Inclusion criteria", "Exclusion criteria", "Search"):
        sec = get_section(text, heading)
        empty = [
            ln[2:].rstrip(": ")
            for ln in sec.splitlines()
            if re.match(r"^- [^:]+:\s*$", ln)
        ]
        if not sec.strip():
            gaps.append(f"{heading}: section missing")
        elif empty:
            gaps.append(
                f"{heading}: " + ", ".join(empty) + " (fill in, or write 'none')"
            )
    return gaps


def protocol_settled(vault: Vault) -> bool:
    path = vault.root / "protocol.md"
    return (
        path.exists()
        and re.search(r"^status:\s*settled\s*$", path.read_text("utf-8"), re.M)
        is not None
    )


def bib_keys(project: Project) -> list[str]:
    if not project.bib.exists():
        return []
    return [e["ID"] for e in bib.parse_bib(project.bib.read_text("utf-8"))]


def has_pdf(vault: Vault, paper) -> bool:
    from obs.cli import paper_pdf

    return paper_pdf(vault, paper) is not None


def claims_of(vault: Vault, key: str) -> list:
    return [c for c in vault.of_type("claim") if key in c.links("paper")]


def search_questions(vault: Vault) -> list:
    """The questions every included paper must be searched for."""
    return [
        q
        for q in vault.of_type("question")
        if q.fm.get("kind") in SEARCHED_KINDS and q.fm.get("status") != "out-of-scope"
    ]


def search_problems(vault: Vault, paper) -> list[str]:
    """Questions the paper was not (or no longer) searched for."""
    searched = paper.fm.get("searched") or {}
    out = []
    for q in search_questions(vault):
        s = searched.get(q.id)
        if s is None:
            out.append(
                f"{paper.id}: not searched for {q.id} ({q.title}); "
                f"`rsx searched {paper.id} {q.id} --found C-… | --none --note …`"
            )
        elif s.get("found") and all(
            vault.notes.get(c) is None
            or vault.notes[c].fm.get("verification") == "rejected"
            for c in s["found"]
        ):
            out.append(
                f"{paper.id}: every claim found for {q.id} was rejected; search again "
                f"(`obs show {paper.id}`, section Searched) and record it with `rsx searched`"
            )
    return out


def unconfirmed_nones(vault: Vault, paper) -> list[str]:
    """Questions the paper was found silent on that no second agent checked."""
    open_ids = {q.id for q in search_questions(vault)}
    return [
        qid
        for qid, s in (paper.fm.get("searched") or {}).items()
        if qid in open_ids and "none" in s and not s.get("confirmed_by")
    ]


def unsupported_statements(vault: Vault) -> list[str]:
    return [
        s.id
        for s in vault.of_type("statement")
        if not provenance.trace(vault, s.id)["origins"]
    ]


# --- the stages ------------------------------------------------------------------
@dataclass
class Ctx:
    """What every stage reads, computed once per `plan()`."""

    project: Project
    vault: Vault
    issues: list[dict]
    papers: dict

    @classmethod
    def of(cls, project: Project) -> Ctx:
        v = project.vault
        return cls(project, v, lint.lint(v), {p.id: p for p in v.of_type("paper")})

    @property
    def bib_rel(self) -> str:
        return self.project.rel(self.project.bib)


def s_fix(x: Ctx) -> list[Action]:
    errors = [i for i in x.issues if i["level"] == "error"]
    by_role: dict[str, list[dict]] = {}
    for i in errors:
        by_role.setdefault(FIXER.get(i["code"], "lead"), []).append(i)
    return [
        Action(
            "fix",
            role,
            f"Fix {len(errs)} vault error(s)",
            "The vault breaks a research rule; nothing else starts until it is fixed.",
            items=sorted({i["note"] for i in errs}),
            commands=[f"# {i['note']}: {i['msg']} -> {i['fix']}" for i in errs[:20]]
            + ["obs lint"],
            gate="rsx gate vault",
        )
        for role, errs in by_role.items()
    ]


def s_protocol(x: Ctx) -> list[Action]:
    if protocol_settled(x.vault):
        return []
    return [
        Action(
            "protocol",
            "human",
            "Settle the review protocol with the user",
            "Search, screening and extraction follow protocol.md; agents may not invent its criteria.",
            items=protocol_gaps(x.vault),
            commands=[
                "rsx protocol                      # shows what is missing",
                "# ask the user ONE question per gap, write their answers into vault/protocol.md",
                "rsx protocol --settle             # refuses while gaps remain",
            ],
            gate="rsx gate protocol",
        )
    ]


def s_map(x: Ctx) -> list[Action]:
    maps = x.vault.of_type("map")
    if maps and x.vault.of_type("question"):
        return []
    return [
        Action(
            "map",
            "lead",
            "Make a map of the research question"
            if not maps
            else "Add tickets to the map",
            "Work is organised as question tickets on a map; without them there is no frontier.",
            commands=[
                'obs map new "<the research question>" -d "<what a finished answer looks like>"',
                'obs q add M-0001 "<sharp sub-question>" -k research   # 3-8 tickets',
                'obs q add M-0001 "<scope question only the user can decide>" -k grilling',
                'obs map fog M-0001 "<question you cannot phrase sharply yet>"',
            ],
            gate="rsx gate map",
        )
    ]


def s_grilling(x: Ctx) -> list[Action]:
    qs = [q for q in wayfinder.frontier(x.vault) if q.fm.get("kind") == "grilling"]
    if not qs:
        return []
    return [
        Action(
            "grilling",
            "human",
            f"Ask the user {len(qs)} question(s)",
            "Only the user answers grilling tickets. Ask, stop, wait; record their words verbatim.",
            items=[q.id for q in qs],
            commands=[f"# {q.id}: {q.title}" for q in qs]
            + [
                'obs q answer Q-… --gist "…" --human-said "<their exact words>" --by lead'
            ],
            gate="rsx gate grilling",
        )
    ]


def s_sync(x: Ctx) -> list[Action]:
    missing = [k for k in bib_keys(x.project) if k not in x.papers]
    if not missing:
        return []
    return [
        Action(
            "sync",
            "lead",
            f"Import {len(missing)} new paper(s) from refs.bib",
            "Zotero has papers the vault does not know yet.",
            items=missing,
            commands=[f"obs paper sync {x.bib_rel}"],
            gate="rsx gate sync",
        )
    ]


def s_screen(x: Ctx) -> list[Action]:
    todo = []
    for k, p in x.papers.items():
        s = p.fm.get("screening", "pending")
        if s == "pending":
            todo.append(k)
        elif not CRITERION.match(str(p.fm.get("screening_reason", ""))):
            todo.append(k)  # decided, but without naming a criterion
    if not todo:
        return []
    return [
        Action(
            "screen",
            "lit-reader",
            f"Screen {len(todo)} paper(s) against the protocol",
            "Only included papers are read and cited; each decision names a criterion (I1, E2, ...).",
            items=todo,
            commands=[
                "cat vault/protocol.md",
                "obs show KEY",
                'obs paper screen KEY --include --reason "I1: …" --by lit-reader',
                'obs paper screen KEY --exclude --reason "E2: …" --by lit-reader',
            ],
            gate="rsx gate screen",
        )
    ]


def _included(x: Ctx) -> dict:
    return {k: p for k, p in x.papers.items() if p.fm.get("screening") == "included"}


def s_pdf(x: Ctx) -> list[Action]:
    no_pdf = [k for k, p in _included(x).items() if not has_pdf(x.vault, p)]
    if not no_pdf:
        return []
    return [
        Action(
            "pdf",
            "lit-scout",
            f"Get the PDF of {len(no_pdf)} included paper(s)",
            "A claim's quote is checked against the PDF; without it nothing can be extracted.",
            items=no_pdf,
            commands=[
                'zot search "<title>"   # is it in Zotero with a PDF?',
                "zot add DOI            # imports and fetches the PDF",
                f"obs paper sync {x.bib_rel}",
                'rsx unavailable KEY --reason "…" --by lit-scout  # no copy can be found',
            ],
            gate="rsx gate pdf",
        )
    ]


def s_notebook(x: Ctx) -> list[Action]:
    nb = x.project.notebook
    ready = {k: p for k, p in _included(x).items() if has_pdf(x.vault, p)}
    if not ready or nb == "none":
        return []
    if not nb:
        return [
            Action(
                "notebook",
                "human",
                "Give this project a Gemini Notebook (or decide to work without one)",
                "The notebook searches all PDFs at once for each question; its quotes "
                "are then looked up in the local PDFs. Only the user can create it.",
                commands=[
                    "# create an empty notebook at https://notebook.google.com, copy its URL",
                    "rsx notebook use URL",
                    "rsx notebook use none   # read the PDFs locally only",
                ],
                gate="rsx gate notebook",
            )
        ]
    push = [k for k, p in ready.items() if not p.fm.get("in_notebook")]
    if push:
        return [
            Action(
                "notebook",
                "lead",
                f"Add the PDFs of {len(push)} included paper(s) to the Gemini Notebook",
                "The notebook can only find what it holds.",
                items=push,
                commands=["rsx notebook push"],
                gate="rsx gate notebook",
            )
        ]
    papers = notebook.in_notebook(x.vault)
    ask = [q.id for q in search_questions(x.vault) if notebook.needs_asking(q, papers)]
    if not ask:
        return []
    return [
        Action(
            "notebook",
            "lead",
            f"Ask the Gemini Notebook {len(ask)} question(s)",
            "One query per question searches every paper; its quotes become leads "
            "for the readers, and papers it quotes nothing from go to the verifiers.",
            items=ask,
            commands=["rsx ask Q-…"],
            gate="rsx gate notebook",
        )
    ]


def extraction_problems(x: Ctx, key: str) -> list[str]:
    """Why paper KEY's extraction does not count as done (empty = done)."""
    p = x.papers.get(key)
    if p is None:
        return [f"{key} is not a paper in the vault"]
    if p.fm.get("screening") != "included":
        return []
    out = []
    ext = p.fm.get("extraction")
    claims = claims_of(x.vault, key)
    if not ext:
        out.append(f"{key}: not marked done; run `rsx extracted {key} --by lit-reader`")
    elif ext == "done" and not claims:
        out.append(f"{key}: marked done but has no claims")
    out += search_problems(x.vault, p)
    for c in claims:
        if c.fm.get("verification") == "rejected":
            continue  # the record of what the paper does not say
        if c.fm.get("quote_check") != "found":
            out.append(
                f"{c.id}: quote {c.fm.get('quote_check', 'unchecked')} in the PDF; copy it from `obs pdf-text`"
            )
    ids = {key, *(c.id for c in claims)}
    out += [
        f"{i['note']}: {i['msg']} -> {i['fix']}"
        for i in x.issues
        if i["level"] == "error" and i["note"] in ids
    ]
    return out


def s_extract(x: Ctx) -> list[Action]:
    todo = [
        k
        for k, p in _included(x).items()
        if has_pdf(x.vault, p) and extraction_problems(x, k)
    ]
    if not todo:
        return []
    return [
        Action(
            "extract",
            "lit-reader",
            f"Extract the claims of {len(todo)} paper(s)",
            "Findings only count as claims with a verbatim quote from the PDF. "
            "Each paper is searched for every question below. One reader per paper.",
            items=todo,
            commands=[f"# {q.id}: {q.title}" for q in search_questions(x.vault)]
            + [
                "rsx leads KEY   # what the notebook quoted from this paper, per question",
                "obs pdf-text KEY --grep WORD",
                'obs claim add -p KEY -s S-… -q "<exact sentence>" -r ROLE --by lit-reader',
                "rsx searched KEY Q-… --found C-… --by lit-reader     # per question",
                'rsx searched KEY Q-… --none --note "<words and pages searched>" --by lit-reader',
                "rsx extracted KEY --by lit-reader  # when the paper is done",
            ],
            gate="rsx gate extract --paper KEY",
            workflow={"script": "extract-verify.js", "args": {"papers": todo}},
        )
    ]


def s_verify(x: Ctx) -> list[Action]:
    todo: dict[str, list[str]] = {}
    for c in x.vault.of_type("claim"):
        if c.fm.get("verification", "unverified") == "unverified":
            todo.setdefault((c.links("paper") or ["?"])[0], []).append(c.id)
    nones = {k: unconfirmed_nones(x.vault, p) for k, p in x.papers.items()}
    nones = {k: qs for k, qs in nones.items() if qs}
    if not todo and not nones:
        return []
    papers = sorted({*todo, *nones})
    title = f"Verify {sum(map(len, todo.values()))} claim(s)"
    if nones:
        title += f" and {sum(map(len, nones.values()))} 'not in this paper' record(s)"
    return [
        Action(
            "verify",
            "lit-verifier",
            f"{title} of {len(papers)} paper(s)",
            "A different agent than the extractor checks every claim against its page, "
            "and searches the paper again where the reader or the notebook found nothing.",
            items=papers,
            commands=[
                "obs ls claim paper=KEY verification=unverified",
                "obs show C-…",
                "obs pdf-text KEY --page N",
                'obs verify C-… --verified|--rejected --by lit-verifier --note "<what the page says>"',
                "rsx leads KEY   # the notebook's quotes, and the ones found in no PDF",
            ]
            + [f"# {k}: found nothing for {', '.join(qs)}" for k, qs in nones.items()]
            + [
                'rsx confirm-none KEY Q-… --note "<words and pages you searched>" --by lit-verifier',
                'rsx confirm-none KEY Q-… --dispute --note "<page N says …>" --by lit-verifier',
            ],
            gate="rsx gate verify --paper KEY",
            workflow={
                "script": "extract-verify.js",
                "args": {"papers": papers, "skipExtract": True},
            },
        )
    ]


def open_hops(x: Ctx) -> tuple[dict, dict]:
    """Citations to chase: only for statements still lacking a verified origin."""
    missing: dict[str, set[str]] = {}
    unread: dict[str, set[str]] = {}
    for sid in unsupported_statements(x.vault):
        for hop in provenance.trace(x.vault, sid)["hops"]:
            target = hop["to"]
            if hop.get("status") == "missing-paper":
                missing.setdefault(target, set()).add(sid)
            elif hop.get("status") == "unchecked":
                t = x.vault.notes[target]
                if t.fm.get("screening") == "included" and sid not in (
                    t.fm.get("not_stated") or []
                ):
                    unread.setdefault(target, set()).add(sid)
    return missing, unread


def s_trace(x: Ctx) -> list[Action]:
    missing, unread = open_hops(x)
    if missing:
        return [
            Action(
                "trace-import",
                "lit-scout",
                f"Import {len(missing)} cited paper(s) to trace statements to their origin",
                "A restating claim cites a paper the vault does not have; the origin may be there.",
                items=sorted(missing),
                commands=[
                    f"# {k}: cited for {', '.join(sorted(s))}"
                    for k, s in sorted(missing.items())
                ]
                + [
                    "zot refs CITING_KEY        # DOIs the citing paper references",
                    "zot add DOI",
                    f"obs paper sync {x.bib_rel}",
                    "rsx relink OLD_KEY NEW_KEY  # if Better BibTeX chose another key",
                    'rsx unavailable KEY --reason "…" --by lit-scout  # no copy can be found',
                ],
                gate="rsx gate trace",
            )
        ]
    if unread:
        return [
            Action(
                "trace-read",
                "lit-reader",
                f"Read {len(unread)} cited paper(s) for the statements cited to them",
                "Does the cited paper really say it? Add its claim, or record that it does not.",
                items=sorted(unread),
                commands=[
                    f"# {k}: check {', '.join(sorted(s))}"
                    for k, s in sorted(unread.items())
                ]
                + [
                    "obs show S-…",
                    "obs pdf-text KEY --grep WORD",
                    'obs claim add -p KEY -s S-… -q "<exact sentence>" -r ROLE --by lit-reader',
                    'rsx not-in KEY S-… --note "<what the paper says instead>" --by lit-reader',
                ],
                gate="rsx gate trace",
            )
        ]
    return []


def s_answer(x: Ctx) -> list[Action]:
    work = [q for q in wayfinder.frontier(x.vault) if q.fm.get("kind") != "grilling"]
    by_role: dict[str, list] = {}
    for q in work:
        by_role.setdefault(KIND_ROLE.get(q.fm.get("kind"), "lead"), []).append(q)
    return [
        Action(
            "answer",
            role,
            f"Answer {len(qs)} question ticket(s)",
            "One ticket per agent session; answers link the claims or statements they rest on. "
            "A ticket with a Review section was blocked: fix what the critic found.",
            items=[q.id for q in qs],
            commands=[f"# {q.id} [{q.fm.get('kind')}]: {q.title}" for q in qs]
            + [
                f"obs q claim Q-… --by {role}",
                "obs show Q-…                 # read the Review section if there is one",
                "obs ls claim … ; obs trace S-… ; gnb ask …",
                f'obs q answer Q-… --gist "…" --text "…" --claim C-… --by {role}',
            ],
            gate="rsx gate answer --question Q-…",
            workflow={
                "script": "answer-review.js",
                "args": {"questions": [q.id for q in qs], "role": role},
            },
        )
        for role, qs in by_role.items()
    ]


def s_review(x: Ctx) -> list[Action]:
    todo = [
        q
        for q in x.vault.of_type("question")
        if q.fm.get("status") == "answered"
        and q.fm.get("kind") != "grilling"
        and review.question_review_state(q) != "current-ok"
    ]
    if not todo:
        return []
    return [
        Action(
            "review",
            "lit-critic",
            f"Review {len(todo)} answer(s)",
            "An answer counts only after a critic who did not write it has tried to break it.",
            items=[q.id for q in todo],
            commands=[
                "obs show Q-…",
                "obs show C-… ; obs trace S-…",
                'rsx review Q-… --ok|--block --note "<what you checked, what is wrong>" --by lit-critic',
            ],
            gate="rsx gate review --question Q-…",
            workflow={
                "script": "answer-review.js",
                "args": {"questions": [q.id for q in todo], "reviewOnly": True},
            },
        )
    ]


def s_stuck(x: Ctx) -> list[Action]:
    qs = [
        q
        for q in x.vault.of_type("question")
        if q.fm.get("status") not in wayfinder.CLOSED
    ]
    if not qs:
        return []
    return [
        Action(
            "stuck",
            "lead",
            f"{len(qs)} question(s) are open but none can be worked on",
            "They are claimed by an agent that stopped, or wait on blockers that will not close.",
            items=[q.id for q in qs],
            commands=[
                "obs map show M-0001",
                "obs q release Q-…   # a claimed ticket nobody works on",
                'obs q drop Q-… --reason "…"',
            ],
        )
    ]


def draft_check(x: Ctx) -> dict:
    from rsx import cite

    if not x.project.doc.exists():
        return {"verdict": "blocked", "errors": 1, "cited": [], "issues": []}
    return cite.check(x.vault, x.project.doc.read_text("utf-8"))


def s_write(x: Ctx) -> list[Action]:
    d = review.draft_state(x.project)
    check = draft_check(x)
    if check["cited"] and check["verdict"] == "pass" and d["submitted"]:
        if d["review"] != "blocked":
            return []
    rel_doc = x.project.rel(x.project.doc)
    if not check["cited"]:
        title, why = (
            "Write the draft",
            (
                "The questions are answered and reviewed; write the draft from their answers."
            ),
        )
    elif d["review"] == "blocked":
        title, why = (
            "Revise the draft",
            f"{d['review_file']} blocked it: fix every finding.",
        )
    elif d["last_review_verdict"] == "blocked" and not d["submitted"]:
        title, why = (
            "Revise the draft",
            f"{d['last_review_file']} blocked the last version.",
        )
    else:
        title, why = (
            "Finish the draft",
            "It does not pass `rsx cite-check` or was not submitted.",
        )
    return [
        Action(
            "write",
            "lit-writer",
            title,
            why,
            items=[rel_doc],
            commands=[
                "obs map show M-0001          # answered questions = the outline",
                "obs show Q-…                 # each answer and its claims",
                f"rsx cite-check {rel_doc}",
                f"typst compile {rel_doc}",
                "rsx draft submit --by lit-writer",
            ],
            gate="rsx gate write",
            workflow={"script": "write-review.js", "args": {}},
        )
    ]


def s_draft_review(x: Ctx) -> list[Action]:
    d = review.draft_state(x.project)
    if not d["submitted"] or d["review"] is not None:
        return []
    rel_doc = x.project.rel(x.project.doc)
    return [
        Action(
            "draft-review",
            "lit-critic",
            "Review the draft",
            "Every sentence must follow from the claims it names, at their strength.",
            items=[rel_doc],
            commands=[
                f"cat {rel_doc}",
                "obs show C-…                 # the quote behind each sentence",
                "rsx draft review --ok|--block --finding 'line N: problem -> fix' ... --by lit-critic",
            ],
            gate="rsx gate draft",
            workflow={"script": "write-review.js", "args": {"reviewOnly": True}},
        )
    ]


# stage order = the method; `rsx next` returns the first stage with work
STAGES = [
    ("fix", s_fix),
    ("protocol", s_protocol),
    ("map", s_map),
    ("grilling", s_grilling),
    ("sync", s_sync),
    ("screen", s_screen),
    ("notebook", s_notebook),
    ("extract", s_extract),
    ("pdf", s_pdf),
    ("verify", s_verify),
    ("trace", s_trace),
    ("answer", s_answer),
    ("review", s_review),
    ("stuck", s_stuck),
    ("write", s_write),
    ("draft-review", s_draft_review),
]


def plan(project: Project, ctx: Ctx | None = None) -> list[Action]:
    x = ctx or Ctx.of(project)
    for name, stage in STAGES:
        actions = stage(x)
        if name == "extract":
            # PDFs can be fetched while other papers are read
            actions += s_pdf(x)
        elif name == "pdf":
            continue
        if actions:
            return [a.specialised() for a in actions]
    d = review.draft_state(project)
    return [
        Action(
            "done",
            "lead",
            "The draft is written, checked and reviewed",
            f"Report to the user: {project.rel(project.doc)}, review {d['review_file']}. "
            "New questions start new tickets on the map.",
            items=[project.rel(project.doc)],
        )
    ]
