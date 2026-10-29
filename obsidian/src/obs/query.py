"""Filtering notes, and SQL over an in-memory index of the vault."""

from __future__ import annotations

import json
import re
import sqlite3

from obs.vault import LINK_FIELDS, Note, Vault, VaultError

_FILTER = re.compile(r"^([\w.-]+)(!=|~|=|>=|<=|>|<)(.*)$")


def _values(note: Note, key: str) -> list[str]:
    if key == "id":
        return [note.id]
    if key in ("body", "text") and key not in note.fm:
        return [note.body]
    v = note.fm.get(key)
    if v is None:
        return []
    vs = v if isinstance(v, list) else [v]
    out = []
    for x in vs:
        s = str(x)
        out.append(s[2:-2] if s.startswith("[[") and s.endswith("]]") else s)
    return out


def match(note: Note, expr: str) -> bool:
    m = _FILTER.match(expr)
    if not m:
        raise VaultError(
            f"bad filter {expr!r}: use field=value, field!=value, field~text, field>N"
        )
    key, op, want = m.groups()
    vals = _values(note, key)
    if op == "=":
        return any(v.lower() == want.lower() for v in vals) or (want == "" and not vals)
    if op == "!=":
        return all(v.lower() != want.lower() for v in vals)
    if op == "~":
        return any(want.lower() in v.lower() for v in vals)
    try:
        num = float(want)
        nums = [float(v) for v in vals]
    except ValueError:
        return False
    return any(
        {">": n > num, "<": n < num, ">=": n >= num, "<=": n <= num}[op] for n in nums
    )


def select(vault: Vault, type_: str | None, filters: list[str]) -> list[Note]:
    notes = [n for n in vault.notes.values() if type_ in (None, "all", n.type)]
    return sorted(
        (n for n in notes if all(match(n, f) for f in filters)), key=lambda n: n.id
    )


def connect(vault: Vault) -> sqlite3.Connection:
    """notes(id, type, title, status, path, body, fm JSON) and links(src, field, dst)."""
    db = sqlite3.connect(":memory:")
    db.execute(
        "create table notes (id text primary key, type text, title text, status text, path text, body text, fm text)"
    )
    db.execute("create table links (src text, field text, dst text)")
    for n in vault.notes.values():
        status = n.fm.get("status") or n.fm.get("verification") or n.fm.get("screening")
        db.execute(
            "insert into notes values (?,?,?,?,?,?,?)",
            (
                n.id,
                n.type,
                n.title,
                status,
                str(n.path.relative_to(vault.root)),
                n.body,
                json.dumps(n.fm, default=str),
            ),
        )
        for f in LINK_FIELDS.get(n.type, ()):
            for t in n.links(f):
                db.execute("insert into links values (?,?,?)", (n.id, f, t))
    return db


def sql(vault: Vault, statement: str) -> tuple[list[str], list[tuple]]:
    if not re.match(r"^\s*(select|with)\b", statement, re.I):
        raise VaultError("only SELECT queries are allowed")
    cur = connect(vault).execute(statement)
    return [d[0] for d in cur.description or ()], cur.fetchall()


def neighbors(
    vault: Vault, note_id: str, depth: int = 1
) -> dict[str, list[tuple[str, str, str]]]:
    """Edges within `depth` hops: {note: [(direction, field, other)]}."""
    start = vault.get(note_id).id
    seen, frontier, edges = {start}, [start], {}
    for _ in range(depth):
        nxt = []
        for nid in frontier:
            n = vault.notes.get(nid)
            out = []
            if n:
                for f in LINK_FIELDS.get(n.type, ()):
                    out += [("->", f, t) for t in n.links(f)]
            out += [("<-", f, src.id) for src, f in vault.backlinks(nid)]
            edges[nid] = out
            for _, _, other in out:
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    return edges
