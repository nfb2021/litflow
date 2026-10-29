"""
Simple NotebookLM Question Interface
Based on MCP server implementation - simplified without sessions

Implements hybrid auth approach:
- Persistent browser profile (user_data_dir) for fingerprint consistency
- Manual cookie injection from state.json for session cookies (Playwright bug workaround)
See: https://github.com/microsoft/playwright/issues/36139
"""

import re
import time

from patchright.sync_api import sync_playwright

from .auth import AuthManager
from .browser import BrowserFactory, StealthUtils
from .config import QUERY_INPUT_SELECTORS, RESPONSE_SELECTORS

# Follow-up reminder (adapted from MCP server for stateless operation)
# Since we don't have persistent sessions, we encourage comprehensive questions
# Transient "still working" placeholder text NotebookLM shows in a message
# slot before the real answer replaces it - never treat these as the answer.
PLACEHOLDER_RE = re.compile(
    r"^(?:Thoughts|Investigating [^\n]*|Reading through pages\.\.\.|Scanning the text[^\n]*"
    r"|Listed files[^\n]*"
    # Any other single-line progress status ("Analyzing your files...", "Scanning the text…")
    r"|[^\n]{0,80}(?:\.\.\.|…))\s*(?:expand_more)?$"
)


def _bottom_most_response(page, selectors):
    """
    Return (text, y) of the visually LOWEST (most recent) chat message
    matching any of the selectors.

    The chat panel is virtualized: query_selector_all() returns nodes in an
    order that does NOT reliably match chronological/visual order (mounted
    nodes can be reordered or reused as the window slides). DOM order and
    element count are therefore both unreliable signals for "the newest
    message" - the only reliable signal is vertical position on the page,
    since chat always renders older-to-newer top-to-bottom.
    """
    best_text, best_y = None, None
    for selector in selectors:
        try:
            for el in page.query_selector_all(selector):
                box = el.bounding_box()
                if not box:
                    continue
                if best_y is None or box["y"] > best_y:
                    text = el.inner_text().strip()
                    best_text, best_y = text, box["y"]
        except Exception:
            continue
    return best_text, best_y


def clean_answer(answer):
    """Turn the raw inner_text() of an answer bubble into readable text"""
    # Strip NotebookLM's collapsible "Thoughts" reasoning widget, which
    # inner_text() captures as literal text at the top of the message
    # (e.g. "Thoughts\nexpand_more\n...reasoning...\nmore_horiz\n<actual answer>")
    answer = re.sub(r"^Thoughts\s+expand_more\s+", "", answer)

    # Citation chips render as their own lines ("\n1\nmore_horiz\n.") - fold
    # them back inline as " [1]" and drop the chip's icon text.
    answer = re.sub(r"\n?more_horiz(?=\n|$)", "", answer)
    answer = re.sub(r"\n(\d+(?:\s*[-–,]\s*\d+)*)(?=\n|$)", r" [\1]", answer)
    answer = re.sub(r"\] \[", "][", answer)
    answer = re.sub(r"(\])\n(?=[.,;:!?)])", r"\1", answer)
    return answer


FOLLOW_UP_REMINDER = (
    "\n\nEXTREMELY IMPORTANT: Is that ALL you need to know? "
    "You can always ask another question! Think about it carefully: "
    "before you reply to the user, review their original request and this answer. "
    "If anything is still unclear or missing, ask me another comprehensive question "
    "that includes all necessary context (since each question opens a new browser session)."
)


def ask_notebook(
    question: str, notebook_url: str, headless: bool = True, timeout: int = 240
) -> str:
    """
    Ask a question to NotebookLM

    Args:
        question: Question to ask
        notebook_url: NotebookLM notebook URL
        headless: Run browser in headless mode

    Returns:
        Answer text from NotebookLM
    """
    auth = AuthManager()

    if not auth.is_authenticated():
        print("⚠️ Not authenticated. Run: gnb auth setup")
        return None

    print(f"💬 Asking: {question}")
    print(f"📚 Notebook: {notebook_url}")

    playwright = None
    context = None

    try:
        # Start playwright
        playwright = sync_playwright().start()

        # Launch persistent browser context using factory
        context = BrowserFactory.launch_persistent_context(
            playwright, headless=headless
        )

        # Navigate to notebook
        page = context.new_page()
        print("  🌐 Opening notebook...")
        page.goto(notebook_url, wait_until="domcontentloaded")

        # Wait for NotebookLM (Google rebranded notebooklm.google.com -> notebook.google.com)
        page.wait_for_url(
            re.compile(r"^https://notebook(?:lm)?\.google\.com/"), timeout=45000
        )

        # Wait for query input (MCP approach)
        print("  ⏳ Waiting for query input...")
        query_element = None

        for selector in QUERY_INPUT_SELECTORS:
            try:
                query_element = page.wait_for_selector(
                    selector,
                    timeout=20000,
                    state="visible",  # Only check visibility, not disabled!
                )
                if query_element:
                    print(f"  ✓ Found input: {selector}")
                    break
            except Exception:
                continue

        if not query_element:
            print("  ❌ Could not find query input")
            return None

        StealthUtils.dismiss_dialogs(page)

        # Snapshot the text of the visually-bottom-most (most recent) response
        # BEFORE we submit, so we don't mistake pre-existing chat history for
        # the live answer.
        baseline_last_text, _ = _bottom_most_response(page, RESPONSE_SELECTORS)

        # Type question (human-like, fast)
        print("  ⏳ Typing question...")

        # Use primary selector for typing
        input_selector = QUERY_INPUT_SELECTORS[0]
        StealthUtils.human_type(page, input_selector, question)

        # Submit
        print("  📤 Submitting...")
        page.keyboard.press("Enter")

        # Small pause
        StealthUtils.random_delay(500, 1500)

        # Wait for response (MCP approach: poll for stable text)
        print("  ⏳ Waiting for answer...")

        answer = None
        stable_count = 0
        last_text = None
        deadline = time.time() + timeout

        while time.time() < deadline:
            # NotebookLM still shows this element (class "thinking-message is-changing") while working
            try:
                thinking_element = page.query_selector("div.thinking-message")
                if thinking_element and thinking_element.is_visible():
                    stable_count = 0
                    time.sleep(1)
                    continue
            except Exception:
                pass  # element vanished mid-check: keep polling

            # Find the visually bottom-most (newest) response bubble
            text, _ = _bottom_most_response(page, RESPONSE_SELECTORS)

            # Still showing the pre-existing (stale) content - the new answer
            # hasn't landed yet.
            if text and text != baseline_last_text and not PLACEHOLDER_RE.match(text):
                if text == last_text:
                    stable_count += 1
                    if stable_count >= 3:  # Stable for 3 polls
                        answer = text
                        break
                else:
                    stable_count = 0
                    last_text = text

            if answer:
                break

            time.sleep(1)

        if not answer:
            print("  ❌ Timeout waiting for answer")
            return None

        answer = clean_answer(answer)

        print("  ✅ Got answer!")
        # Add follow-up reminder to encourage Claude to ask more questions
        return answer + FOLLOW_UP_REMINDER

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return None

    finally:
        # Always clean up
        if context:
            try:
                context.close()
            except Exception:
                pass  # already closed / stopped

        if playwright:
            try:
                playwright.stop()
            except Exception:
                pass  # already closed / stopped
