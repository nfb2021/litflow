"""Stage gates: one JSON verdict per stage, for workflow gates and for agents.

`rsx gate STAGE` runs that stage's check alone, whatever the other stages say,
and prints {"verdict": "pass" | "blocked", "stage", "issues": [...]}. It exits
0 either way: the verdict is data (pi-subagents typed gates read stdout).
"""

from __future__ import annotations

import shutil
import subprocess

from obs import wayfinder

from rsx import plan, review
from rsx.plan import Ctx

GATES = (
    "vault",
    "protocol",
    "map",
    "grilling",
    "sync",
    "screen",
    "pdf",
    "extract",
    "verify",
    "trace",
    "answer",
    "review",
    "write",
    "draft",
    "all",
)


def _from_actions(actions: list[plan.Action], item: str | None) -> list[str]:
    out = []
    for a in actions:
        items = a.items or [""]
        if item is not None and item not in items:
            continue
        shown = [item] if item else a.items[:20]
        out.append(
            f"{a.title}: {', '.join(shown)}" if shown and shown != [""] else a.title
        )
        out += a.commands[:6]
    return out


def compile_doc(x: Ctx) -> list[str]:
    typst = shutil.which("typst")
    if not typst:
        return ["typst is not installed: brew install typst"]
    out = x.project.root / ".rsx" / "draft.pdf"
    out.parent.mkdir(exist_ok=True)
    r = subprocess.run(
        [typst, "compile", "--root", str(x.project.root), str(x.project.doc), str(out)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        return ["typst compile failed:", *r.stderr.strip().splitlines()[:15]]
    return []


def gate(
    x: Ctx, stage: str, paper: str | None = None, question: str | None = None
) -> dict:
    if stage not in GATES:
        raise ValueError(f"unknown gate {stage!r}; one of {', '.join(GATES)}")
    issues: list[str] = []
    extra: dict = {}
    if stage in ("vault", "all"):
        issues += _from_actions(plan.s_fix(x), None)
    if stage == "all":
        nxt = plan.plan(x.project, x)[0]
        extra["next"] = nxt.to_dict()
        if nxt.stage != "done":
            issues.append(f"not done: next is {nxt.stage} ({nxt.title})")
    elif stage == "protocol":
        issues += _from_actions(plan.s_protocol(x), None)
    elif stage == "map":
        issues += _from_actions(plan.s_map(x), None)
    elif stage == "grilling":
        issues += _from_actions(plan.s_grilling(x), None)
        issues += [
            f"{i['note']}: {i['msg']}"
            for i in x.issues
            if i["code"] == "agent-answered-grilling"
        ]
    elif stage == "sync":
        issues += _from_actions(plan.s_sync(x), None)
    elif stage == "screen":
        issues += _from_actions(plan.s_screen(x), paper)
    elif stage == "pdf":
        issues += _from_actions(plan.s_pdf(x), paper)
    elif stage == "extract":
        keys = [paper] if paper else [a for s in plan.s_extract(x) for a in s.items]
        for k in keys:
            issues += plan.extraction_problems(x, k)
        if paper:
            extra["claims"] = [c.id for c in plan.claims_of(x.vault, paper)]
    elif stage == "verify":
        issues += _from_actions(plan.s_verify(x), paper)
        issues += [
            f"{i['note']}: {i['msg']} -> {i['fix']}"
            for i in x.issues
            if i["code"] in ("self-verified", "verified-by-nobody")
        ]
    elif stage == "trace":
        issues += _from_actions(plan.s_trace(x), paper)
    elif stage == "answer":
        qs = [question] if question else [i for a in plan.s_answer(x) for i in a.items]
        for qid in qs:
            q = x.vault.notes.get(qid)
            if q is None or q.type != "question":
                issues.append(f"{qid} is not a question")
            elif q.fm.get("status") not in wayfinder.CLOSED:
                issues.append(
                    f"{qid} is {q.fm.get('status', 'open')}: answer it with `obs q answer {qid} ...`"
                )
    elif stage == "review":
        qs = [question] if question else [i for a in plan.s_review(x) for i in a.items]
        states = {}
        for qid in qs:
            q = x.vault.notes.get(qid)
            if q is None or q.type != "question":
                issues.append(f"{qid} is not a question")
                continue
            st = review.question_review_state(q)
            states[qid] = st
            if st in ("none", "stale"):
                issues.append(
                    f"{qid}: no review of the current answer; `rsx review {qid} --ok|--block ...`"
                )
        extra["reviews"] = states
    elif stage == "write":
        check = plan.draft_check(x)
        issues += [
            f"line {i['line']}: {i['code']}: {i['msg']} -> {i['fix']}"
            for i in check.get("issues", [])
            if i["level"] == "error"
        ]
        if not check["cited"]:
            issues.append("the draft cites nothing yet")
        if not issues and x.project.doc.exists():
            issues += compile_doc(x)
        d = review.draft_state(x.project)
        if not issues and not d["submitted"]:
            issues.append("checks pass; submit it: `rsx draft submit --by lit-writer`")
        extra["warnings"] = [
            f"line {i['line']}: {i['msg']}"
            for i in check.get("issues", [])
            if i["level"] == "warning"
        ]
    elif stage == "draft":
        d = review.draft_state(x.project)
        if not d["submitted"]:
            issues.append("the current draft was not submitted")
        elif d["review"] is None:
            issues.append("no review of the current draft: `rsx draft review ...`")
        extra["review"] = d["review"]
        extra["review_file"] = d["review_file"]
    return {
        "verdict": "blocked" if issues else "pass",
        "stage": stage,
        **({"paper": paper} if paper else {}),
        **({"question": question} if question else {}),
        **extra,
        "issues": issues[:60],
    }
