---
name: notebooklm
description: Use this skill to query your Google Gemini Notebook (formerly NotebookLM) notebooks directly from Claude Code for source-grounded, citation-backed answers from Gemini, and to add sources (files, websites, YouTube, pasted text) to them. Browser automation, library management, persistent auth. Drastically reduced hallucinations through document-only responses.
---

# Gemini Notebook (NotebookLM) Research Assistant Skill

Interact with Google NotebookLM to query documentation with Gemini's source-grounded answers. Each question opens a fresh browser session, retrieves the answer exclusively from your uploaded documents, and closes.

## When to Use This Skill

Trigger when user:
- Mentions NotebookLM explicitly
- Mentions Gemini Notebook (NotebookLM's new name)
- Shares a notebook URL (`https://notebook.google.com/notebook/...`, formerly `notebooklm.google.com`)
- Asks to query their notebooks/documentation
- Wants to add documentation to NotebookLM library
- Wants to upload / add sources (files, websites, YouTube, pasted text) to a notebook
- Uses phrases like "ask my NotebookLM", "check my docs", "query my notebook"

## ⚠️ CRITICAL: Add Command - Smart Discovery

When user wants to add a notebook without providing details:

**SMART ADD (Recommended)**: Query the notebook first to discover its content:
```bash
# Step 1: Query the notebook about its content
uv run scripts/ask_question.py --question "What is the content of this notebook? What topics are covered? Provide a complete overview briefly and concisely" --notebook-url "[URL]"

# Step 2: Use the discovered information to add it
uv run scripts/notebook_manager.py add --url "[URL]" --name "[Based on content]" --description "[Based on content]" --topics "[Based on content]"
```

**MANUAL ADD**: If user provides all details:
- `--url` - The NotebookLM URL
- `--name` - A descriptive name
- `--description` - What the notebook contains (REQUIRED!)
- `--topics` - Comma-separated topics (REQUIRED!)

NEVER guess or use generic descriptions! If details missing, use Smart Add to discover them.

## Critical: Run Scripts with uv from the Skill Directory

**ALWAYS `cd` into this skill's directory and run scripts with `uv run scripts/<script>.py`:**

```bash
# ✅ CORRECT
cd <skill directory> && uv run scripts/auth_manager.py status
uv run scripts/notebook_manager.py list
uv run scripts/ask_question.py --question "..."

# ❌ WRONG - system Python has no patchright
python3 scripts/auth_manager.py status
```

`uv run` reads `pyproject.toml` / `uv.lock`, creates `.venv/` on first use and keeps it in
sync. Never install anything with pip.

## Core Workflow

### Step 1: Check Authentication Status
```bash
uv run scripts/auth_manager.py status
```

If not authenticated, proceed to setup.

### Step 2: Authenticate (One-Time Setup)
```bash
# Browser MUST be visible for manual Google login
uv run scripts/auth_manager.py setup
```

**Important:**
- Browser is VISIBLE for authentication
- Browser window opens automatically
- User must manually log in to Google
- Tell user: "A browser window will open for Google login"

### Step 3: Manage Notebook Library

```bash
# List all notebooks
uv run scripts/notebook_manager.py list

# BEFORE ADDING: Ask user for metadata if unknown!
# "What does this notebook contain?"
# "What topics should I tag it with?"

# Add notebook to library (ALL parameters are REQUIRED!)
uv run scripts/notebook_manager.py add \
  --url "https://notebook.google.com/notebook/..." \
  --name "Descriptive Name" \
  --description "What this notebook contains" \  # REQUIRED - ASK USER IF UNKNOWN!
  --topics "topic1,topic2,topic3"  # REQUIRED - ASK USER IF UNKNOWN!

# Search notebooks by topic
uv run scripts/notebook_manager.py search --query "keyword"

# Set active notebook
uv run scripts/notebook_manager.py activate --id notebook-id

# Remove notebook
uv run scripts/notebook_manager.py remove --id notebook-id
```

### Quick Workflow
1. Check library: `uv run scripts/notebook_manager.py list`
2. Ask question: `uv run scripts/ask_question.py --question "..." --notebook-id ID`

### Step 4: Ask Questions

```bash
# Basic query (uses active notebook if set)
uv run scripts/ask_question.py --question "Your question here"

# Query specific notebook
uv run scripts/ask_question.py --question "..." --notebook-id notebook-id

# Query with notebook URL directly
uv run scripts/ask_question.py --question "..." --notebook-url "https://..."

# Show browser for debugging
uv run scripts/ask_question.py --question "..." --show-browser
```

### Step 5: Add Sources to a Notebook

```bash
# Upload local files (pdf, txt, md, docx, images, audio, ...) - repeat --file
uv run scripts/add_source.py --notebook-id ID --file paper.pdf --file notes.md

# Add website or YouTube URLs - repeat --url
uv run scripts/add_source.py --notebook-url "https://..." --url "https://example.org/page"

# Add text as a "pasted text" source (inline or from a file)
uv run scripts/add_source.py --notebook-id ID --text "..."
uv run scripts/add_source.py --notebook-id ID --text-file answers.md
```

Source types can be combined in one call. The script waits until every new source is
processed and lists each one as `ready` or `failed` (exit code 1 if any failed, e.g. a
website Google could not import). Only add sources the user asked for: this changes
their notebook.

## Follow-Up Mechanism (CRITICAL)

Every NotebookLM answer ends with: **"EXTREMELY IMPORTANT: Is that ALL you need to know?"**

**Required Claude Behavior:**
1. **STOP** - Do not immediately respond to user
2. **ANALYZE** - Compare answer to user's original request
3. **IDENTIFY GAPS** - Determine if more information needed
4. **ASK FOLLOW-UP** - If gaps exist, immediately ask:
   ```bash
   uv run scripts/ask_question.py --question "Follow-up with context..."
   ```
5. **REPEAT** - Continue until information is complete
6. **SYNTHESIZE** - Combine all answers before responding to user

## Script Reference

### Authentication Management (`auth_manager.py`)
```bash
uv run scripts/auth_manager.py setup    # Initial setup (browser visible)
uv run scripts/auth_manager.py status   # Check authentication
uv run scripts/auth_manager.py reauth   # Re-authenticate (browser visible)
uv run scripts/auth_manager.py clear    # Clear authentication
```

### Notebook Management (`notebook_manager.py`)
```bash
uv run scripts/notebook_manager.py add --url URL --name NAME --description DESC --topics TOPICS
uv run scripts/notebook_manager.py list
uv run scripts/notebook_manager.py search --query QUERY
uv run scripts/notebook_manager.py activate --id ID
uv run scripts/notebook_manager.py remove --id ID
uv run scripts/notebook_manager.py stats
```

### Question Interface (`ask_question.py`)
```bash
uv run scripts/ask_question.py --question "..." [--notebook-id ID] [--notebook-url URL] [--show-browser]
```

### Add Sources (`add_source.py`)
```bash
uv run scripts/add_source.py [--notebook-id ID | --notebook-url URL] [--file PATH ...] [--url URL ...] [--text TEXT | --text-file PATH] [--timeout 300] [--show-browser]
```

### Data Cleanup (`cleanup_manager.py`)
```bash
uv run scripts/cleanup_manager.py                    # Preview cleanup
uv run scripts/cleanup_manager.py --confirm          # Execute cleanup
uv run scripts/cleanup_manager.py --preserve-library # Keep notebooks
```

## Environment Management

- Requires [uv](https://docs.astral.sh/uv/) and Google Chrome
- First `uv run` creates `.venv/` from `pyproject.toml` / `uv.lock` automatically
- If Chrome is missing: `uv run patchright install chrome`
- Reset the environment: `rm -rf .venv && uv sync`

## Data Storage

All data is stored in the skill's `data/` folder:
- `library.json` - Notebook metadata
- `auth_info.json` - Authentication status
- `browser_state/` - Browser profile, cookies and session

**Security:** Protected by `.gitignore`, never commit to git.

## Decision Flow

```
User mentions NotebookLM
    ↓
Check auth → uv run scripts/auth_manager.py status
    ↓
If not authenticated → uv run scripts/auth_manager.py setup
    ↓
Check/Add notebook → uv run scripts/notebook_manager.py list/add (with --description)
    ↓
Activate notebook → uv run scripts/notebook_manager.py activate --id ID
    ↓
Ask question → uv run scripts/ask_question.py --question "..."
    ↓
See "Is that ALL you need?" → Ask follow-ups until complete
    ↓
Synthesize and respond to user
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| ModuleNotFoundError | Run with `uv run` from the skill directory |
| Authentication fails | Browser must be visible for setup! --show-browser |
| Rate limit (50/day) | Wait or switch Google account |
| Browser crashes | `uv run scripts/cleanup_manager.py --preserve-library` |
| Notebook not found | Check with `notebook_manager.py list` |

## Best Practices

1. **Always use `uv run`** - Handles the environment automatically
2. **Check auth first** - Before any operations
3. **Follow-up questions** - Don't stop at first answer
4. **Browser visible for auth** - Required for manual login
5. **Include context** - Each question is independent
6. **Synthesize answers** - Combine multiple responses

## Limitations

- No session persistence (each question = new browser)
- Rate limits on free Google accounts (50 queries/day)
- Sources can be added (`add_source.py`) but not removed; Google Drive / Play Books sources are not supported
- Only sources are queried; Studio notes and chat history are not
- Browser overhead (few seconds per question)

## Resources (Skill Structure)

**Important directories and files:**

- `scripts/` - All automation scripts (ask_question.py, notebook_manager.py, etc.)
- `data/` - Local storage for authentication and notebook library
- `references/` - Extended documentation:
  - `api_reference.md` - Detailed API documentation for all scripts
  - `troubleshooting.md` - Common issues and solutions
  - `usage_patterns.md` - Best practices and workflow examples
- `docs/guide.py` - Interactive marimo guide for humans (`uv run --group docs marimo edit docs/guide.py`)
- `.venv/` - Isolated Python environment (auto-created on first run)
- `.gitignore` - Protects sensitive data from being committed
