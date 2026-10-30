# Gemini Notebook Skill API Reference

Every `gnb` command and the Python functions behind them (Gemini Notebook was formerly
NotebookLM). `gnb` is installed as a uv tool and runs from any directory:

```bash
uv tool install --editable ~/src/litflow/gemini_notebook   # or from git, see README
gnb --help
```

## Notebook selection

`ask` and `add` take `-n/--notebook`, which is either a **library ID** or a **notebook URL**
(anything starting with `http`). Without it the active notebook is used
(`gnb library activate ID`).

## gnb ask

```bash
gnb ask "Your question"                 # active notebook
gnb ask "..." -n notebook-id
gnb ask "..." -n "https://notebook.google.com/notebook/..."
gnb ask "..." --timeout 400 --show-browser
```

| Option | Default | Meaning |
|---|---|---|
| `QUESTION` (argument) | required | Question to ask |
| `-n`, `--notebook` | active notebook | Library ID or URL |
| `--timeout` | 240 | Seconds to wait for a stable answer |
| `--show-browser` | off | Visible Chrome instead of headless |

**Output:** progress lines, then the answer between two `====…` lines (60 `=`), with the
follow-up reminder appended. Citations appear inline as `[1]`, `[1][4]`.
**Exit code:** 0 with an answer, 1 otherwise.

## gnb add

```bash
gnb add -n ID --file paper.pdf --file notes.md
gnb add -n ID --url "https://example.org/article" --url "https://youtu.be/..."
gnb add -n ID --text "..."
gnb add -n ID --text-file answers.md
```

| Option | Default | Meaning |
|---|---|---|
| `-n`, `--notebook` | active notebook | Library ID or URL |
| `-f`, `--file` | | Local file to upload (repeatable) |
| `-u`, `--url` | | Website or YouTube URL (repeatable) |
| `--text` | | Text added as one pasted-text source |
| `--text-file` | | File whose contents are added as pasted text |
| `--timeout` | 300 | Seconds to wait for processing |
| `--show-browser` | off | Visible Chrome |

At least one of `--file`, `--url`, `--text`, `--text-file` is required (exit code 2 otherwise).
**Output:** `New sources:` followed by `✓ title (ready)` / `✗ title (failed)` / `… title (processing)`.
**Exit code:** 0 only if every new source is `ready`.

## gnb library

```bash
gnb library list
gnb library add URL --name "Name" --description "What it contains" --topics "a,b,c" \
    [--use-cases "x,y"] [--tags "t1,t2"]
gnb library search QUERY          # name, description, topics, tags, use cases
gnb library activate ID
gnb library remove ID             # library entry only, the notebook stays
gnb library stats
```

The ID is derived from the name (`"GNSS-T VOD"` → `gnss-t-vod`). The first notebook added
becomes active. `add` fails with exit code 1 if the ID already exists.

## gnb auth

```bash
gnb auth status                   # exit code 1 if no login saved; prints the data folder
gnb auth setup [--timeout 10]     # visible Chrome, log in manually (minutes)
gnb auth validate                 # opens the site headless, checks the login works
gnb auth reauth [--timeout 10]    # clear + setup, also to switch accounts
gnb auth clear
```

## gnb cleanup

```bash
gnb cleanup                                   # preview only
gnb cleanup --confirm                         # asks, then deletes login + library
gnb cleanup --confirm --preserve-library      # keep library.json
gnb cleanup --confirm --force                 # no prompt
```

## Data folder

`~/Library/Application Support/gemini-notebook/` on macOS (platformdirs user data dir on
other systems), or `$GEMINI_NOTEBOOK_HOME` if set.

```
library.json        notebooks and the active notebook ID
auth_info.json      login timestamp
browser_state/
  browser_profile/  persistent Chrome profile
  state.json        cookies saved at login, re-injected on every start
```

`library.json`:
```json
{
  "notebooks": {
    "notebook-id": {
      "id": "notebook-id",
      "url": "https://notebook.google.com/notebook/...",
      "name": "Display Name",
      "description": "Contents",
      "topics": ["topic1", "topic2"],
      "content_types": [],
      "use_cases": [],
      "tags": [],
      "created_at": "ISO-8601",
      "updated_at": "ISO-8601",
      "use_count": 0,
      "last_used": null
    }
  },
  "active_notebook_id": "notebook-id",
  "updated_at": "ISO-8601"
}
```

## Python API

The package is `gemini_notebook`:

```python
from gemini_notebook.ask import ask_notebook, clean_answer, PLACEHOLDER_RE
from gemini_notebook.sources import add_sources
from gemini_notebook.library import NotebookLibrary
from gemini_notebook.auth import AuthManager

answer = ask_notebook(
    "Question?", "https://notebook.google.com/notebook/...", timeout=240
)
new = add_sources(
    url, files=["paper.pdf"], urls=["https://..."], text="..."
)  # [(title, status)] or None

lib = NotebookLibrary()
lib.list_notebooks()
lib.get_notebook("id")
lib.get_active_notebook()
lib.add_notebook(url=..., name=..., description=..., topics=[...])
lib.select_notebook("id")
lib.remove_notebook("id")
lib.search_notebooks("q")

AuthManager().is_authenticated()
```

| Module | Contents |
|---|---|
| `cli.py` | Typer app behind `gnb` |
| `ask.py` | `ask_notebook()`, `clean_answer()`, `PLACEHOLDER_RE`, `FOLLOW_UP_REMINDER` |
| `sources.py` | `add_sources()` and the add-source dialog steps |
| `library.py` | `NotebookLibrary` |
| `auth.py` | `AuthManager` (setup, status, validate, clear, reauth) |
| `cleanup.py` | `CleanupManager` |
| `browser.py` | `BrowserFactory` (Chrome launch, cookie injection), `StealthUtils` |
| `config.py` | data paths and every page selector |

## Calling gnb from another program

```python
import subprocess

result = subprocess.run(
    ["gnb", "ask", "Question?", "-n", "notebook-id"], capture_output=True, text=True
)
answer = result.stdout.split("=" * 60)[2].strip() if result.returncode == 0 else None
```

## Rate limits

Free Google accounts allow roughly 50 questions per day. Space out automated batches,
or switch accounts with `gnb auth reauth`.
