"""Vault checks. Errors break the research rules; warnings are open work."""

from __future__ import annotations

from obs import provenance
from obs.vault import (
    DRIFT,
    HUMAN_KINDS,
    LINK_FIELDS,
    Q_KINDS,
    Q_STATUS,
    ROLES,
    SCREENING,
    TYPES,
    VERIFICATION,
    Vault,
    seal_of,
)


def _issue(level: str, code: str, note: str, msg: str, fix: str = "") -> dict:
    return {"level": level, "code": code, "note": note, "msg": msg, "fix": fix}


def lint(vault: Vault) -> list[dict]:
    out: list[dict] = []
    notes = vault.notes
    for path, msg in vault.errors:
        out.append(
            _issue(
                "error",
                "unreadable",
                str(path.relative_to(vault.root)),
                msg,
                "fix the YAML between the --- lines",
            )
        )

    for n in notes.values():
        if n.type not in TYPES:
            out.append(
                _issue(
                    "error",
                    "unknown-type",
                    n.id,
                    f"type {n.type!r}",
                    f"use one of {', '.join(TYPES)}",
                )
            )
            continue
        if n.fm.get("id") not in (None, n.id):
            out.append(
                _issue(
                    "error",
                    "id-mismatch",
                    n.id,
                    f"frontmatter id {n.fm['id']!r} differs from the file name",
                    "rename the file or fix `id`",
                )
            )
        seal = seal_of(n.type, n.fm, n.body)
        if seal and n.fm.get("seal") != seal:
            out.append(
                _issue(
                    "error",
                    "hand-edited",
                    n.id,
                    "written or changed outside obs, so its checks no longer hold"
                    if n.fm.get("seal")
                    else "has no seal: written outside obs",
                    f"redo it with the obs command (claim add / verify / q answer), or `obs reseal {n.id} --by WHO`, which sends it back to be checked",
                )
            )
        for f in LINK_FIELDS[n.type]:
            for t in n.links(f):
                if t not in notes:
                    level = (
                        "warning" if (n.type == "claim" and f == "cites") else "error"
                    )
                    out.append(
                        _issue(
                            level,
                            "broken-link",
                            n.id,
                            f"{f} -> [[{t}]] does not exist",
                            "create the note or fix the link",
                        )
                    )

    for c in vault.of_type("claim"):
        role, ver = c.fm.get("role"), c.fm.get("verification", "unverified")
        if not c.links("paper"):
            out.append(
                _issue(
                    "error",
                    "claim-no-paper",
                    c.id,
                    "claim has no paper",
                    "every claim belongs to exactly one paper",
                )
            )
        if not c.links("statement"):
            out.append(
                _issue(
                    "error",
                    "claim-no-statement",
                    c.id,
                    "claim has no statement",
                    "link it to a statement (obs statement add)",
                )
            )
        if not str(c.fm.get("quote") or "").strip():
            out.append(
                _issue(
                    "error",
                    "claim-no-quote",
                    c.id,
                    "claim has no verbatim quote",
                    "copy the sentence from the paper",
                )
            )
        if c.fm.get("page") in (None, "") and ver != "rejected":
            out.append(
                _issue(
                    "warning",
                    "claim-no-page",
                    c.id,
                    "claim has no page",
                    "add the page the quote is on",
                )
            )
        if role not in ROLES:
            out.append(
                _issue(
                    "error",
                    "claim-role",
                    c.id,
                    f"role {role!r}",
                    f"use one of {', '.join(ROLES)}",
                )
            )
        if role == "restates" and not c.fm.get("cites"):
            out.append(
                _issue(
                    "error",
                    "restates-no-cites",
                    c.id,
                    "role restates but cites nothing",
                    "add what the paper cites for it, or use restates-uncited",
                )
            )
        if c.fm.get("drift", "none") not in DRIFT:
            out.append(
                _issue(
                    "error",
                    "claim-drift",
                    c.id,
                    f"drift {c.fm.get('drift')!r}",
                    f"use one of {', '.join(DRIFT)}",
                )
            )
        if ver not in VERIFICATION:
            out.append(
                _issue(
                    "error",
                    "claim-verification",
                    c.id,
                    f"verification {ver!r}",
                    f"use one of {', '.join(VERIFICATION)}",
                )
            )
        qc = c.fm.get("quote_check")
        if ver == "rejected":
            continue  # kept as the record of what the paper does not say
        if qc == "not-found":
            out.append(
                _issue(
                    "error",
                    "quote-not-found",
                    c.id,
                    "quote not found in the PDF",
                    "copy the exact wording from the PDF, or reject the claim",
                )
            )
        elif qc is None:
            out.append(
                _issue(
                    "warning",
                    "quote-unchecked",
                    c.id,
                    "quote not checked against the PDF",
                    f"obs check-quotes {c.id}",
                )
            )
        if ver == "unverified":
            out.append(
                _issue(
                    "warning",
                    "claim-unverified",
                    c.id,
                    "not yet verified by an independent reviewer",
                    "a verifier runs obs verify",
                )
            )
        if ver == "verified" and not c.fm.get("verified_by"):
            out.append(
                _issue(
                    "error",
                    "verified-by-nobody",
                    c.id,
                    "verified but `verified_by` is empty",
                    "obs verify sets it",
                )
            )
        if (
            ver == "verified"
            and c.fm.get("verified_by") == c.fm.get("extracted_by")
            and c.fm.get("extracted_by")
        ):
            out.append(
                _issue(
                    "error",
                    "self-verified",
                    c.id,
                    f"verified by its own extractor ({c.fm['verified_by']})",
                    "a different agent must verify",
                )
            )
        for p in c.links("paper"):
            paper = notes.get(p)
            if paper and paper.fm.get("screening") == "excluded":
                out.append(
                    _issue(
                        "error",
                        "claim-from-excluded",
                        c.id,
                        f"{p} is excluded by screening",
                        "delete the claim or revisit the screening",
                    )
                )

    for p in vault.of_type("paper"):
        s = p.fm.get("screening", "pending")
        if s not in SCREENING:
            out.append(
                _issue(
                    "error",
                    "paper-screening",
                    p.id,
                    f"screening {s!r}",
                    f"use one of {', '.join(SCREENING)}",
                )
            )
        if s == "excluded" and not p.fm.get("screening_reason"):
            out.append(
                _issue(
                    "error",
                    "excluded-no-reason",
                    p.id,
                    "excluded without a reason",
                    "obs paper screen KEY --exclude --reason 'criterion'",
                )
            )
        if s == "pending":
            out.append(
                _issue(
                    "warning",
                    "paper-unscreened",
                    p.id,
                    "not screened yet",
                    "obs paper screen",
                )
            )
        if s == "included" and not any(
            n.type == "claim" for n, _ in vault.backlinks(p.id)
        ):
            out.append(
                _issue(
                    "warning",
                    "paper-no-claims",
                    p.id,
                    "included but no claims extracted",
                    "extract its claims",
                )
            )
        if s == "included" and not p.fm.get("pdf"):
            out.append(
                _issue(
                    "warning",
                    "paper-no-pdf",
                    p.id,
                    "no PDF path, quotes cannot be checked",
                    "zot pdfs, or set `pdf`",
                )
            )

    for st in vault.of_type("statement"):
        t = provenance.trace(vault, st.id)
        if t["claims"] == 0:
            out.append(
                _issue(
                    "warning",
                    "statement-no-claims",
                    st.id,
                    "no paper asserts it yet",
                    "find a source or delete the statement",
                )
            )
        elif t["verdict"] == "unsupported":
            out.append(
                _issue(
                    "warning",
                    "statement-unsupported",
                    st.id,
                    "no verified origin claim",
                    f"obs trace {st.id}",
                )
            )
        for prob in t["problems"]:
            if prob["kind"] == "circular-citation":
                out.append(
                    _issue(
                        "error",
                        "circular-citation",
                        st.id,
                        prob["detail"],
                        "find the paper that actually shows it",
                    )
                )
            elif prob["kind"] == "citation-does-not-support":
                out.append(
                    _issue(
                        "warning",
                        "citation-does-not-support",
                        prob["claim"],
                        prob["detail"],
                        "mark the claim drift=changed or reject it",
                    )
                )
            elif prob["kind"] in ("unchecked-hop", "missing-paper"):
                out.append(
                    _issue("warning", prob["kind"], prob["claim"], prob["detail"])
                )

    questions = vault.of_type("question")
    for q in questions:
        kind, status = q.fm.get("kind"), q.fm.get("status", "open")
        if kind not in Q_KINDS:
            out.append(
                _issue(
                    "error",
                    "question-kind",
                    q.id,
                    f"kind {kind!r}",
                    f"use one of {', '.join(Q_KINDS)}",
                )
            )
        if status not in Q_STATUS:
            out.append(
                _issue(
                    "error",
                    "question-status",
                    q.id,
                    f"status {status!r}",
                    f"use one of {', '.join(Q_STATUS)}",
                )
            )
        if (
            status == "answered"
            and kind in HUMAN_KINDS
            and q.fm.get("answered_by") != "human"
        ):
            out.append(
                _issue(
                    "error",
                    "agent-answered-grilling",
                    q.id,
                    "a grilling question was answered without the human",
                    "ask the user; record it with obs q answer --human-said",
                )
            )
        if (
            status == "answered"
            and kind in ("research", "query", "falsify")
            and not (q.fm.get("claims") or q.fm.get("statements"))
        ):
            out.append(
                _issue(
                    "error",
                    "answer-without-evidence",
                    q.id,
                    f"{kind} answer cites no claims or statements",
                    "link the claims the answer rests on",
                )
            )
        if status == "out-of-scope" and not q.fm.get("reason"):
            out.append(
                _issue(
                    "error",
                    "out-of-scope-no-reason",
                    q.id,
                    "ruled out of scope without a reason",
                    "obs q drop Q --reason",
                )
            )
    for cyc in _blocked_cycles(questions):
        out.append(
            _issue(
                "error",
                "blocked-cycle",
                cyc[0],
                " -> ".join([*cyc, cyc[0]]),
                "remove one blocked_by edge",
            )
        )
    return out


def _blocked_cycles(questions):
    graph = {q.id: set(q.links("blocked_by")) for q in questions}
    return provenance._cycles(graph)


def summary(issues: list[dict]) -> dict:
    errors = sum(i["level"] == "error" for i in issues)
    warnings = sum(i["level"] == "warning" for i in issues)
    return {"errors": errors, "warnings": warnings}
