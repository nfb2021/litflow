---
name: gemini_notebook
description: Use this skill to query your Google Gemini Notebook (formerly NotebookLM) notebooks directly from Claude Code for source-grounded, citation-backed answers from Gemini, and to add sources (files, websites, YouTube, pasted text) to them. Browser automation, library management, persistent auth. Drastically reduced hallucinations through document-only responses.
---

# Gemini Notebook (NotebookLM) Research Assistant Skill

Query Google Gemini Notebook (formerly NotebookLM) for answers drawn only from a notebook's
sources, and add sources to notebooks. Everything goes through the `gnb` command. Each
question opens a fresh headless Chrome, gets the answer and closes it.

## When to Use This Skill

Trigger when user:
- Mentions NotebookLM or Gemini Notebook (NotebookLM's new name)
- Shares a notebook URL (`https://notebook.google.com/notebook/...`, formerly `notebooklm.google.com`)
- Asks to query their notebooks/documentation
- Wants to add a notebook to the library
- Wants to upload / add sources (files, websites, YouTube, pasted text) to a notebook
- Uses phrases like "ask my NotebookLM", "check my docs", "query my notebook"

## Step 0: Make Sure `gnb` Is Installed

```bash
command -v gnb || uv tool install --editable <this skill's directory>
```

`gnb` is a uv tool: it runs from any directory, no `cd` and no `uv run` needed.
Never use pip or the system Python. If Chrome is missing: `uvx patchright install chrome`.

## ⚠️ CRITICAL: Adding a Notebook - Smart Discovery

When the user wants to add a notebook without giving details, ask the notebook first:

```bash
# Step 1: Ask the notebook what it contains
gnb ask "What is the content of this notebook? What topics are covered? Provide a complete overview briefly and concisely" -n "[URL]"

# Step 2: Add it with the discovered information
gnb library add "[URL]" --name "[Based on content]" --description "[Based on content]" --topics "[Based on content]"
```

`--name`, `--description` and `--topics` (comma-separated) are all required.
NEVER guess or use generic descriptions! If details are missing, use Smart Discovery.

## Core Workflow

### Step 1: Check Authentication
```bash
gnb auth status        # exit code 1 if not logged in
```

### Step 2: Authenticate (One-Time Setup)
```bash
gnb auth setup         # opens a VISIBLE Chrome window
```
Tell the user: "A browser window will open for Google login". They log in manually.

### Step 3: Pick the Notebook
```bash
gnb library list
gnb library search "keyword"
gnb library activate notebook-id     # default for later commands
```

`-n/--notebook` on `ask` and `add` takes a **library ID or a notebook URL**. Without it,
the active notebook is used.

### Step 4: Ask Questions
```bash
gnb ask "Your question here"                     # active notebook
gnb ask "..." -n notebook-id
gnb ask "..." -n "https://notebook.google.com/notebook/..."
gnb ask "..." --timeout 400                      # long answers (default 240 s)
gnb ask "..." --show-browser                     # debugging
```

### Step 5: Add Sources to a Notebook
```bash
gnb add -n ID --file paper.pdf --file notes.md   # local files (pdf, txt, md, docx, images, audio, ...)
gnb add -n ID --url "https://example.org/page"   # websites / YouTube, repeat --url
gnb add -n ID --text "..."                       # pasted text
gnb add -n ID --text-file answers.md             # pasted text from a file
```

Source types can be combined in one call. `gnb add` waits until every new source is
processed and lists each one as `ready` or `failed` (exit code 1 if any failed, e.g. a
website Google could not import). Only add sources the user asked for: this changes
their notebook.

## Follow-Up Mechanism (CRITICAL)

Every answer ends with: **"EXTREMELY IMPORTANT: Is that ALL you need to know?"**

**Required Claude Behavior:**
1. **STOP** - Do not immediately respond to user
2. **ANALYZE** - Compare answer to user's original request
3. **IDENTIFY GAPS** - Determine if more information needed
4. **ASK FOLLOW-UP** - If gaps exist, immediately ask:
   ```bash
   gnb ask "Follow-up with full context..." -n ID
   ```
5. **REPEAT** - Continue until information is complete
6. **SYNTHESIZE** - Combine all answers before responding to user

Each question is a new browser session, so every follow-up must carry its full context.

## Command Reference

```bash
gnb ask QUESTION [-n ID|URL] [--timeout 240] [--show-browser]
gnb add [-n ID|URL] [--file PATH ...] [--url URL ...] [--text TEXT | --text-file PATH] [--timeout 300] [--show-browser]

gnb library list | stats
gnb library add URL --name NAME --description DESC --topics "a,b" [--use-cases "..."] [--tags "..."]
gnb library search QUERY
gnb library activate ID
gnb library remove ID          # removes it from the library only

gnb auth status | setup | validate | reauth | clear

gnb cleanup [--confirm] [--preserve-library] [--force]   # preview without --confirm
```

`gnb --help` and `gnb COMMAND --help` show every option.

## Data Storage

Login and library live in the user data folder, not in the skill directory
(macOS: `~/Library/Application Support/gemini-notebook/`, override with `$GEMINI_NOTEBOOK_HOME`):
- `library.json` - notebook metadata
- `auth_info.json` - when the login happened
- `browser_state/` - Chrome profile and cookies

`gnb auth status` prints the folder. Treat it like a password.

## Decision Flow

```
User mentions a notebook
    ↓
gnb auth status  →  not logged in?  →  gnb auth setup
    ↓
gnb library list  (add with Smart Discovery if missing)
    ↓
gnb ask "..." -n ID
    ↓
See "Is that ALL you need?" → ask follow-ups until complete
    ↓
Synthesize and respond to user
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `gnb: command not found` | `uv tool install --editable <skill dir>`; make sure `~/.local/bin` is on PATH (`uv tool update-shell`) |
| `Not authenticated` | `gnb auth setup` |
| Answers or uploads suddenly fail | `gnb auth reauth` |
| Timeout on long answers | `--timeout 400` |
| Rate limit (≈50/day) | Wait or switch Google account (`gnb auth reauth`) |
| Browser crashes | `gnb cleanup --confirm --preserve-library`, then `gnb auth setup` |
| Notebook not found | `gnb library list` |

More in `references/troubleshooting.md`.

## Limitations

- No session persistence (each question = new browser)
- Rate limits on free Google accounts (≈50 queries/day)
- Sources can be added but not removed; Google Drive / Play Books sources are not supported
- Only sources are queried; Studio notes and chat history are not
- Browser overhead (a few seconds per question)

## Resources (Skill Structure)

- `src/gemini_notebook/` - the `gnb` package (`cli.py` commands, `config.py` page selectors)
- `references/` - extended documentation:
  - `api_reference.md` - every command, option and Python function
  - `troubleshooting.md` - common issues and solutions
  - `usage_patterns.md` - best practices and workflow examples
- `docs/guide.py` - interactive marimo guide for humans (`uv run --group docs marimo edit docs/guide.py`)
