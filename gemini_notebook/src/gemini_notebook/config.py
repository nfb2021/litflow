"""
Configuration for the Gemini Notebook skill
Centralizes constants, selectors, and paths
"""

import os
from pathlib import Path

from platformdirs import user_data_path

# Paths: login and library live in the user data folder
# (macOS: ~/Library/Application Support/gemini-notebook), override with $GEMINI_NOTEBOOK_HOME
DATA_DIR = Path(
    os.environ.get("GEMINI_NOTEBOOK_HOME")
    or user_data_path("gemini-notebook", appauthor=False)
).expanduser()
BROWSER_STATE_DIR = DATA_DIR / "browser_state"
BROWSER_PROFILE_DIR = BROWSER_STATE_DIR / "browser_profile"
STATE_FILE = BROWSER_STATE_DIR / "state.json"
AUTH_INFO_FILE = DATA_DIR / "auth_info.json"
LIBRARY_FILE = DATA_DIR / "library.json"

# NotebookLM Selectors
QUERY_INPUT_SELECTORS = [
    "textarea.query-box-input",  # Primary
    'textarea[aria-label="Feld für Anfragen"]',  # Fallback German
    'textarea[aria-label="Input for queries"]',  # Fallback English
]

RESPONSE_SELECTORS = [
    ".to-user-container .message-text-content",  # Primary
    "[data-message-author='bot']",
    "[data-message-author='assistant']",
]

# Close button of promo/announcement modals shown over a notebook
DIALOG_CLOSE_SELECTOR = "mat-dialog-container button[aria-label*='lose' i]"

# Add-source dialog (Gemini Notebook)
ADD_SOURCE_BUTTON = "button[aria-label='Add source']"
SOURCE_ACTION_BUTTON = "mat-dialog-container button.source-action-button:has-text('{}')"
URL_INPUT = "mat-dialog-container textarea[aria-label='Enter URLs']"
TEXT_INPUT = "mat-dialog-container textarea[aria-label='Pasted text']"
INSERT_BUTTON = "mat-dialog-container button:has-text('Insert')"
# Source list rows: processed rows get a "Select <title>" checkbox, failed
# imports get the error class and an "Error info" icon instead
SOURCE_ROW = ".source-panel .single-source-container"
SOURCE_ROW_TITLE = "button.source-stretched-button"
SOURCE_ROW_READY = "input[type=checkbox]"
SOURCE_ROW_ERROR_CLASS = "single-source-error-container"

# Browser Configuration
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",  # Patches navigator.webdriver
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
]

DESKTOP_VIEWPORT = {"width": 1600, "height": 1000}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Timeouts
LOGIN_TIMEOUT_MINUTES = 10
QUERY_TIMEOUT_SECONDS = 120
PAGE_LOAD_TIMEOUT = 30000
