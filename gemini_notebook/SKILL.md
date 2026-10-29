---
name: notebooklm
description: Use this skill to query your Google Gemini Notebook (formerly NotebookLM) notebooks directly from Claude Code for source-grounded, citation-backed answers from Gemini, and to add sources (files, websites, YouTube, pasted text) to them. Browser automation, library management, persistent auth. Drastically reduced hallucinations through document-only responses.
---

# NotebookLM Research Assistant Skill

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
python3 scripts/run.py ask_question.py --question "What is the content of this notebook? What topics are covered? Provide a complete overview briefly and concisely" --notebook-url "[URL]"

# Step 2: Use the discovered information to add it
python3 scripts/run.py notebook_manager.py add --url "[URL]" --name "[Based on content]" --description "[Based on content]" --topics "[Based on content]"
```

**MANUAL ADD**: If user provides all details:
- `--url` - The NotebookLM URL
- `--name` - A descriptive name
- `--description` - What the notebook contains (REQUIRED!)
- `--topics` - Comma-separated topics (REQUIRED!)

NEVER guess or use generic descriptions! If details missing, use Smart Add to discover them.

## Critical: Always Use run.py Wrapper

**NEVER call scripts directly. ALWAYS use `python3 scripts/run.py [script]`:**

```bash
# ✅ CORRECT - Always use run.py:
python3 scripts/run.py auth_manager.py status
python3 scripts/run.py notebook_manager.py list
python3 scripts/run.py ask_question.py --question "..."

# ❌ WRONG - Never call directly:
python3 scripts/auth_manager.py status  # Fails without venv!
```

The `run.py` wrapper automatically:
1. Creates `.venv` if needed
2. Installs all dependencies
3. Activates environment
4. Executes script properly

## Core Workflow

### Step 1: Check Authentication Status
```bash
python3 scripts/run.py auth_manager.py status
```

If not authenticated, proceed to setup.

### Step 2: Authenticate (One-Time Setup)
```bash
# Browser MUST be visible for manual Google login
python3 scripts/run.py auth_manager.py setup
```

**Important:**
- Browser is VISIBLE for authentication
- Browser window opens automatically
- User must manually log in to Google
- Tell user: "A browser window will open for Google login"

### Step 3: Manage Notebook Library

```bash
# List all notebooks
python3 scripts/run.py notebook_manager.py list

# BEFORE ADDING: Ask user for metadata if unknown!
# "What does this notebook contain?"
# "What topics should I tag it with?"

# Add notebook to library (ALL parameters are REQUIRED!)
python3 scripts/run.py notebook_manager.py add \
  --url "https://notebooklm.google.com/notebook/..." \
  --name "Descriptive Name" \
  --description "What this notebook contains" \  # REQUIRED - ASK USER IF UNKNOWN!
  --topics "topic1,topic2,topic3"  # REQUIRED - ASK USER IF UNKNOWN!

# Search notebooks by topic
python3 scripts/run.py notebook_manager.py search --query "keyword"

# Set active notebook
python3 scripts/run.py notebook_manager.py activate --id notebook-id

# Remove notebook
python3 scripts/run.py notebook_manager.py remove --id notebook-id
```

### Quick Workflow
1. Check library: `python3 scripts/run.py notebook_manager.py list`
2. Ask question: `python3 scripts/run.py ask_question.py --question "..." --notebook-id ID`

### Step 4: Ask Questions

```bash
# Basic query (uses active notebook if set)
python3 scripts/run.py ask_question.py --question "Your question here"

# Query specific notebook
python3 scripts/run.py ask_question.py --question "..." --notebook-id notebook-id

# Query with notebook URL directly
python3 scripts/run.py ask_question.py --question "..." --notebook-url "https://..."

# Show browser for debugging
python3 scripts/run.py ask_question.py --question "..." --show-browser
```

### Step 5: Add Sources to a Notebook

```bash
# Upload local files (pdf, txt, md, docx, images, audio, ...) - repeat --file
python3 scripts/run.py add_source.py --notebook-id ID --file paper.pdf --file notes.md

# Add website or YouTube URLs - repeat --url
python3 scripts/run.py add_source.py --notebook-url "https://..." --url "https://example.org/page"

# Add text as a "pasted text" source (inline or from a file)
python3 scripts/run.py add_source.py --notebook-id ID --text "..."
python3 scripts/run.py add_source.py --notebook-id ID --text-file answers.md
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
   python3 scripts/run.py ask_question.py --question "Follow-up with context..."
   ```
5. **REPEAT** - Continue until information is complete
6. **SYNTHESIZE** - Combine all answers before responding to user

## Script Reference

### Authentication Management (`auth_manager.py`)
```bash
python3 scripts/run.py auth_manager.py setup    # Initial setup (browser visible)
python3 scripts/run.py auth_manager.py status   # Check authentication
python3 scripts/run.py auth_manager.py reauth   # Re-authenticate (browser visible)
python3 scripts/run.py auth_manager.py clear    # Clear authentication
```

### Notebook Management (`notebook_manager.py`)
```bash
python3 scripts/run.py notebook_manager.py add --url URL --name NAME --description DESC --topics TOPICS
python3 scripts/run.py notebook_manager.py list
python3 scripts/run.py notebook_manager.py search --query QUERY
python3 scripts/run.py notebook_manager.py activate --id ID
python3 scripts/run.py notebook_manager.py remove --id ID
python3 scripts/run.py notebook_manager.py stats
```

### Question Interface (`ask_question.py`)
```bash
python3 scripts/run.py ask_question.py --question "..." [--notebook-id ID] [--notebook-url URL] [--show-browser]
```

### Add Sources (`add_source.py`)
```bash
python3 scripts/run.py add_source.py [--notebook-id ID | --notebook-url URL] [--file PATH ...] [--url URL ...] [--text TEXT | --text-file PATH] [--timeout 300] [--show-browser]
```

### Data Cleanup (`cleanup_manager.py`)
```bash
python3 scripts/run.py cleanup_manager.py                    # Preview cleanup
python3 scripts/run.py cleanup_manager.py --confirm          # Execute cleanup
python3 scripts/run.py cleanup_manager.py --preserve-library # Keep notebooks
```

## Environment Management

The virtual environment is automatically managed:
- First run creates `.venv` automatically
- Dependencies install automatically
- Chromium browser installs automatically
- Everything isolated in skill directory

Manual setup (only if automatic fails):
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
python -m patchright install chromium
```

## Data Storage

All data stored in `~/.claude/skills/notebooklm/data/`:
- `library.json` - Notebook metadata
- `auth_info.json` - Authentication status
- `browser_state/` - Browser cookies and session

**Security:** Protected by `.gitignore`, never commit to git.

## Configuration

Optional `.env` file in skill directory:
```env
HEADLESS=false           # Browser visibility
SHOW_BROWSER=false       # Default browser display
STEALTH_ENABLED=true     # Human-like behavior
TYPING_WPM_MIN=160       # Typing speed
TYPING_WPM_MAX=240
DEFAULT_NOTEBOOK_ID=     # Default notebook
```

## Decision Flow

```
User mentions NotebookLM
    ↓
Check auth → python3 scripts/run.py auth_manager.py status
    ↓
If not authenticated → python3 scripts/run.py auth_manager.py setup
    ↓
Check/Add notebook → python3 scripts/run.py notebook_manager.py list/add (with --description)
    ↓
Activate notebook → python3 scripts/run.py notebook_manager.py activate --id ID
    ↓
Ask question → python3 scripts/run.py ask_question.py --question "..."
    ↓
See "Is that ALL you need?" → Ask follow-ups until complete
    ↓
Synthesize and respond to user
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| ModuleNotFoundError | Use `run.py` wrapper |
| Authentication fails | Browser must be visible for setup! --show-browser |
| Rate limit (50/day) | Wait or switch Google account |
| Browser crashes | `python3 scripts/run.py cleanup_manager.py --preserve-library` |
| Notebook not found | Check with `notebook_manager.py list` |

## Best Practices

1. **Always use run.py** - Handles environment automatically
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
- `.venv/` - Isolated Python environment (auto-created on first run)
- `.gitignore` - Protects sensitive data from being committed
