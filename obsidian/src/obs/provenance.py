"""Trace where a statement comes from through the papers that assert it.

A claim is one paper asserting a statement. `restates` claims cite other papers
for it; following those citations gives a provenance graph per statement.
Support is counted in *independent* sources: papers whose verified claim is an
`origin` (they show it themselves). Repetition adds reach, not evidence.
"""

from __future__ import annotations

from obs.vault import Note, Vault, link_target


def cited(claim: Note) -> list[str]:
    """Cited ids/strings of a claim: '[[key]]' -> key, 'doi:..' kept as is."""
    value = claim.fm.get("cites") or []
    values = value if isinstance(value, list) else [value]
    return [link_target(v) or str(v) for v in values if v]


def trace(vault: Vault, statement_id: str) -> dict:
    st = vault.get(statement_id, "statement")
    claims = [c for c in vault.of_type("claim") if st.id in c.links("statement")]
    by_paper: dict[str, list[Note]] = {}
    for c in claims:
        for p in c.links("paper"):
            by_paper.setdefault(p, []).append(c)

    def ok(c: Note) -> bool:
        return c.fm.get("verification") == "verified"

    origins = sorted(
        {
            p
            for p, cs in by_paper.items()
            if any(ok(c) and c.fm.get("role") == "origin" for c in cs)
        }
    )
    disputes = sorted(
        {
            p
            for p, cs in by_paper.items()
            if any(ok(c) and c.fm.get("role") == "disputes" for c in cs)
        }
    )

    hops, problems = [], []
    graph: dict[str, set[str]] = {}
    for c in claims:
        paper = (c.links("paper") or ["?"])[0]
        role = c.fm.get("role")
        if c.fm.get("verification") == "rejected":
            problems.append(
                {
                    "kind": "rejected-claim",
                    "claim": c.id,
                    "paper": paper,
                    "detail": c.fm.get("verify_note", ""),
                }
            )
        if c.fm.get("drift") not in (None, "none"):
            problems.append(
                {
                    "kind": "drift",
                    "claim": c.id,
                    "paper": paper,
                    "detail": c.fm["drift"],
                }
            )
        if role == "restates" and not cited(c):
            problems.append(
                {
                    "kind": "restates-without-citation",
                    "claim": c.id,
                    "paper": paper,
                    "detail": "role restates but no `cites`",
                }
            )
        for target in cited(c):
            graph.setdefault(paper, set()).add(target)
            hop = {"from": paper, "claim": c.id, "to": target}
            if target not in vault.notes:
                hop["status"] = "missing-paper"
                problems.append(
                    {
                        "kind": "missing-paper",
                        "claim": c.id,
                        "paper": paper,
                        "detail": f"cites {target}, not in the vault - add it, then extract its claim",
                    }
                )
            elif target not in by_paper:
                hop["status"] = "unchecked"
                problems.append(
                    {
                        "kind": "unchecked-hop",
                        "claim": c.id,
                        "paper": paper,
                        "detail": f"cites {target} for this, but {target} has no claim on {st.id} - read {target} and add its claim (or record that it does not say this)",
                    }
                )
            elif all(t.fm.get("verification") == "rejected" for t in by_paper[target]):
                hop["status"] = "not-in-cited"
                problems.append(
                    {
                        "kind": "citation-does-not-support",
                        "claim": c.id,
                        "paper": paper,
                        "detail": f"{target} was checked and does not support it",
                    }
                )
            else:
                hop["status"] = (
                    "ok" if any(ok(t) for t in by_paper[target]) else "unverified"
                )
            hops.append(hop)

    for cycle in _cycles(graph):
        problems.append(
            {
                "kind": "circular-citation",
                "claim": None,
                "paper": cycle[0],
                "detail": " -> ".join([*cycle, cycle[0]]),
            }
        )

    # papers the chains end in (cite nothing further for it) with an origin claim
    roots = sorted({p for p in by_paper if not graph.get(p)})
    if disputes and origins:
        verdict = "contested"
    elif origins:
        verdict = "supported"
    elif disputes:
        verdict = "disputed"
    else:
        verdict = "unsupported"
    return {
        "statement": st.id,
        "text": st.fm.get("text", ""),
        "verdict": verdict,
        "independent_sources": len(origins),
        "origins": origins,
        "disputes": disputes,
        "papers": len(by_paper),
        "claims": len(claims),
        "unverified_claims": sorted(
            c.id
            for c in claims
            if c.fm.get("verification", "unverified") == "unverified"
        ),
        "chain_ends": roots,
        "hops": hops,
        "problems": problems,
    }


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    seen_cycles, out = set(), []
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(n: str) -> None:
        state[n] = 1
        stack.append(n)
        for m in sorted(graph.get(n, ())):
            if state.get(m) == 1:
                cyc = stack[stack.index(m) :]
                k = frozenset(cyc)
                if k not in seen_cycles:
                    seen_cycles.add(k)
                    out.append(cyc)
            elif m not in state:
                visit(m)
        stack.pop()
        state[n] = 2

    for n in sorted(graph):
        if n not in state:
            visit(n)
    return out


def render(t: dict) -> str:
    lines = [
        f"{t['statement']}: {t['text']}",
        f"verdict: {t['verdict']}  |  independent sources: {t['independent_sources']}  |  papers: {t['papers']}  |  claims: {t['claims']}",
    ]
    if t["origins"]:
        lines.append("origins (verified): " + ", ".join(t["origins"]))
    if t["disputes"]:
        lines.append("disputed by (verified): " + ", ".join(t["disputes"]))
    if t["hops"]:
        lines.append("citation hops:")
        for h in t["hops"]:
            lines.append(f"  {h['from']} --{h['claim']}--> {h['to']}  [{h['status']}]")
    if t["unverified_claims"]:
        lines.append("unverified claims: " + ", ".join(t["unverified_claims"]))
    if t["problems"]:
        lines.append("problems:")
        for p in t["problems"]:
            where = p["claim"] or p["paper"]
            lines.append(f"  - {p['kind']} ({where}): {p['detail']}")
    return "\n".join(lines)
