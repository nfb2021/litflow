# skills

Collection of Claude Code skills.

| Skill | Description |
|---|---|
| [`gemini_notebook`](gemini_notebook/) | Query Google Gemini Notebook (formerly NotebookLM) notebooks from Claude Code and add sources (files, websites, YouTube, pasted text) to them. Fork of [PleasePrompto/notebooklm-skill](https://github.com/PleasePrompto/notebooklm-skill) (MIT) with fixes for the `notebook.google.com` rebrand. |

## Install a skill

```bash
git clone git@github.com:nfb2021/skills.git ~/src/skills
ln -s ~/src/skills/gemini_notebook ~/.claude/skills/gemini_notebook
```

Each skill has its own README with setup steps. Skills with Python code use
[uv](https://docs.astral.sh/uv/): run `uv sync` in the skill folder once; data such as
logins stays in the skill's git-ignored `data/` folder.
