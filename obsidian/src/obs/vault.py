"""The vault on disk: a folder of Obsidian markdown notes with YAML frontmatter.

Every note has a `type` and an `id`; the file name is the id, so `[[id]]` links
resolve in Obsidian and here. Links live in frontmatter as "[[id]]" strings.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MARKER = "obs.toml"
SCHEMA = 1

# type -> (folder, id prefix or None for free ids like citekeys)
TYPES: dict[str, tuple[str, str | None]] = {
    "paper": ("papers", None),
    "statement": ("statements", "S"),
    "claim": ("claims", "C"),
    "question": ("questions", "Q"),
    "map": ("maps", "M"),
    "concept": ("concepts", None),
    "decision": ("decisions", "D"),
}

# frontmatter fields that hold links, per type
LINK_FIELDS: dict[str, tuple[str, ...]] = {
    "paper": (),
    "statement": ("concepts",),
    "claim": ("statement", "paper", "cites"),
    "question": ("map", "blocked_by", "claims", "statements"),
    "map": (),
    "concept": ("claims",),
    "decision": ("map",),
}

ROLES = ("origin", "restates", "restates-uncited", "disputes")
DRIFT = ("none", "weakened", "strengthened", "changed")
VERIFICATION = ("unverified", "verified", "rejected")
SCREENING = ("pending", "included", "excluded")
Q_KINDS = ("grilling", "research", "query", "falsify", "task")
HUMAN_KINDS = ("grilling",)  # only a human may answer these
Q_STATUS = ("open", "claimed", "answered", "out-of-scope")

LINK_RE = re.compile(r"^\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
FM_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)


class VaultError(Exception):
    """A user-facing error: bad input, missing note, no vault."""


@dataclass
class Note:
    id: str
    type: str
    path: Path
    fm: dict = field(default_factory=dict)
    body: str = ""

    def links(self, name: str) -> list[str]:
        """Target ids of a link field (single or list)."""
        value = self.fm.get(name)
        values = value if isinstance(value, list) else [value]
        return [t for t in (link_target(v) for v in values) if t]

    @property
    def title(self) -> str:
        return str(self.fm.get("title") or self.fm.get("text") or self.id)


def link(note_id: str) -> str:
    return f"[[{note_id}]]"


def link_target(value) -> str | None:
    """'[[x]]' -> 'x'; plain strings that are not links -> None."""
    if not isinstance(value, str):
        return None
    m = LINK_RE.match(value.strip())
    return m.group(1).strip() if m else None


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "note"


def parse(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    if not isinstance(fm, dict):
        raise ValueError("frontmatter is not a mapping")
    return fm, m.group(2)


# Evidence fields obs seals when it writes a note. A note whose seal no longer
# matches was edited outside obs, so its checks (quote lookup, verifier,
# answer) no longer hold for what it says now.
SEALED: dict[str, tuple[str, ...]] = {
    "claim": (
        "statement",
        "paper",
        "role",
        "quote",
        "page",
        "cites",
        "drift",
        "verification",
        "extracted_by",
        "verified_by",
    ),
    "question": (
        "status",
        "claims",
        "statements",
        "answered_by",
        "review",
        "reviewed_by",
        "review_of",
    ),
    "paper": ("searched",),
}
SEALED_SECTIONS: dict[str, tuple[str, ...]] = {"question": ("Answer",)}


def seal_of(type_: str, fm: dict, body: str) -> str | None:
    """Hash of the sealed fields of a note, None for unsealed types."""
    if type_ not in SEALED:
        return None
    if type_ == "paper" and not fm.get("searched"):
        return None  # nothing sealed yet: papers from before search records
    data = {
        "fm": {f: fm.get(f) for f in SEALED[type_]},
        "sections": {h: get_section(body, h) for h in SEALED_SECTIONS.get(type_, ())},
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def stamp_seal(type_: str, fm: dict, body: str) -> None:
    seal = seal_of(type_, fm, body)
    if seal:
        fm["seal"] = seal


# Pi sets these in the shell of every session it runs, lead and subagents
PI_SESSION_VARS = (
    "PI_SESSION_ID",
    "PI_SESSION_FILE",
    "PI_CODING_AGENT",
    "PI_MODEL",
    "PI_PROVIDER",
)


def _subagent_session(file: str) -> bool:
    """A pi-subagents child keeps its session inside its parent's:
    <parent>/<run id>/run-N/session.jsonl next to <parent>.jsonl."""
    path = Path(file)
    if path.name != "session.jsonl" or not re.fullmatch(r"run-\d+", path.parent.name):
        return False
    parent = path.parents[2]
    return path.is_file() and parent.with_name(parent.name + ".jsonl").is_file()


def lead_session() -> bool:
    """True inside the lead's own Pi session, False in its subagents' and
    outside Pi. Any of the variables counts, set or empty."""
    if not any(v in os.environ for v in PI_SESSION_VARS):
        return False
    return not _subagent_session(os.environ.get("PI_SESSION_FILE", ""))


def refuse_lead(role: str, what: str) -> str | None:
    """The error to show when the lead tries to do ROLE's work itself."""
    if not lead_session():
        return None
    return (
        f"{what} is {role}'s job and this is the lead's session. "
        "Delegate it: run the workflow that `rsx next --json` names."
    )


def render(fm: dict, body: str) -> str:
    dumped = yaml.safe_dump(
        fm, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False
    )
    return f"---\n{dumped}---\n{body if body.startswith(chr(10)) else chr(10) + body}"


def find_root(start: Path | None = None) -> Path:
    """$OBS_VAULT, else the nearest folder upwards containing obs.toml, or a
    litflow project (rsx.toml) whose `vault` folder is one."""
    env = os.environ.get("OBS_VAULT")
    if env:
        root = Path(env).expanduser().resolve()
        if not (root / MARKER).exists():
            raise VaultError(f"$OBS_VAULT={env} has no {MARKER}; run `obs init` there")
        return root
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / MARKER).exists():
            return d
        # a litflow project (rsx.toml) names its vault folder
        project = d / "rsx.toml"
        if project.exists():
            m = re.search(
                r'^\s*vault\s*=\s*"([^"]+)"', project.read_text("utf-8"), re.M
            )
            root = (d / (m.group(1) if m else "vault")).resolve()
            if (root / MARKER).exists():
                return root
    raise VaultError(
        f"no vault found from {here} upwards (no {MARKER}). "
        "Run `obs init PATH`, cd into the vault, or set $OBS_VAULT."
    )


class Vault:
    def __init__(self, root: Path):
        self.root = root
        self._notes: dict[str, Note] | None = None
        self.errors: list[tuple[Path, str]] = []  # unreadable notes, for lint

    @classmethod
    def open(cls, path: str | Path | None = None) -> Vault:
        return cls(find_root(Path(path) if path else None))

    # --- reading -----------------------------------------------------------
    @property
    def notes(self) -> dict[str, Note]:
        if self._notes is None:
            self._notes = {}
            self.errors = []
            for type_, (folder, _) in TYPES.items():
                for p in sorted((self.root / folder).glob("*.md")):
                    try:
                        fm, body = parse(p.read_text(encoding="utf-8"))
                    except (ValueError, yaml.YAMLError) as e:
                        self.errors.append((p, f"unreadable frontmatter: {e}"))
                        continue
                    note = Note(p.stem, fm.get("type", type_), p, fm, body)
                    if note.id in self._notes:
                        self.errors.append((p, f"duplicate id {note.id}"))
                        continue
                    self._notes[note.id] = note
        return self._notes

    def get(self, note_id: str, type_: str | None = None) -> Note:
        note_id = link_target(note_id) or note_id
        note = self.notes.get(note_id)
        if note is None:
            # case-insensitive fallback: weak agents get the case wrong
            lowered = {k.lower(): v for k, v in self.notes.items()}
            note = lowered.get(note_id.lower())
        if note is None:
            raise VaultError(f"no note {note_id!r}" + (f" ({type_})" if type_ else ""))
        if type_ and note.type != type_:
            raise VaultError(f"{note_id} is a {note.type}, expected a {type_}")
        return note

    def of_type(self, type_: str) -> list[Note]:
        return [n for n in self.notes.values() if n.type == type_]

    def backlinks(self, note_id: str) -> list[tuple[Note, str]]:
        out = []
        for n in self.notes.values():
            for f in LINK_FIELDS.get(n.type, ()):
                if note_id in n.links(f):
                    out.append((n, f))
        return out

    # --- writing -----------------------------------------------------------
    def next_id(self, type_: str) -> str:
        prefix = TYPES[type_][1]
        nums = [
            int(m.group(1))
            for n in self.notes
            if (m := re.fullmatch(rf"{prefix}-(\d+)", n))
        ]
        return f"{prefix}-{max(nums, default=0) + 1:04d}"

    def create(
        self, type_: str, fm: dict, body: str, note_id: str | None = None
    ) -> Note:
        note_id = note_id or self.next_id(type_)
        if not ID_RE.match(note_id):
            raise VaultError(f"invalid id {note_id!r}: use letters, digits, - _ . :")
        if note_id in self.notes:
            raise VaultError(f"{note_id} already exists ({self.notes[note_id].path})")
        path = self.root / TYPES[type_][0] / f"{note_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        fm = {"id": note_id, "type": type_, **fm}
        stamp_seal(type_, fm, body)
        path.write_text(render(fm, body), encoding="utf-8")
        note = Note(note_id, type_, path, fm, body)
        self.notes[note_id] = note
        return note

    def save(self, note: Note) -> None:
        stamp_seal(note.type, note.fm, note.body)
        note.path.write_text(render(note.fm, note.body), encoding="utf-8")


def set_section(body: str, heading: str, content: str) -> str:
    """Replace the text under `## heading` (or append the section)."""
    pattern = re.compile(
        rf"(^## {re.escape(heading)}[ \t]*\n)(.*?)(?=^## |\Z)", re.M | re.S
    )
    block = content.strip() + "\n\n"
    if pattern.search(body):
        return pattern.sub(lambda m: m.group(1) + "\n" + block, body, count=1)
    return body.rstrip() + f"\n\n## {heading}\n\n{block}"


def get_section(body: str, heading: str) -> str:
    m = re.search(
        rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", body, re.M | re.S
    )
    return m.group(1).strip() if m else ""
