"""Reviews: the critic's verdict on an answered question and on a draft.

A review is tied to a hash of what it reviewed. Change the answer or the draft
and the review no longer counts: the work goes back to the critic.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from obs.vault import Note, Vault, get_section, set_section

from rsx.project import Project

VERDICTS = ("ok", "blocked")


class ReviewError(Exception):
    """A refused review: wrong state, self-review, missing note."""


def today() -> str:
    return dt.date.today().isoformat()


def answer_hash(q: Note) -> str:
    """What the critic reviews: the answer text and the evidence it links."""
    payload = json.dumps(
        [
            get_section(q.body, "Answer"),
            q.fm.get("gist", ""),
            sorted(q.links("claims")),
            sorted(q.links("statements")),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def question_review_state(q: Note) -> str:
    """none | current-ok | current-blocked | stale (answer changed since)."""
    rev = q.fm.get("review")
    if not rev:
        return "none"
    if q.fm.get("status") != "answered":
        return "current-blocked" if rev == "blocked" else "stale"
    if q.fm.get("review_of") != answer_hash(q):
        return "stale"
    return f"current-{rev}"


def review_question(
    vault: Vault, question: str, verdict: str, note: str, by: str
) -> Note:
    if verdict not in VERDICTS:
        raise ReviewError(f"verdict must be one of {', '.join(VERDICTS)}")
    q = vault.get(question, "question")
    if q.fm.get("kind") == "grilling":
        raise ReviewError(f"{q.id} is a grilling question: the user's answer stands")
    if q.fm.get("status") != "answered":
        raise ReviewError(f"{q.id} is {q.fm.get('status', 'open')}, not answered")
    author = q.fm.get("recorded_by") or q.fm.get("answered_by")
    if author and author == by:
        raise ReviewError(
            f"{q.id} was answered by {by}; a different agent must review it"
        )
    if not note.strip():
        raise ReviewError("--note is required: what you checked and what you found")
    q.fm.update(
        {
            "review": verdict,
            "reviewed_by": by,
            "reviewed": today(),
            "review_of": answer_hash(q),
        }
    )
    stamp = f"- {today()} {by}: **{verdict}**. {note.strip()}"
    log = get_section(q.body, "Review")
    q.body = set_section(q.body, "Review", (log + "\n" + stamp).strip())
    if verdict == "blocked":
        # back to the frontier; the answerer reads the review section
        q.fm["status"] = "open"
        q.fm.pop("claimed_by", None)
    vault.save(q)
    return q


# --- drafts -------------------------------------------------------------------
def _records(project: Project) -> list[dict]:
    out = []
    if project.reviews.exists():
        for p in sorted(project.reviews.glob("*.md")):
            m = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", p.read_text("utf-8"), re.S)
            if not m:
                continue
            fm = {}
            for line in m.group(1).splitlines():
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
            fm["file"] = project.rel(p)
            fm["body"] = m.group(2).strip()
            out.append(fm)
    return out


def _write(project: Project, kind: str, fm: dict, body: str) -> str:
    project.reviews.mkdir(parents=True, exist_ok=True)
    n = len(list(project.reviews.glob("*.md"))) + 1
    path = project.reviews / f"{n:03d}-{kind}.md"
    head = "\n".join(f"{k}: {v}" for k, v in fm.items())
    path.write_text(f"---\n{head}\n---\n\n{body.strip()}\n", "utf-8")
    return project.rel(path)


def draft_state(project: Project) -> dict:
    """The draft's submission and review state for its current text."""
    h = project.doc_hash()
    recs = [r for r in _records(project) if r.get("doc_hash") == h]
    subs = [r for r in recs if r.get("kind") == "submission"]
    revs = [r for r in recs if r.get("kind") == "review"]
    last_review = next(
        (r for r in reversed(_records(project)) if r.get("kind") == "review"), None
    )
    return {
        "doc_hash": h,
        "submitted": bool(subs),
        "author": subs[-1]["by"] if subs else None,
        "review": revs[-1]["verdict"] if revs else None,
        "review_file": revs[-1]["file"] if revs else None,
        "last_review_file": last_review["file"] if last_review else None,
        "last_review_verdict": last_review["verdict"] if last_review else None,
    }


def submit_draft(project: Project, by: str, check: dict) -> str:
    if check["verdict"] != "pass":
        raise ReviewError(
            f"the draft does not pass the checks ({check['errors']} errors): run `rsx cite-check`"
        )
    return _write(
        project,
        "submission",
        {
            "kind": "submission",
            "by": by,
            "date": today(),
            "doc_hash": project.doc_hash(),
        },
        f"Cites {len(check['cited'])} papers through {len(check['claims'])} claims.",
    )


def review_draft(project: Project, verdict: str, findings: str, by: str) -> str:
    if verdict not in VERDICTS:
        raise ReviewError(f"verdict must be one of {', '.join(VERDICTS)}")
    st = draft_state(project)
    if not st["submitted"]:
        raise ReviewError(
            "this version of the draft was not submitted (`rsx draft submit`); "
            "it changed after submission or was never checked"
        )
    if st["author"] == by:
        raise ReviewError(
            f"the draft was submitted by {by}; a different agent reviews it"
        )
    if not findings.strip():
        raise ReviewError("findings are required (--file or --text)")
    return _write(
        project,
        "review",
        {
            "kind": "review",
            "verdict": verdict,
            "by": by,
            "date": today(),
            "doc_hash": st["doc_hash"],
        },
        findings,
    )
