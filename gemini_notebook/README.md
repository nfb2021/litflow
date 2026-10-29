# Gemini Notebook skill for Claude Code

Lets Claude Code work with your **Google Gemini Notebook** notebooks (the service formerly
called NotebookLM, now at `notebook.google.com`):

- **Ask questions** and get answers drawn only from the notebook's sources, with citations
- **Add sources** to a notebook: local files, websites / YouTube videos, or pasted text
- **Keep a library** of your notebooks so Claude knows which one to use for which topic

It works by driving a real Chrome browser with your Google login, because Gemini Notebook
has no public API.

> Fork of [PleasePrompto/notebooklm-skill](https://github.com/PleasePrompto/notebooklm-skill)
> (MIT), updated for the Gemini Notebook rebrand and extended with source uploads.
> See [What changed from the original](#what-changed-from-the-original).

## Requirements

- [Claude Code](https://claude.com/claude-code) running locally (not the web UI)
- [uv](https://docs.astral.sh/uv/) (`brew install uv` or see the uv docs)
- Google Chrome
- A Google account with access to Gemini Notebook

## Installation

```bash
# 1. Get the skills collection
git clone git@github.com:nfb2021/skills.git ~/src/skills

# 2. Make the skill visible to Claude Code
mkdir -p ~/.claude/skills
ln -s ~/src/skills/gemini_notebook ~/.claude/skills/gemini_notebook

# 3. Create the environment (uv reads pyproject.toml / uv.lock)
cd ~/.claude/skills/gemini_notebook
uv sync

# 4. Log in to Google once - a Chrome window opens, log in there
uv run scripts/auth_manager.py setup
```

Only if Chrome is not installed: `uv run patchright install chrome`.

To update later: `git -C ~/src/skills pull && uv sync`.

## Interactive guide (marimo)

`docs/guide.py` is a [marimo](https://marimo.io) notebook that explains how the skill works
and lets you try everything from buttons: check the login, browse your library, ask a
question, add sources, and play with the answer clean-up and placeholder detection.

```bash
cd ~/.claude/skills/gemini_notebook
uv run --group docs marimo edit docs/guide.py     # or: marimo run (app view, code hidden)
```

## Using it with Claude

Just ask in Claude Code. Examples:

| You say | What happens |
|---|---|
| "What does my GNSS-T notebook say about VOD retrieval?" | Claude asks the notebook and answers with citations |
| "Add this notebook to my library: https://notebook.google.com/notebook/…" | Claude asks the notebook what it covers and saves it with a name and topics |
| "Upload `paper.pdf` and `notes.md` to my GNSS-T notebook" | Files are uploaded and Claude reports when they are processed |
| "Add https://example.org/article to the notebook" | The website is imported as a source |
| "Put these answers into the notebook as a source" | The text is added as a pasted-text source |
| "Which notebooks do I have?" | Claude lists your library |

Claude asks follow-up questions on its own when an answer is incomplete. Each question
opens a fresh browser session, so it includes the full context every time.

## Using it from the terminal

Run everything from the skill folder with `uv run`:

```bash
cd ~/.claude/skills/gemini_notebook

# Ask a question
uv run scripts/ask_question.py --question "Summarise the main findings" --notebook-id my-notebook
uv run scripts/ask_question.py --question "..." --notebook-url "https://notebook.google.com/notebook/…"

# Add sources (types can be combined; --file and --url can be repeated)
uv run scripts/add_source.py --notebook-id my-notebook --file paper.pdf --file notes.md
uv run scripts/add_source.py --notebook-id my-notebook --url "https://example.org/article"
uv run scripts/add_source.py --notebook-id my-notebook --text "Some text"
uv run scripts/add_source.py --notebook-id my-notebook --text-file answers.md

# Manage the library
uv run scripts/notebook_manager.py list
uv run scripts/notebook_manager.py add --url URL --name NAME --description DESC --topics "a,b"
uv run scripts/notebook_manager.py activate --id my-notebook    # default for later commands
uv run scripts/notebook_manager.py remove --id my-notebook

# Login
uv run scripts/auth_manager.py status     # how old is the saved login?
uv run scripts/auth_manager.py reauth     # log in again / switch account
```

Useful options:

- `--show-browser` - watch the browser instead of running it in the background
- `--timeout SECONDS` - wait longer for long answers (default 240) or slow source processing (default 300)

`add_source.py` lists every new source as `ready` or `failed` and exits with an error if
any failed (for example a website Google could not import).

## Where your data lives

Everything personal stays in the skill's `data/` folder, which is git-ignored:

- `data/browser_state/` - Chrome profile and Google login cookies
- `data/library.json` - your notebook library
- `data/auth_info.json` - when you last logged in

Nothing in `data/` is ever committed. Treat it like a password: anyone with this folder
can use your Google session.

## Limitations

- Sources can be added but not removed. Google Drive and Play Books sources are not supported.
- Only a notebook's sources are queried. Studio notes and earlier chat history are not.
- No conversation memory between questions (each one is a new browser session).
- Free Google accounts allow roughly 50 questions per day.
- It depends on the Gemini Notebook web page. When Google changes the page, selectors in
  `scripts/config.py` may need updating.
- The Google login expires after a few weeks; run `uv run scripts/auth_manager.py reauth`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Not authenticated` | `uv run scripts/auth_manager.py setup` |
| Answers or uploads suddenly fail | Log in again: `uv run scripts/auth_manager.py reauth` |
| `ModuleNotFoundError` | Use `uv run` from the skill folder, not `python3` |
| Timeout on a long answer | Add `--timeout 400` |
| Something looks wrong | Re-run with `--show-browser` to see what the browser sees |

More in [references/troubleshooting.md](references/troubleshooting.md).

## What changed from the original

- **Gemini Notebook rebrand:** works with `notebook.google.com`; login detection checks for a
  real Google session instead of just the URL
- **Correct answers:** picks the newest answer reliably, skips "Thinking…"-style placeholders,
  and turns citation chips into inline `[1]` references
- **Background browser** uses a desktop-sized window, so the full three-panel layout loads
- **Popups** announcing new features are closed automatically
- **`--timeout`** option for long answers
- **New `add_source.py`** for files, websites/YouTube and pasted text
- **uv** replaces the old pip-based `run.py` / `setup_environment.py`
- **Interactive marimo guide** in `docs/guide.py`

Details in [CHANGELOG.md](CHANGELOG.md).

## Further reading

- [docs/guide.py](docs/guide.py) - interactive marimo guide
- [SKILL.md](SKILL.md) - instructions Claude follows when using the skill
- [references/api_reference.md](references/api_reference.md) - every script and option
- [references/usage_patterns.md](references/usage_patterns.md) - workflows
- [AUTHENTICATION.md](AUTHENTICATION.md) - how the login is stored and reused

## Licence

MIT. Original work © 2025 Please Prompto!; see [LICENSE](LICENSE).
