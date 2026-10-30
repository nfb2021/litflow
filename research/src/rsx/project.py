"""A litflow project: one folder holding the vault, refs.bib, the Typst draft
and the draft reviews, marked by rsx.toml.

    project/
      rsx.toml          title and the paths below
      refs.bib          Better BibTeX auto-export of the Zotero collection
      vault/            the obs vault (claims, statements, questions, ...)
      paper/main.typ    the draft
      reviews/          draft submissions and reviews (rsx draft)
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from obs.vault import MARKER as VAULT_MARKER
from obs.vault import Vault

MARKER = "rsx.toml"
KEYS = ("title", "vault", "bib", "doc", "reviews")
DEFAULTS = {
    "title": "Literature research",
    "vault": "vault",
    "bib": "refs.bib",
    "doc": "paper/main.typ",
    "reviews": "reviews",
}

DOC_TEMPLATE = """// Draft for {title}. Written by lit-writer, reviewed by lit-critic.
//
// Rules (checked by `rsx cite-check`):
// - Every sentence that rests on the literature cites its papers with @key
//   and ends with a comment naming the verified claims it rests on:
//     Light ejects electrons only above a threshold frequency @lenard1902. // C-0004
// - Cite the paper that shows a result (origin), not one that repeats it.
// - Nothing from your own background knowledge; no claim, no sentence.

#set document(title: "{title}")
#set text(lang: "en")
#set par(justify: true)
#set heading(numbering: "1.")

= {title}

#bibliography("{bib}", style: "apa")
"""


class ProjectError(Exception):
    """A user-facing error: no project, bad config."""


@dataclass
class Project:
    root: Path
    title: str
    vault_dir: Path
    bib: Path
    doc: Path
    reviews: Path

    @property
    def vault(self) -> Vault:
        return Vault(self.vault_dir)

    def doc_hash(self) -> str | None:
        if not self.doc.exists():
            return None
        return hashlib.sha256(self.doc.read_bytes()).hexdigest()[:16]

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)


def parse_toml(text: str) -> dict:
    """The flat `key = "value"` subset rsx.toml uses (no tomllib on 3.10)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r'^\s*([A-Za-z_]+)\s*=\s*"((?:[^"\\]|\\.)*)"\s*(#.*)?$', line)
        if m:
            out[m.group(1)] = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
    return out


def write_toml(data: dict) -> str:
    def q(v: str) -> str:
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'

    return "".join(f"{k} = {q(str(data[k]))}\n" for k in KEYS if k in data)


def load(root: Path) -> Project:
    cfg = {**DEFAULTS, **parse_toml((root / MARKER).read_text(encoding="utf-8"))}
    return Project(
        root=root,
        title=cfg["title"],
        vault_dir=(root / cfg["vault"]).resolve(),
        bib=(root / cfg["bib"]).resolve(),
        doc=(root / cfg["doc"]).resolve(),
        reviews=(root / cfg["reviews"]).resolve(),
    )


def find(start: Path | None = None) -> Project:
    """$RSX_PROJECT, else the nearest folder upwards containing rsx.toml."""
    env = os.environ.get("RSX_PROJECT")
    if env:
        root = Path(env).expanduser().resolve()
        if not (root / MARKER).exists():
            raise ProjectError(f"$RSX_PROJECT={env} has no {MARKER}")
        return load(root)
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / MARKER).exists():
            return load(d)
    raise ProjectError(
        f"no litflow project from {here} upwards (no {MARKER}). "
        "Run `rsx init PATH --title ...`, cd into the project, or set $RSX_PROJECT."
    )


def init(path: Path, title: str) -> Project:
    from obs.cli import init as obs_init

    path = path.expanduser().resolve()
    if (path / MARKER).exists():
        raise ProjectError(f"{path} is already a litflow project")
    path.mkdir(parents=True, exist_ok=True)
    (path / MARKER).write_text(write_toml({**DEFAULTS, "title": title}), "utf-8")
    p = load(path)
    if not (p.vault_dir / VAULT_MARKER).exists():
        obs_init(p.vault_dir, title)
    if not p.bib.exists():
        p.bib.write_text(
            "% Better BibTeX auto-export of the project's Zotero collection.\n"
            "% Zotero: right-click the collection > Export Collection > Better BibLaTeX,\n"
            "% tick 'Keep updated', save here.\n",
            "utf-8",
        )
    if not p.doc.exists():
        p.doc.parent.mkdir(parents=True, exist_ok=True)
        bib = os.path.relpath(p.bib, p.doc.parent)
        p.doc.write_text(DOC_TEMPLATE.format(title=title, bib=bib), "utf-8")
    p.reviews.mkdir(exist_ok=True)
    gi = path / ".gitignore"
    if not gi.exists():
        gi.write_text(".rsx/\n", "utf-8")
    return p
