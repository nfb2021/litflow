"""Citation snowball: from seed papers through their references, N levels deep.

A reader judges every reference of a paper against protocol.md, a verifier who
is not that reader confirms the judgement, and only then do the included
references become papers of the next level. Each DOI enters the snowball once:
it is imported into Zotero once and its references are judged once, so the
snowball ends when every paper above the chosen depth is judged and confirmed.

The state lives in the vault (vault/snowball.json) next to the log book it is
rendered into (vault/snowball.md): who cites whom, what was excluded and why,
and which references have no DOI. Paper notes get `snowball_cites` links, so
Obsidian's graph shows the citation network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from obs import bib

from rsx.project import Project

CROSSREF = "https://api.crossref.org/works/"
USER_AGENT = "rsx (https://github.com/nfb2021/litflow)"
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.I)
EXCLUDE_WHY = re.compile(r"^\s*E\d+\b")


class SnowballError(Exception):
    """A refused snowball step, with what to do instead."""


# Publishers (Wiley/AGU) deposit reference DOIs in Crossref with typographic
# hyphens; one DOI must have one key.
DASHES = dict.fromkeys(
    map(ord, "\u00ad\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-"
)


def norm(doi: str) -> str:
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi.strip(), flags=re.I)
    return doi.translate(DASHES).rstrip(".,;").lower()


def today() -> str:
    return date.today().isoformat()


# --- state -------------------------------------------------------------------


def state_path(p: Project) -> Path:
    return p.vault_dir / "snowball.json"


def load(p: Project) -> dict:
    f = state_path(p)
    s = json.loads(f.read_text("utf-8")) if f.exists() else {}
    s.setdefault("seeds", [])
    s["seeds"] = list(dict.fromkeys(map(norm, s["seeds"])))
    papers: dict = {}
    for k, v in s.get("papers", {}).items():
        for r in v.get("refs", {}).get("list", []):
            if r.get("doi"):
                r["doi"] = norm(r["doi"])
        k = norm(k)
        if k not in papers:
            papers[k] = v
            continue
        # a duplicate written before norm() knew the hyphen: merge into the first
        kept = papers[k]
        kept["depth"] = min(kept["depth"], v["depth"])
        kept["found_in"] = list(dict.fromkeys(kept["found_in"] + v["found_in"]))
        for f, x in v.items():
            kept.setdefault(f, x)
    s["papers"] = papers
    return s


def save(p: Project, s: dict) -> None:
    state_path(p).write_text(
        json.dumps(s, indent=1, ensure_ascii=False) + "\n", "utf-8"
    )
    render(p, s)


def depth_of(p: Project) -> int | None:
    return int(p.depth) if str(p.depth).strip().isdigit() else None


def seed(p: Project, dois: list[str]) -> list[str]:
    s = load(p)
    added = []
    for d in map(norm, dois):
        if not DOI_RE.match(d):
            raise SnowballError(f"not a DOI: {d}")
        if d not in s["papers"]:
            s["papers"][d] = {"depth": 0, "found_in": []}
            added.append(d)
        if d not in s["seeds"]:
            s["seeds"].append(d)
    save(p, s)
    return added


# --- Crossref ------------------------------------------------------------------


def work(p: Project, doi: str) -> dict:
    """Crossref's record of a DOI, cached in .rsx/crossref (RSX_CROSSREF_OFFLINE=1:
    cache only, for tests)."""
    cache = p.root / ".rsx" / "crossref"
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / (re.sub(r"[^\w.-]", "_", norm(doi)) + ".json")
    if not f.exists() and not os.environ.get("RSX_CROSSREF_OFFLINE"):
        url = CROSSREF + urllib.parse.quote(norm(doi), safe="/")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    f.write_text(r.read().decode("utf-8"), "utf-8")
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    f.write_text(json.dumps({"message": {"missing": True}}), "utf-8")
                    break
                time.sleep(3 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError):
                time.sleep(3 * (attempt + 1))
    if not f.exists():
        return {}
    return json.loads(f.read_text("utf-8")).get("message", {})


def describe(m: dict) -> str:
    """'Family YEAR Title. Journal' from a Crossref record."""
    au = ((m.get("author") or [{}])[0]).get("family", "")
    yr = (m.get("issued", {}).get("date-parts") or [[""]])[0][0]
    title = (m.get("title") or [""])[0]
    venue = (m.get("container-title") or [""])[0]
    return " ".join(
        str(x) for x in (au, yr, title + ("." if venue else ""), venue) if x
    )


def ref_text(r: dict) -> str:
    keys = ("author", "year", "article-title", "series-title", "volume-title")
    keys += ("journal-title", "unstructured")
    return " ".join(str(r[k]) for k in keys if r.get(k))


def references(p: Project, doi: str) -> tuple[str, list[dict]]:
    """(source, [{n, doi, text}]): Crossref's reference list, bare DOIs given their
    titles; else the DOIs in the PDF text (zot refs --source pdf)."""
    m = work(p, doi)
    out = []
    for i, r in enumerate(m.get("reference") or [], 1):
        d = norm(r["DOI"]) if r.get("DOI") else ""
        if not d:
            found = DOI_RE.search(r.get("unstructured", ""))
            d = norm(found.group(0)) if found else ""
        text = ref_text(r)
        if d and len(text) < 40:  # a bare DOI: name it
            text = describe(work(p, d)) or text
        out.append({"n": i, "doi": d, "text": text.strip() or "(no text)"})
    if out:
        return "crossref", out
    zot = shutil.which("zot")
    if zot:
        r = subprocess.run(
            [zot, "refs", doi, "--source", "pdf"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        dois = [norm(x) for x in r.stdout.split() if DOI_RE.match(x)]
        for i, d in enumerate(dois, 1):
            out.append({"n": i, "doi": d, "text": describe(work(p, d)) or "(no text)"})
    return ("pdf" if out else "none"), out


# --- judging -------------------------------------------------------------------


def _pick(spec: str, refs: dict[int, dict]) -> tuple[int, str]:
    """'12' or '12=10.1/x' or '12=none' -> (12, doi or '')"""
    n, _, given = spec.partition("=")
    if not n.strip().isdigit() or int(n) not in refs:
        raise SnowballError(f"no reference number {n!r}; see `rsx snowball refs`")
    doi = norm(given) if given and given.strip().lower() != "none" else ""
    if given and doi and not DOI_RE.match(doi):
        raise SnowballError(f"not a DOI: {given}")
    if not given:
        doi = refs[int(n)]["doi"]
        if not doi:
            raise SnowballError(
                f'reference {n} has no DOI: find it (`rsx snowball find "title"`) and '
                f"give it as {n}=10.…, or {n}=none to log it without importing"
            )
    return int(n), doi


def _apply(rows: dict[int, dict], include, exclude, rest) -> None:
    for spec in include or []:
        n, doi = _pick(spec, rows)
        rows[n].update(decision="include", doi=doi or rows[n]["doi"], no_doi=not doi)
    for spec in exclude or []:
        n, _, why = spec.partition(":")
        if not n.strip().isdigit() or int(n) not in rows:
            raise SnowballError(f"no reference number {n!r}")
        if not EXCLUDE_WHY.match(why):
            raise SnowballError(
                f"exclude {n} needs a criterion from protocol.md: {n}:'E2: why'"
            )
        rows[int(n)].update(decision="exclude", why=why.strip())
    if rest:
        if not EXCLUDE_WHY.match(rest):
            raise SnowballError("--exclude-rest needs a criterion: 'E2: why'")
        for r in rows.values():
            r.setdefault("decision", "exclude")
            if r["decision"] == "exclude":
                r.setdefault("why", rest.strip())


def judge(p: Project, doi: str, include, exclude, rest: str | None, by: str) -> dict:
    s = load(p)
    doi = norm(doi)
    paper = s["papers"].get(doi)
    if paper is None:
        raise SnowballError(f"{doi} is not in the snowball")
    if paper.get("refs", {}).get("confirmed_by"):
        raise SnowballError(f"{doi}: its references are judged and confirmed already")
    source, refs = references(p, doi)
    rows = {r["n"]: dict(r) for r in refs}
    _apply(rows, include, exclude, rest)
    open_ = [n for n, r in rows.items() if "decision" not in r]
    if open_:
        raise SnowballError(
            f"{len(open_)} reference(s) without a decision: {', '.join(map(str, open_[:30]))}; "
            "--include N, --exclude N:'E2: why', or --exclude-rest 'E2: why'"
        )
    paper["refs"] = {
        "source": source,
        "judged_by": by,
        "judged": today(),
        "list": [rows[n] for n in sorted(rows)],
    }
    save(p, s)
    return paper["refs"]


def no_refs(p: Project, doi: str, reason: str, by: str) -> None:
    s = load(p)
    paper = s["papers"].get(norm(doi))
    if paper is None:
        raise SnowballError(f"{doi} is not in the snowball")
    source, refs = references(p, norm(doi))
    if refs:
        raise SnowballError(f"{doi} has {len(refs)} references ({source}): judge them")
    paper["refs"] = {
        "source": "none",
        "judged_by": by,
        "judged": today(),
        "list": [],
        "reason": reason,
    }
    save(p, s)


def confirm(p: Project, doi: str, by: str, include, exclude) -> list[str]:
    """The verifier's check of a judgement; returns the papers it adds."""
    s = load(p)
    doi = norm(doi)
    paper = s["papers"].get(doi)
    refs = (paper or {}).get("refs")
    if not refs:
        raise SnowballError(f"{doi}: its references are not judged yet")
    if refs.get("confirmed_by"):
        raise SnowballError(f"{doi}: confirmed already by {refs['confirmed_by']}")
    if by == refs["judged_by"]:
        raise SnowballError(
            f"{by} judged these references; a different agent confirms them"
        )
    rows = {r["n"]: r for r in refs["list"]}
    changes = []
    for spec in include or []:
        n, d = _pick(spec, rows)
        if rows[n].get("decision") != "include":
            changes.append(f"{n} included by {by}")
        rows[n].update(decision="include", doi=d or rows[n]["doi"], no_doi=not d)
        rows[n].pop("why", None)
    for spec in exclude or []:
        n, _, why = spec.partition(":")
        if not n.strip().isdigit() or int(n) not in rows or not EXCLUDE_WHY.match(why):
            raise SnowballError(f"exclude needs N:'E2: why', got {spec!r}")
        if rows[int(n)].get("decision") != "exclude":
            changes.append(f"{n} excluded by {by}")
        rows[int(n)].update(decision="exclude", why=why.strip(), no_doi=False)
    refs.update(confirmed_by=by, confirmed=today(), changes=changes)
    added = []
    for r in refs["list"]:
        if r.get("decision") != "include" or r.get("no_doi") or not r.get("doi"):
            continue
        child = s["papers"].get(r["doi"])
        if child is None:
            s["papers"][r["doi"]] = {"depth": paper["depth"] + 1, "found_in": [doi]}
            added.append(r["doi"])
        elif doi not in child["found_in"]:
            child["found_in"].append(doi)
    save(p, s)
    return added


# --- Zotero --------------------------------------------------------------------


def to_import(s: dict) -> list[str]:
    return [d for d, x in s["papers"].items() if "zotero" not in x]


def fetch(p: Project) -> dict:
    """Get the papers not in the collection yet, the way the user chose (rsx.toml
    `fetch`): `zotero` runs zot add (Zotero fetches the PDFs it can reach, so the
    user is on the institution's network first); `manual` lists the DOIs for the
    user to add by hand. Either way `sync` then reads what arrived."""
    if not p.collection:
        raise SnowballError(
            "no Zotero collection chosen: ask the user, `rsx config collection NAME`"
        )
    if p.fetch not in ("zotero", "manual"):
        raise SnowballError(
            "how papers are fetched is not chosen: ask the user, `rsx config fetch zotero|manual`"
        )
    s = load(p)
    todo = to_import(s)
    if not todo or p.fetch == "manual":
        if todo:
            out = p.root / ".rsx" / "to-add.txt"
            out.parent.mkdir(exist_ok=True)
            out.write_text("".join(f"https://doi.org/{d}\n" for d in todo), "utf-8")
        return {"mode": p.fetch, "todo": todo, "results": []}
    zot = shutil.which("zot")
    if not zot:
        raise SnowballError(
            "zot not found: uv tool install --editable ~/src/litflow/zotero"
        )
    r = subprocess.run(
        [zot, "add", "--json", "-c", p.collection, "-f", "-"],
        input="\n".join(todo),
        capture_output=True,
        text=True,
        timeout=60 * 60,
    )
    try:
        results = json.loads(r.stdout)
    except ValueError as e:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-5:])
        raise SnowballError(f"zot add failed (exit {r.returncode}):\n{tail}") from e
    for res in results:
        d = norm(res.get("input", ""))
        if d in s["papers"] and res.get("status") in ("imported", "exists"):
            s["papers"][d]["imported"] = res["status"]
    save(p, s)
    sync(p)
    return {"mode": p.fetch, "todo": todo, "results": results}


def sync(p: Project) -> dict:
    """Read the collection (zot pdfs --json): which snowball papers are in it, and
    which have a PDF. Papers in it are never fetched again."""
    zot = shutil.which("zot")
    if not zot:
        raise SnowballError(
            "zot not found: uv tool install --editable ~/src/litflow/zotero"
        )
    r = subprocess.run(
        [zot, "pdfs", "-c", p.collection, "--json"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    try:
        rows = json.loads(r.stdout)
    except ValueError as e:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-5:])
        raise SnowballError(f"zot pdfs failed (exit {r.returncode}):\n{tail}") from e
    s = load(p)
    arrived = []
    for row in rows:
        d = norm(row.get("doi") or "")
        x = s["papers"].get(d)
        if x is None:
            continue
        if "zotero" not in x:
            arrived.append(d)
        x.update(
            zotero=row["key"],
            pdf=bool(row.get("pdf")),
            title=row.get("title") or x.get("title"),
        )
        x.setdefault("imported", "added by hand")
    save(p, s)
    return {
        "arrived": arrived,
        "missing": to_import(s),
        "no_pdf": [
            d for d, x in s["papers"].items() if x.get("zotero") and not x.get("pdf")
        ],
    }


def unavailable(p: Project, doi: str, reason: str) -> None:
    """A paper nobody can get into Zotero: never fetched again; its references can
    still be judged from Crossref."""
    s = load(p)
    x = s["papers"].get(norm(doi))
    if x is None:
        raise SnowballError(f"{doi} is not in the snowball")
    x.update(zotero=None, imported="unavailable", reason=reason, pdf=False)
    save(p, s)


def find(p: Project, title: str, rows: int = 5) -> list[str]:
    """Crossref's best matches for a reference given by its text."""
    if os.environ.get("RSX_CROSSREF_OFFLINE"):
        return []
    q = urllib.parse.urlencode(
        {
            "query.bibliographic": title,
            "rows": rows,
            "select": "DOI,title,issued,author,container-title",
        }
    )
    req = urllib.request.Request(
        CROSSREF[:-1] + "?" + q, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.load(r)["message"]["items"]
    return [f"{norm(it['DOI'])}  {describe(it)}" for it in items]


def missing_from_bib(p: Project, s: dict) -> list[str]:
    """Imported papers the Better BibTeX export does not hold (yet)."""
    have = set()
    if p.bib.exists():
        have = {
            norm(bib.clean(e.get("doi", "")))
            for e in bib.parse_bib(p.bib.read_text("utf-8"))
        }
    return [d for d, x in s["papers"].items() if x.get("zotero") and d not in have]


# --- what is open ----------------------------------------------------------------


def open_work(p: Project) -> dict:
    s = load(p)
    n = depth_of(p) or 0
    papers = s["papers"]
    return {
        "fetch": to_import(s),
        "judge": [
            d
            for d, x in papers.items()
            if x["depth"] < n and "zotero" in x and not x.get("refs")
        ],
        "confirm": [
            d
            for d, x in papers.items()
            if x.get("refs") and not x["refs"].get("confirmed_by") and x["refs"]["list"]
        ],
        "bib": missing_from_bib(p, s) if papers else [],
        "no_pdf": [
            d for d, x in papers.items() if x.get("zotero") and not x.get("pdf")
        ],
    }


# --- log book --------------------------------------------------------------------


def _keys(p: Project) -> dict[str, str]:
    """DOI -> citekey of the vault's paper notes."""
    v = p.vault
    return {
        norm(str(x.fm.get("doi", ""))): x.id
        for x in v.of_type("paper")
        if x.fm.get("doi")
    }


def edges(s: dict) -> list[tuple[str, str]]:
    out = []
    for d, x in s["papers"].items():
        refs = x.get("refs") or {}
        if not refs.get("confirmed_by"):
            continue
        for r in refs["list"]:
            if (
                r.get("decision") == "include"
                and r.get("doi")
                and r["doi"] in s["papers"]
            ):
                out.append((d, r["doi"]))
    return out


def render(p: Project, s: dict) -> None:
    keys = _keys(p)

    def name(d: str) -> str:
        return f"[[{keys[d]}]]" if d in keys else f"`{d}`"

    def short(d: str) -> str:
        x = s["papers"][d]
        return (x.get("title") or d)[:70]

    n = depth_of(p)
    E = edges(s)
    lines = [
        "---",
        "type: log",
        "title: Snowball log book",
        "---",
        "",
        "# Snowball log book",
        "",
        "Written by `rsx snowball`; do not edit. State: `snowball.json`.",
        "",
        f"- Zotero collection: `{p.collection or '(not chosen)'}`",
        f"- Depth: {n if n is not None else '(not chosen)'} level(s) of references from the seeds",
        f"- Seeds: {', '.join(name(d) for d in s['seeds']) or '(none)'}",
        f"- Papers: {len(s['papers'])}, citation links between them: {len(E)}",
        "",
    ]
    for lvl in sorted({x["depth"] for x in s["papers"].values()}):
        lines += [
            f"## Level {lvl}",
            "",
            "| Paper | Zotero | PDF | References |",
            "|---|---|---|---|",
        ]
        for d, x in sorted(s["papers"].items(), key=lambda kv: kv[0]):
            if x["depth"] != lvl:
                continue
            refs = x.get("refs") or {}
            if refs.get("confirmed_by"):
                inc = sum(r.get("decision") == "include" for r in refs["list"])
                rstate = f"{inc}/{len(refs['list'])} included ({refs['judged_by']}, confirmed by {refs['confirmed_by']})"
            elif refs:
                rstate = f"judged by {refs['judged_by']}, not confirmed"
            elif n is not None and lvl >= n:
                rstate = "not expanded (last level)"
            else:
                rstate = "open"
            pdf = {True: "yes", False: "**no**", None: "?"}[x.get("pdf")]
            lines.append(
                f"| {name(d)} {short(d)} | {x.get('imported', 'open')} | {pdf} | {rstate} |"
            )
        lines.append("")
    lines += ["## Who cites whom", ""]
    if E:
        ids = {d: f"p{i}" for i, d in enumerate(s["papers"])}
        lines += ["```mermaid", "flowchart LR"]
        for d in s["papers"]:
            label = (keys.get(d) or d).replace('"', "'")
            lines.append(f'    {ids[d]}["{label}"]')
        lines += [f"    {ids[a]} --> {ids[b]}" for a, b in E]
        lines += ["```", ""]
        lines += [f"- {name(a)} cites {name(b)}" for a, b in E]
    else:
        lines.append("No confirmed citation links yet.")
    no_doi = [
        (d, r)
        for d, x in s["papers"].items()
        for r in (x.get("refs") or {}).get("list", [])
        if r.get("decision") == "include" and r.get("no_doi")
    ]
    lines += ["", "## Included references without a DOI (logged, not imported)", ""]
    lines += [f"- {name(d)}: {r['text'][:160]}" for d, r in no_doi] or ["None."]
    lines += ["", "## Excluded references, by reason", ""]
    why: dict[str, int] = {}
    for x in s["papers"].values():
        for r in (x.get("refs") or {}).get("list", []):
            if r.get("decision") == "exclude":
                k = r.get("why", "?").split(":")[0]
                why[k] = why.get(k, 0) + 1
    lines += [f"- {k}: {v}" for k, v in sorted(why.items())] or ["None."]
    (p.vault_dir / "snowball.md").write_text("\n".join(lines) + "\n", "utf-8")
    _link_papers(p, s, keys, E)


def _link_papers(p: Project, s: dict, keys: dict[str, str], E) -> None:
    """snowball_cites on paper notes: the graph view shows who cites whom."""
    v = p.vault
    cites: dict[str, list[str]] = {}
    for a, b in E:
        if a in keys and b in keys:
            cites.setdefault(keys[a], []).append(f"[[{keys[b]}]]")
    for key in set(keys.values()):
        note = v.notes.get(key)
        want = sorted(cites.get(key, []))
        if note is not None and (note.fm.get("snowball_cites") or []) != want:
            if want:
                note.fm["snowball_cites"] = want
            else:
                note.fm.pop("snowball_cites", None)
            v.save(note)
