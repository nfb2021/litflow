# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-10-29

### Changed
- **`gnb` command** (Typer) replaces the scripts: `gnb ask`, `gnb add`, `gnb library …`,
  `gnb auth …`, `gnb cleanup`. Installed with `uv tool install`, runs from any directory
- Scripts became the package `src/gemini_notebook/` (`ask`, `sources`, `library`, `auth`,
  `cleanup`, `browser`, `config`, `cli`)
- `-n/--notebook` takes a library ID or a notebook URL (replaces `--notebook-id` / `--notebook-url`)
- Login and library moved from the skill's `data/` folder to the user data folder
  (macOS `~/Library/Application Support/gemini-notebook/`), override with `$GEMINI_NOTEBOOK_HOME`
- Skill renamed `notebooklm` → `gemini_notebook`

### Removed
- `browser_session.py` (unused)

## [2.0.0] - 2026-10-29

Fork: [nfb2021/skills](https://github.com/nfb2021/skills) → `gemini_notebook/`

### Added
- `add_source.py` - add local files, website / YouTube URLs and pasted text to a notebook;
  waits for processing and reports each source as ready / failed
- `--timeout` option for `ask_question.py`
- `docs/guide.py` - interactive marimo guide (`uv run --group docs marimo edit docs/guide.py`)
- `clean_answer()` in `ask_question.py` (answer clean-up as a reusable function)

### Changed
- **uv** replaces pip: `pyproject.toml` + `uv.lock`; run scripts with `uv run scripts/<script>.py`.
  Removed `run.py`, `setup_environment.py`, `requirements.txt` and the unused `python-dotenv`
- Headless browser uses a 1600×1000 viewport (full three-panel layout)
- Docs updated for the Gemini Notebook name; README rewritten

### Fixed
- Google rebrand `notebooklm.google.com` → `notebook.google.com` (login and queries)
- Login detection requires a Google session cookie (no false "already authenticated")
- Stale answers: the newest answer is found by on-screen position (chat list is virtualized)
- Progress placeholders ("Thoughts", "Listed files…", "…ing...") no longer returned as answers
- Citation chips folded into inline `[n]` references
- Feature-announcement popups are closed before typing

## [1.3.0] - 2025-11-21

### Added
- **Modular Architecture** - Refactored codebase for better maintainability
  - New `config.py` - Centralized configuration (paths, selectors, timeouts)
  - New `browser_utils.py` - BrowserFactory and StealthUtils classes
  - Cleaner separation of concerns across all scripts

### Changed
- **Timeout increased to 120 seconds** - Long queries no longer timeout prematurely
  - `ask_question.py`: 30s → 120s
  - `browser_session.py`: 30s → 120s
  - Resolves Issue #4

### Fixed
- **Thinking Message Detection** - Fixed incomplete answers showing placeholder text
  - Now waits for `div.thinking-message` element to disappear before reading answer
  - Answers like "Reviewing the content..." or "Looking for answers..." no longer returned prematurely
  - Works reliably across all languages and NotebookLM UI changes

- **Correct CSS Selectors** - Updated to match current NotebookLM UI
  - Changed from `.response-content, .message-content` to `.to-user-container .message-text-content`
  - Consistent selectors across all scripts

- **Stability Detection** - Improved answer completeness check
  - Now requires 3 consecutive stable polls instead of 1 second wait
  - Prevents truncated responses during streaming

## [1.2.0] - 2025-10-28

### Added
- Initial public release
- NotebookLM integration via browser automation
- Session-based conversations with Gemini 2.5
- Notebook library management
- Knowledge base preparation tools
- Google authentication with persistent sessions
