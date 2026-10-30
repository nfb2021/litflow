# Gemini Notebook Skill Troubleshooting Guide

All commands are `gnb`, which works from any directory.

## Quick Fix Table

| Problem | Solution |
|---------|----------|
| `gnb: command not found` | `uv tool install --editable ~/src/litflow/gemini_notebook` (or from git, see README); put `~/.local/bin` on PATH with `uv tool update-shell` |
| `⚠️ Not authenticated` | `gnb auth setup` (log in in the browser window that opens) |
| Login saved but queries land on the sign-in page | `gnb auth reauth` |
| Browser not found | Install Google Chrome, or `uvx patchright install chrome` |
| Browser crash / hang | Quit leftover Chrome processes, then `gnb cleanup --confirm --preserve-library` and `gnb auth setup` |
| `❌ Timeout waiting for answer` | Long answers: add `--timeout 400`; otherwise retry with `--show-browser` to watch |
| `❌ Could not find query input` | Google changed the page; open with `--show-browser` and update the selectors in `src/gemini_notebook/config.py` |
| Source shows `failed` after `gnb add` | Google could not import it (paywall, blocked site, private video). Retry later, or add it as a PDF or pasted text |
| Rate limit (≈50 queries/day on free accounts) | Wait for the daily reset or switch accounts with `reauth` |
| `❌ Notebook 'x' not found` | `gnb library list` |

## Authentication

```bash
gnb auth status       # Age of the saved login and the data folder
gnb auth setup        # Visible browser, log in manually (10 min default)
gnb auth setup --timeout 15
gnb auth validate     # Open the site and check the login works
gnb auth reauth       # clear + setup, also to switch Google account
gnb auth clear
```

Google sessions expire after a few weeks. When `status` reports a state older than
~30 days, expect to run `reauth`.

## Installation

```bash
uv tool install --editable --force ~/src/litflow/gemini_notebook   # Reinstall gnb
uv tool list                       # Is gnb installed, and from where?
uvx patchright install chrome      # Only if Google Chrome is not installed
```

The skill drives the installed Google Chrome (`channel="chrome"`), not Playwright's Chromium.

## Debugging

```bash
# Watch the browser while it works
gnb ask "test" --show-browser
gnb add -n ID --text "test" --show-browser
```

Page selectors live in `src/gemini_notebook/config.py`. When Google changes the UI, open the notebook
with `--show-browser`, inspect the element, and update the selector there.

## Reset

```bash
# Keep login and library, reinstall the tool
uv tool install --editable --force ~/src/litflow/gemini_notebook

# Delete browser state but keep the notebook library, then log in again
gnb cleanup --confirm --preserve-library
gnb auth setup

# Delete everything in the data folder (login + library)
gnb cleanup --confirm --force
```

## Common Questions

**Why doesn't this work in the Claude web UI?**
It needs a local browser. Use Claude Code on your machine.

**Can I use several Google accounts?**
One at a time: `gnb auth reauth` and log in. Or keep separate data folders with `GEMINI_NOTEBOOK_HOME=~/gnb-other gnb ...` with the other account.

**Is this safe for my Google account?**
It drives a normal Chrome session with your login and only opens notebook.google.com.
A dedicated account is still a good idea for heavy automated use.
