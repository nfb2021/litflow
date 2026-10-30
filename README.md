# litflow

A literature research workflow for AI agents. Each step is a skill with its own command:
import papers into Zotero, query them in a Gemini Notebook, record verified claims and their
citation chains in an Obsidian vault, and write in Typst. Agents verify and review each
other's work, and the commands enforce the rules so that smaller models can follow them.

| Skill | Description |
|---|---|
| [`gemini_notebook`](gemini_notebook/) | Query Google Gemini Notebook (formerly NotebookLM) notebooks from Claude Code and add sources (files, websites, YouTube, pasted text) to them. Fork of [PleasePrompto/notebooklm-skill](https://github.com/PleasePrompto/notebooklm-skill) (MIT) with fixes for the `notebook.google.com` rebrand. Comes with the `gnb` command. |
| [`zotero`](zotero/) | Import papers into Zotero by DOI with their PDFs, list a collection's PDFs, extract the DOIs papers cite, and upload PDFs to a Gemini Notebook. Drives the Zotero desktop app through the [Zotero MCP plugin](https://github.com/cookjohn/zotero-mcp). Comes with the `zot` command. |
| [`obsidian`](obsidian/) | A research vault in Obsidian markdown: papers from the Better BibTeX export, claims with verbatim quotes checked against the PDF, citation provenance across papers, question maps with a frontier, and a lint gate for agent workflows. Comes with the `obs` command. |

## Install a skill

```bash
git clone git@github.com:nfb2021/litflow.git ~/src/litflow
ln -s ~/src/litflow/gemini_notebook ~/.claude/skills/gemini_notebook
ln -s ~/src/litflow/zotero ~/.claude/skills/zotero
ln -s ~/src/litflow/obsidian ~/.claude/skills/obsidian
```

Each skill has its own README with setup steps. Skills with Python code are uv projects;
each installs its command with `uv tool install --editable ~/src/litflow/<skill>`
(`gnb` for `gemini_notebook`, `zot` for `zotero`, `obs` for `obsidian`).
Logins and other personal data are stored outside the repository.

## Skills used from upstream

Documents are written in Typst with
[lucifer1004/claude-skill-typst](https://github.com/lucifer1004/claude-skill-typst) (MIT),
used as is and not copied here. Its repository keeps the skill in `skills/typst`, so link
that folder, not the clone:

```bash
git clone https://github.com/lucifer1004/claude-skill-typst.git ~/src/claude-skill-typst
ln -s ~/src/claude-skill-typst/skills/typst ~/.claude/skills/typst
```

It needs Typst 0.15 or newer (`brew install typst`). Cite with the Better BibTeX export that
`obsidian` reads, e.g. `#bibliography("refs.bib")`; `typst compile` fails on a citation key
that is not in the file.

## Contributing

Commits follow [Conventional Commits](https://www.conventionalcommits.org) with the skill
as scope, e.g. `feat(gemini_notebook): add source removal`. Hooks run ruff (lint and
format), `uv lock`, file checks and a GitGuardian secret scan before push:

```bash
uvx prek install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
uvx ggshield auth login        # once, for the secret scan
uvx prek run --all-files       # what CI runs
```

CI (`.github/workflows/`) runs the same hooks, checks every lock file, installs each
command as a uv tool and smoke-tests it, and scans for secrets. See [SECURITY.md](SECURITY.md)
for reporting vulnerabilities.
