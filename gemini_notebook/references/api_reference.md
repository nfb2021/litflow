# Gemini Notebook Skill API Reference

Complete API documentation for all skill scripts (Gemini Notebook was formerly NotebookLM).

## Important: Run with uv from the Skill Directory

```bash
# ✅ CORRECT:
uv run scripts/[script_name].py [arguments]

# ❌ WRONG:
python3 scripts/[script_name].py [arguments]  # system Python has no patchright
```

`uv run` creates `.venv/` from `pyproject.toml` / `uv.lock` on first use.

## Core Scripts

### ask_question.py
Query NotebookLM with automated browser interaction.

```bash
# Basic usage
uv run scripts/ask_question.py --question "Your question"

# With specific notebook
uv run scripts/ask_question.py --question "..." --notebook-id notebook-id

# With direct URL
uv run scripts/ask_question.py --question "..." --notebook-url "https://..."

# Show browser (debugging)
uv run scripts/ask_question.py --question "..." --show-browser
```

**Parameters:**
- `--question` (required): Question to ask
- `--notebook-id`: Use notebook from library
- `--notebook-url`: Use URL directly
- `--show-browser`: Make browser visible

**Returns:** Answer text with follow-up prompt appended

### add_source.py
Add sources to a notebook through the "Add sources" dialog.

```bash
# Upload local files (repeatable)
uv run scripts/add_source.py --notebook-id ID --file paper.pdf --file notes.md

# Website / YouTube URLs (repeatable)
uv run scripts/add_source.py --notebook-id ID --url "https://..."

# Pasted text, inline or from a file
uv run scripts/add_source.py --notebook-id ID --text "..."
uv run scripts/add_source.py --notebook-id ID --text-file answers.md
```

**Parameters:**
- `--notebook-id` / `--notebook-url`: Target notebook (defaults to the active notebook)
- `--file`: Local file to upload (repeatable)
- `--url`: Website or YouTube URL (repeatable)
- `--text` / `--text-file`: Text added as one pasted-text source
- `--timeout`: Seconds to wait for processing (default 300)
- `--show-browser`: Make browser visible

**Returns:** List of new sources with status `ready` / `failed` / `processing`;
exit code 0 only if all are `ready`

### notebook_manager.py
Manage notebook library with CRUD operations.

```bash
# Smart Add (discover content first)
uv run scripts/ask_question.py --question "What is the content of this notebook? What topics are covered? Provide a complete overview briefly and concisely" --notebook-url "[URL]"
# Then add with discovered info
uv run scripts/notebook_manager.py add \
  --url "https://notebook.google.com/notebook/..." \
  --name "Name" \
  --description "Description" \
  --topics "topic1,topic2"

# Direct add (when you know the content)
uv run scripts/notebook_manager.py add \
  --url "https://notebook.google.com/notebook/..." \
  --name "Name" \
  --description "What it contains" \
  --topics "topic1,topic2"

# List notebooks
uv run scripts/notebook_manager.py list

# Search notebooks
uv run scripts/notebook_manager.py search --query "keyword"

# Activate notebook
uv run scripts/notebook_manager.py activate --id notebook-id

# Remove notebook
uv run scripts/notebook_manager.py remove --id notebook-id

# Show statistics
uv run scripts/notebook_manager.py stats
```

**Commands:**
- `add`: Add notebook (requires --url, --name, --topics)
- `list`: Show all notebooks
- `search`: Find notebooks by keyword
- `activate`: Set default notebook
- `remove`: Delete from library
- `stats`: Display library statistics

### auth_manager.py
Handle Google authentication and browser state.

```bash
# Setup (browser visible for login)
uv run scripts/auth_manager.py setup

# Check status
uv run scripts/auth_manager.py status

# Re-authenticate
uv run scripts/auth_manager.py reauth

# Clear authentication
uv run scripts/auth_manager.py clear
```

**Commands:**
- `setup`: Initial authentication (browser MUST be visible)
- `status`: Check if authenticated
- `reauth`: Clear and re-setup
- `clear`: Remove all auth data

### cleanup_manager.py
Clean skill data with preservation options.

```bash
# Preview cleanup
uv run scripts/cleanup_manager.py

# Execute cleanup
uv run scripts/cleanup_manager.py --confirm

# Keep library
uv run scripts/cleanup_manager.py --confirm --preserve-library

# Force without prompt
uv run scripts/cleanup_manager.py --confirm --force
```

**Options:**
- `--confirm`: Actually perform cleanup
- `--preserve-library`: Keep notebook library
- `--force`: Skip confirmation prompt

## Python API Usage

### Using subprocess

```python
import subprocess
import json

result = subprocess.run([
    "uv", "run", "scripts/ask_question.py",
    "--question", "Your question",
    "--notebook-id", "notebook-id"
], capture_output=True, text=True)

answer = result.stdout
```

### Direct imports

```python
# Run inside the skill's environment, e.g. `uv run python` from the skill directory,
# with scripts/ on sys.path
from notebook_manager import NotebookLibrary
from auth_manager import AuthManager

library = NotebookLibrary()
notebooks = library.list_notebooks()

auth = AuthManager()
is_auth = auth.is_authenticated()
```

## Data Storage

Location: `data/` in the skill directory

```
data/
├── library.json       # Notebook metadata
├── auth_info.json     # Auth status
└── browser_state/     # Browser cookies
    └── state.json
```

**Security:** Protected by `.gitignore`, never commit.

## Error Handling

Common patterns:

```python
result = subprocess.run([
    "uv", "run", "scripts/ask_question.py",
    "--question", "Question"
], capture_output=True, text=True)

if result.returncode != 0:
    error = result.stderr
    if "rate limit" in error.lower():
        # Wait or switch accounts
        pass
    elif "not authenticated" in error.lower():
        # Run auth setup
        subprocess.run(["uv", "run", "scripts/auth_manager.py", "setup"])
```

## Rate Limits

Free Google accounts: 50 queries/day

Solutions:
1. Wait for reset (midnight PST)
2. Switch accounts with `reauth`
3. Use multiple Google accounts

## Advanced Patterns

### Parallel Queries

```python
import concurrent.futures
import subprocess

def query(question, notebook_id):
    result = subprocess.run([
        "uv", "run", "scripts/ask_question.py",
        "--question", question,
        "--notebook-id", notebook_id
    ], capture_output=True, text=True)
    return result.stdout

# Run multiple queries simultaneously
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    futures = [
        executor.submit(query, q, nb)
        for q, nb in zip(questions, notebooks)
    ]
    results = [f.result() for f in futures]
```

### Batch Processing

```python
def batch_research(questions, notebook_id):
    results = []
    for question in questions:
        result = subprocess.run([
            "uv", "run", "scripts/ask_question.py",
            "--question", question,
            "--notebook-id", notebook_id
        ], capture_output=True, text=True)
        results.append(result.stdout)
        time.sleep(2)  # Avoid rate limits
    return results
```

## Module Classes

### NotebookLibrary
- `add_notebook(url, name, topics)`
- `list_notebooks()`
- `search_notebooks(query)`
- `get_notebook(notebook_id)`
- `activate_notebook(notebook_id)`
- `remove_notebook(notebook_id)`

### AuthManager
- `is_authenticated()`
- `setup_auth(headless=False)`
- `get_auth_info()`
- `clear_auth()`
- `validate_auth()`

### BrowserSession (internal)
- Handles browser automation
- Manages stealth behavior
- Not intended for direct use

## Best Practices

1. **Always use `uv run`** - Ensures environment
2. **Check auth first** - Before operations
3. **Handle rate limits** - Implement retries
4. **Include context** - Questions are independent
5. **Clean sessions** - Use cleanup_manager