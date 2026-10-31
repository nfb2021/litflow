# Gemini Notebook skill for Claude Code

Lets Claude Code work with your **Google Gemini Notebook** notebooks (the service formerly
called NotebookLM, now at `notebook.google.com`):

- **Ask questions** and get answers drawn only from the notebook's sources, with citations
- **Add sources** to a notebook: local files, websites / YouTube videos, or pasted text
- **Keep a library** of your notebooks so Claude knows which one to use for which topic

Everything is available as one command, `gnb`, which you can also use yourself in the
terminal. It works by driving a real Chrome browser with your Google login, because Gemini Notebook
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
git clone git@github.com:nfb2021/litflow.git ~/src/litflow

# 2. Make the skill visible to Claude Code
mkdir -p ~/.claude/skills
ln -s ~/src/litflow/gemini_notebook ~/.claude/skills/gemini_notebook

# 3. Install the gnb command (editable: a git pull updates it too)
uv tool install --editable ~/src/litflow/gemini_notebook

# 4. Log in to Google once - a Chrome window opens, log in there
gnb auth setup
```

If `gnb` is not found afterwards, run `uv tool update-shell` and open a new terminal.
Only if Chrome is not installed: `uvx patchright install chrome`.

To update later: `git -C ~/src/litflow pull` (the editable install picks it up; after a
dependency change also `uv tool upgrade gemini-notebook`).

**Only the command, without the Claude skill:**

```bash
uv tool install "git+https://github.com/nfb2021/litflow#subdirectory=gemini_notebook"
```

## Interactive guide (marimo)

`docs/guide.py` is a [marimo](https://marimo.io) notebook that explains how the skill works
and lets you try everything from buttons: check the login, browse your library, ask a
question, add sources, and play with the answer clean-up and placeholder detection.

```bash
cd ~/src/litflow/gemini_notebook
uvx --with-editable . marimo edit docs/guide.py   # or: marimo run (app view, code hidden)
```

`uvx` builds a throwaway environment with marimo and this package, so nothing is
installed into your project or system Python.

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

`gnb` works from any folder. `-n` takes a library ID or a notebook URL; without it the
active notebook is used.

```bash
# Ask a question
gnb ask "Summarise the main findings" -n my-notebook
gnb ask "..." -n "https://notebook.google.com/notebook/…"

# Add sources (types can be combined; --file and --url can be repeated)
gnb add -n my-notebook --file paper.pdf --file notes.md
gnb add -n my-notebook --url "https://example.org/article"
gnb add -n my-notebook --text "Some text"
gnb add -n my-notebook --text-file answers.md

# Manage the library
gnb library list
gnb library add URL --name NAME --description DESC --topics "a,b"
gnb library activate my-notebook     # default for later commands
gnb library remove my-notebook

# Login
gnb auth status      # how old is the saved login, where is the data?
gnb auth reauth      # log in again / switch account
```

`gnb --help` and `gnb ask --help` (etc.) list every option. Useful ones:

- `--show-browser` - watch the browser instead of running it in the background
- `--timeout SECONDS` - wait longer for long answers (default 240) or slow source processing (default 300)
- `gnb ask --json` - print only `{question, notebook, answer}` as JSON, for scripts such as `rsx ask`

`gnb add` lists every new source as `ready` or `failed` and exits with an error if
any failed (for example a website Google could not import).

## Where your data lives

Your login and library are kept outside the repository, in your user data folder
(macOS: `~/Library/Application Support/gemini-notebook/`; `gnb auth status` shows it):

- `browser_state/` - Chrome profile and Google login cookies
- `library.json` - your notebook library
- `auth_info.json` - when you last logged in

Set `GEMINI_NOTEBOOK_HOME` to use another folder (e.g. for a second Google account).
Treat the folder like a password: anyone with it can use your Google session.

## Limitations

- Sources can be added but not removed. Google Drive and Play Books sources are not supported.
- Only a notebook's sources are queried. Studio notes and earlier chat history are not.
- No conversation memory between questions (each one is a new browser session).
- Free Google accounts allow roughly 50 questions per day.
- It depends on the Gemini Notebook web page. When Google changes the page, selectors in
  `src/gemini_notebook/config.py` may need updating.
- The Google login expires after a few weeks; run `gnb auth reauth`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `gnb: command not found` | `uv tool update-shell`, new terminal; or reinstall (step 3) |
| `Not authenticated` | `gnb auth setup` |
| Answers or uploads suddenly fail | Log in again: `gnb auth reauth` |
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
- **Adding sources** (`gnb add`) for files, websites/YouTube and pasted text
- **`gnb` command** (Typer, installed with `uv tool`) replaces the separate scripts and
  the old pip-based `run.py` / `setup_environment.py`; login and library moved to the user data folder
- **Interactive marimo guide** in `docs/guide.py`

Details in [CHANGELOG.md](CHANGELOG.md).

## Further reading

- [docs/guide.py](docs/guide.py) - interactive marimo guide
- [SKILL.md](SKILL.md) - instructions Claude follows when using the skill
- [references/api_reference.md](references/api_reference.md) - every command, option and Python function
- [references/usage_patterns.md](references/usage_patterns.md) - workflows
- [AUTHENTICATION.md](AUTHENTICATION.md) - how the login is stored and reused

## Licence

MIT. Original work © 2025 Please Prompto!; see [LICENSE](LICENSE).
