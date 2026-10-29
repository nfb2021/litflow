"""Maps and question tickets (after Matt Pocock's wayfinder skill, MIT).

A map names a destination. Its questions are tickets; `blocked_by` orders them.
The frontier is every open ticket whose blockers are all closed. One ticket
per session. The map's "Decisions so far" and "Out of scope" sections are
generated from the tickets, so each answer lives in exactly one place.
"""

from __future__ import annotations

from obs.vault import Note, Vault, get_section, set_section

CLOSED = ("answered", "out-of-scope")


def questions(vault: Vault, map_id: str | None = None) -> list[Note]:
    qs = vault.of_type("question")
    if map_id:
        m = vault.get(map_id, "map")
        qs = [q for q in qs if m.id in q.links("map")]
    return sorted(qs, key=lambda q: q.id)


def blockers_open(vault: Vault, q: Note) -> list[str]:
    out = []
    for b in q.links("blocked_by"):
        bn = vault.notes.get(b)
        if bn is None or bn.fm.get("status") not in CLOSED:
            out.append(b)
    return out


def frontier(vault: Vault, map_id: str | None = None) -> list[Note]:
    return [
        q
        for q in questions(vault, map_id)
        if q.fm.get("status", "open") == "open" and not blockers_open(vault, q)
    ]


def refresh_map(vault: Vault, map_note: Note) -> None:
    """Regenerate the map's index sections from its tickets."""
    qs = questions(vault, map_note.id)
    decided = [q for q in qs if q.fm.get("status") == "answered"]
    dropped = [q for q in qs if q.fm.get("status") == "out-of-scope"]
    lines = [
        f"- [[{q.id}]] {q.title}: {q.fm.get('gist', '').strip() or '(no gist)'}"
        for q in decided
    ]
    body = set_section(
        map_note.body, "Decisions so far", "\n".join(lines) or "_none yet_"
    )
    lines = [f"- [[{q.id}]] {q.title}: {q.fm.get('reason', '')}" for q in dropped]
    body = set_section(body, "Out of scope", "\n".join(lines) or "_none_")
    if body != map_note.body:
        map_note.body = body
        vault.save(map_note)


def render_map(vault: Vault, map_note: Note) -> str:
    qs = questions(vault, map_note.id)
    front = {q.id for q in frontier(vault, map_note.id)}
    out = [f"# {map_note.id}: {map_note.title}", ""]
    out.append(
        "Destination: " + (get_section(map_note.body, "Destination") or map_note.title)
    )
    notes = get_section(map_note.body, "Notes")
    if notes:
        out += ["", "Notes:", notes]
    out += ["", "Tickets:"]
    for q in qs:
        status = q.fm.get("status", "open")
        tag = "FRONTIER" if q.id in front else status
        blocked = blockers_open(vault, q)
        extra = (
            f"  (blocked by {', '.join(blocked)})"
            if blocked and status == "open"
            else ""
        )
        human = " [needs human]" if q.fm.get("kind") == "grilling" else ""
        out.append(f"  {q.id} [{q.fm.get('kind')}] {tag}{human}: {q.title}{extra}")
    fog = get_section(map_note.body, "Not yet specified")
    if fog:
        out += ["", "Not yet specified (fog):", fog]
    return "\n".join(out)
