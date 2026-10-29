# Gemini Notebook Skill Troubleshooting Guide

All commands run from the skill directory with `uv run`.

## Quick Fix Table

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: patchright` | Run with `uv run scripts/<script>.py` from the skill directory, not with the system Python |
| `⚠️ Not authenticated` | `uv run scripts/auth_manager.py setup` (log in in the browser window that opens) |
| Login saved but queries land on the sign-in page | `uv run scripts/auth_manager.py reauth` |
| Browser not found | Install Google Chrome, or `uv run patchright install chrome` |
| Browser crash / hang | Quit leftover Chrome processes, then `uv run scripts/cleanup_manager.py --confirm --preserve-library` and `uv run scripts/auth_manager.py setup` |
| `❌ Timeout waiting for answer` | Long answers: add `--timeout 400`; otherwise retry with `--show-browser` to watch |
| `❌ Could not find query input` | Google changed the page; open with `--show-browser` and update the selectors in `scripts/config.py` |
| Source shows `failed` after `add_source.py` | Google could not import it (paywall, blocked site, private video). Retry later, or add it as a PDF or pasted text |
| Rate limit (≈50 queries/day on free accounts) | Wait for the daily reset or switch accounts with `reauth` |
| `❌ Notebook 'x' not found` | `uv run scripts/notebook_manager.py list` |

## Authentication

```bash
uv run scripts/auth_manager.py status     # Age of the saved login
uv run scripts/auth_manager.py setup      # Visible browser, log in manually (10 min default)
uv run scripts/auth_manager.py setup --timeout 15
uv run scripts/auth_manager.py validate   # Open the site and check the login works
uv run scripts/auth_manager.py reauth     # clear + setup, also to switch Google account
uv run scripts/auth_manager.py clear
```

Google sessions expire after a few weeks. When `status` reports a state older than
~30 days, expect to run `reauth`.

## Environment

```bash
uv sync                            # (Re)create .venv from pyproject.toml / uv.lock
rm -rf .venv && uv sync            # Clean rebuild
uv run patchright install chrome   # Only if Google Chrome is not installed
```

The skill drives the installed Google Chrome (`channel="chrome"`), not Playwright's Chromium.

## Debugging

```bash
# Watch the browser while it works
uv run scripts/ask_question.py --question "test" --show-browser
uv run scripts/add_source.py --notebook-id ID --text "test" --show-browser
```

Page selectors live in `scripts/config.py`. When Google changes the UI, open the notebook
with `--show-browser`, inspect the element, and update the selector there.

## Reset

```bash
# Keep login and library, rebuild the environment
rm -rf .venv && uv sync

# Delete browser state but keep the notebook library, then log in again
uv run scripts/cleanup_manager.py --confirm --preserve-library
uv run scripts/auth_manager.py setup

# Delete everything in data/ (login + library)
uv run scripts/cleanup_manager.py --confirm --force
```

## Common Questions

**Why doesn't this work in the Claude web UI?**
It needs a local browser. Use Claude Code on your machine.

**Can I use several Google accounts?**
One at a time: `uv run scripts/auth_manager.py reauth` and log in with the other account.

**Is this safe for my Google account?**
It drives a normal Chrome session with your login and only opens notebook.google.com.
A dedicated account is still a good idea for heavy automated use.
