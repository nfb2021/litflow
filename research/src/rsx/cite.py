"""Check a Typst draft against the vault.

Typst itself fails on a cite key missing from refs.bib. This checks what Typst
cannot know: every cited paper is screened in and has verified claims, and every
paragraph that cites a paper names (in a `// C-0001` comment) the verified
claims of that paper it rests on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from obs import provenance
from obs.vault import Vault

KEY = r"[A-Za-z0-9_][A-Za-z0-9_:.\-]*"
# as in Typst: any @key is a reference (an e-mail too); only \@ is literal
AT_CITE = re.compile(rf"(?<![\\@])@({KEY})")
FN_CITE = re.compile(rf"#cite\(\s*(?:<({KEY})>|label\(\s*\"({KEY})\"\s*\))")
LABEL_DEF = re.compile(rf"<({KEY})>")
CLAIM_ID = re.compile(r"\bC-\d{4,}\b")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
RAW_BLOCK = re.compile(r"```.*?```", re.S)
RAW_INLINE = re.compile(r"`[^`\n]*`")
LINE_COMMENT = re.compile(r"(?<!:)//(.*)$", re.M)


@dataclass
class Paragraph:
    line: int
    text: str  # without comments
    cites: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)


def _issue(level: str, code: str, line: int, msg: str, fix: str = "") -> dict:
    return {"level": level, "code": code, "line": line, "msg": msg, "fix": fix}


def _strip_key(k: str) -> str:
    # "@key." at a sentence end, "@key:" before a colon
    return k.rstrip(".:-")


def paragraphs(source: str) -> tuple[list[Paragraph], set[str]]:
    """Split the draft into paragraphs; collect cites and claim ids of each."""

    # keep line numbers: blank out what we drop instead of deleting it
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = RAW_BLOCK.sub(blank, BLOCK_COMMENT.sub(blank, source))
    labels: set[str] = set()
    out: list[Paragraph] = []
    cur: Paragraph | None = None
    for no, raw in enumerate(text.splitlines(), 1):
        comment = LINE_COMMENT.search(raw)
        code = raw[: comment.start()] if comment else raw
        code = RAW_INLINE.sub(lambda m: " " * len(m.group(0)), code)
        stripped = code.strip()
        if stripped.startswith(("#set", "#show", "#import", "#bibliography", "#let")):
            cur = None
            continue
        if not stripped:
            # a comment-only line belongs to the paragraph above it;
            # a blank line ends the paragraph
            if comment and cur is not None:
                cur.claims += CLAIM_ID.findall(comment.group(1))
            elif not comment:
                cur = None
            continue
        if stripped.startswith("="):
            cur = None  # a heading is its own paragraph
        if cur is None:
            cur = Paragraph(line=no, text="")
            out.append(cur)
        no_fn = FN_CITE.sub(" ", stripped)
        for m in FN_CITE.finditer(stripped):
            cur.cites.append(m.group(1) or m.group(2))
        labels.update(LABEL_DEF.findall(no_fn))
        cur.cites += [_strip_key(k) for k in AT_CITE.findall(no_fn)]
        cur.text += " " + stripped
        if comment:
            cur.claims += CLAIM_ID.findall(comment.group(1))
        if stripped.startswith("="):
            cur = None
    for p in out:
        p.cites = [c for c in dict.fromkeys(p.cites) if c not in labels]
        p.claims = list(dict.fromkeys(p.claims))
    return [p for p in out if p.text.strip()], labels


def check(vault: Vault, source: str, require_claims: bool = True) -> dict:
    paras, _ = paragraphs(source)
    notes = vault.notes
    issues: list[dict] = []
    cited_keys: list[str] = []
    for p in paras:
        cited_keys += p.cites
        for key in p.cites:
            paper = notes.get(key)
            if paper is None or paper.type != "paper":
                issues.append(
                    _issue(
                        "error",
                        "cite-not-in-vault",
                        p.line,
                        f"@{key} is not a paper in the vault",
                        "add it with `zot add DOI`, then `obs paper sync refs.bib`; or fix the key",
                    )
                )
                continue
            screening = paper.fm.get("screening", "pending")
            if screening != "included":
                issues.append(
                    _issue(
                        "error",
                        "cite-not-included",
                        p.line,
                        f"@{key} is {screening} in screening",
                        f"screen it (`obs paper screen {key} ...`) or do not cite it",
                    )
                )
            verified = [
                c
                for c in vault.of_type("claim")
                if key in c.links("paper") and c.fm.get("verification") == "verified"
            ]
            if not verified:
                issues.append(
                    _issue(
                        "error",
                        "cite-no-verified-claim",
                        p.line,
                        f"@{key} has no verified claim",
                        f"extract and verify its claims first (`obs ls claim paper={key}`)",
                    )
                )
        backed: set[str] = set()
        for cid in p.claims:
            c = notes.get(cid)
            if c is None or c.type != "claim":
                issues.append(
                    _issue(
                        "error",
                        "claim-unknown",
                        p.line,
                        f"{cid} is not a claim",
                        "use the id from `obs ls claim`",
                    )
                )
                continue
            ver = c.fm.get("verification", "unverified")
            if ver != "verified":
                issues.append(
                    _issue(
                        "error",
                        "claim-not-verified",
                        p.line,
                        f"{cid} is {ver}",
                        "only verified claims may back a sentence",
                    )
                )
            paper = (c.links("paper") or [""])[0]
            backed.add(paper)
            if paper not in p.cites:
                issues.append(
                    _issue(
                        "error",
                        "claim-paper-not-cited",
                        p.line,
                        f"{cid} is from {paper}, which this paragraph does not cite",
                        f"cite @{paper} in the sentence the claim backs",
                    )
                )
            if c.fm.get("role") in ("restates", "restates-uncited"):
                st = (c.links("statement") or [""])[0]
                if st in notes:
                    origins = [
                        o
                        for o in provenance.trace(vault, st)["origins"]
                        if o not in p.cites
                    ]
                    if origins:
                        issues.append(
                            _issue(
                                "warning",
                                "cites-restating-paper",
                                p.line,
                                f"{cid}: {paper} only restates {st}; it was shown by {', '.join(origins)}",
                                f"cite the origin (@{origins[0]}) and use its claim",
                            )
                        )
        if require_claims:
            for key in p.cites:
                if key not in backed and key in notes:
                    issues.append(
                        _issue(
                            "error",
                            "citation-without-claim",
                            p.line,
                            f"@{key} is cited but no claim of it is named",
                            f"end the sentence with `// C-…`, a verified claim of {key} (`obs ls claim paper={key} verification=verified`)",
                        )
                    )
    errors = sum(i["level"] == "error" for i in issues)
    return {
        "verdict": "blocked" if errors else "pass",
        "errors": errors,
        "warnings": len(issues) - errors,
        "paragraphs": len(paras),
        "cited": sorted(set(cited_keys)),
        "claims": sorted({c for p in paras for c in p.claims}),
        "issues": issues,
    }
