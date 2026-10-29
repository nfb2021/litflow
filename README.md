# skills

Collection of Claude Code skills.

| Skill | Description |
|---|---|
| [`gemini_notebook`](gemini_notebook/) | Query Google Gemini Notebook (formerly NotebookLM) notebooks from Claude Code and add sources (files, websites, YouTube, pasted text) to them. Fork of [PleasePrompto/notebooklm-skill](https://github.com/PleasePrompto/notebooklm-skill) (MIT) with fixes for the `notebook.google.com` rebrand. Comes with the `gnb` command. |
| [`zotero`](zotero/) | Import papers into Zotero by DOI with their PDFs, list a collection's PDFs, extract the DOIs papers cite, and upload PDFs to a Gemini Notebook. Drives the Zotero desktop app through the [Zotero MCP plugin](https://github.com/cookjohn/zotero-mcp). Comes with the `zot` command. |

## Install a skill

```bash
git clone git@github.com:nfb2021/skills.git ~/src/skills
ln -s ~/src/skills/gemini_notebook ~/.claude/skills/gemini_notebook
ln -s ~/src/skills/zotero ~/.claude/skills/zotero
```

Each skill has its own README with setup steps. Skills with Python code are uv projects;
each installs its command with `uv tool install --editable ~/src/skills/<skill>`
(`gnb` for `gemini_notebook`, `zot` for `zotero`).
Logins and other personal data are stored outside the repository.

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
