#!/usr/bin/env python3
"""
Add sources to a Gemini Notebook (formerly NotebookLM) notebook

Supports the three source types of the "Add sources" dialog:
- local files (pdf, txt, md, docx, images, audio, ...)
- website / YouTube URLs
- pasted text
"""

import argparse
import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from auth_manager import AuthManager
from notebook_manager import NotebookLibrary
from config import (
    ADD_SOURCE_BUTTON, SOURCE_ACTION_BUTTON, URL_INPUT, TEXT_INPUT,
    INSERT_BUTTON, SOURCE_ROW, SOURCE_ROW_TITLE, SOURCE_ROW_READY,
    SOURCE_ROW_ERROR_CLASS
)
from browser_utils import BrowserFactory, StealthUtils


def _source_rows(page):
    """(title, status) of every listed source; status is ready/failed/processing"""
    rows = []
    for row in page.query_selector_all(SOURCE_ROW):
        title_el = row.query_selector(SOURCE_ROW_TITLE)
        title = (title_el.get_attribute("aria-label") if title_el else None) or row.inner_text().strip()
        if SOURCE_ROW_ERROR_CLASS in (row.get_attribute("class") or ""):
            status = "failed"
        elif row.query_selector(SOURCE_ROW_READY):
            status = "ready"
        else:
            status = "processing"
        rows.append((title, status))
    return rows


def _open_dialog(page):
    """Open the "Add sources" dialog (empty notebooks open it on their own)"""
    if page.query_selector(SOURCE_ACTION_BUTTON.format("Copied text")):
        return
    page.click(ADD_SOURCE_BUTTON)
    page.wait_for_selector(SOURCE_ACTION_BUTTON.format("Copied text"), timeout=15000)
    StealthUtils.random_delay(500, 1000)


def _insert(page, action, input_selector, value):
    """Fill the URL / pasted-text form and press Insert"""
    page.click(SOURCE_ACTION_BUTTON.format(action))
    page.wait_for_selector(input_selector, state="visible", timeout=15000)
    page.fill(input_selector, value)
    page.wait_for_selector(f"{INSERT_BUTTON}:not([disabled])", timeout=15000)
    page.click(INSERT_BUTTON)


def _upload_files(page, files):
    """Pick files through the native file chooser of "Upload files" """
    with page.expect_file_chooser(timeout=15000) as fc:
        page.click(SOURCE_ACTION_BUTTON.format("Upload files"))
    fc.value.set_files([str(f) for f in files])


def _wait_for_sources(page, before, expected, timeout):
    """
    Wait until `expected` new sources are listed and none is still processing.
    Returns [(title, status)] of the new sources (may be short on timeout).
    """
    deadline = time.time() + timeout
    new = []
    while time.time() < deadline:
        new = [r for r in _source_rows(page) if r[0] not in before]
        if len(new) >= expected and all(status != "processing" for _, status in new):
            return new
        time.sleep(2)
    return new


def add_sources(notebook_url, files=None, urls=None, text=None,
                headless=True, timeout=300):
    """
    Add sources to a notebook

    Args:
        notebook_url: Notebook URL
        files: Local file paths to upload
        urls: Website / YouTube URLs
        text: Text to add as a "Pasted text" source
        headless: Run browser in headless mode
        timeout: Seconds to wait for the sources to finish processing

    Returns:
        List of (title, status) for the new sources, or None on failure
    """
    files = [Path(f).expanduser().resolve() for f in (files or [])]
    urls = urls or []

    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        print(f"❌ File(s) not found: {', '.join(missing)}")
        return None

    auth = AuthManager()
    if not auth.is_authenticated():
        print("⚠️ Not authenticated. Run: python3 scripts/run.py auth_manager.py setup")
        return None

    print(f"📚 Notebook: {notebook_url}")

    playwright = None
    context = None

    try:
        playwright = sync_playwright().start()
        context = BrowserFactory.launch_persistent_context(playwright, headless=headless)

        page = context.new_page()
        print("  🌐 Opening notebook...")
        page.goto(notebook_url, wait_until="domcontentloaded")
        page.wait_for_selector(ADD_SOURCE_BUTTON, timeout=60000)
        time.sleep(3)  # Let the source list hydrate

        # Empty notebooks open the add-source dialog right away - only close promos
        if not page.query_selector(SOURCE_ACTION_BUTTON.format("Copied text")):
            StealthUtils.dismiss_dialogs(page)

        before = [title for title, _ in _source_rows(page)]
        print(f"  📄 {len(before)} source(s) before")

        expected = 0
        if files:
            print(f"  📤 Uploading {len(files)} file(s)...")
            _open_dialog(page)
            _upload_files(page, files)
            expected += len(files)
            time.sleep(3)
        if urls:
            print(f"  🔗 Adding {len(urls)} URL(s)...")
            _open_dialog(page)
            _insert(page, "Websites", URL_INPUT, "\n".join(urls))
            expected += len(urls)
            time.sleep(3)
        if text:
            print(f"  📝 Adding pasted text ({len(text)} chars)...")
            _open_dialog(page)
            _insert(page, "Copied text", TEXT_INPUT, text)
            expected += 1
            time.sleep(3)

        print("  ⏳ Waiting for sources to be processed...")
        new = _wait_for_sources(page, before, expected, timeout)

        ready = sum(status == "ready" for _, status in new)
        if len(new) < expected:
            print(f"  ⚠️ Only {len(new)} of {expected} new source(s) appeared within {timeout}s")
        elif ready < len(new):
            print(f"  ⚠️ {len(new) - ready} of {len(new)} new source(s) failed or are still processing")
        else:
            print(f"  ✅ Added {len(new)} source(s)")
        return new

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        if context:
            try:
                context.close()
            except:
                pass
        if playwright:
            try:
                playwright.stop()
            except:
                pass


def main():
    parser = argparse.ArgumentParser(description='Add sources to a Gemini Notebook notebook')

    parser.add_argument('--notebook-url', help='Notebook URL')
    parser.add_argument('--notebook-id', help='Notebook ID from library')
    parser.add_argument('--file', action='append', default=[], help='Local file to upload (repeatable)')
    parser.add_argument('--url', action='append', default=[], help='Website or YouTube URL (repeatable)')
    parser.add_argument('--text', help='Text to add as a pasted-text source')
    parser.add_argument('--text-file', help='Add the contents of this file as a pasted-text source')
    parser.add_argument('--show-browser', action='store_true', help='Show browser')
    parser.add_argument('--timeout', type=int, default=300, help='Seconds to wait for processing (default 300)')

    args = parser.parse_args()

    text = args.text
    if args.text_file:
        text = Path(args.text_file).expanduser().read_text()

    if not (args.file or args.url or text):
        parser.error("give at least one of --file, --url, --text, --text-file")

    # Resolve notebook URL
    notebook_url = args.notebook_url
    library = NotebookLibrary()

    if not notebook_url and args.notebook_id:
        notebook = library.get_notebook(args.notebook_id)
        if not notebook:
            print(f"❌ Notebook '{args.notebook_id}' not found")
            return 1
        notebook_url = notebook['url']

    if not notebook_url:
        active = library.get_active_notebook()
        if not active:
            print("❌ No notebook given. Use --notebook-url or --notebook-id")
            return 1
        notebook_url = active['url']
        print(f"📚 Using active notebook: {active['name']}")

    new = add_sources(
        notebook_url,
        files=args.file,
        urls=args.url,
        text=text,
        headless=not args.show_browser,
        timeout=args.timeout
    )

    if new is None:
        print("\n❌ Failed to add sources")
        return 1

    print("\nNew sources:")
    for title, status in new:
        mark = {"ready": "✓", "failed": "✗"}.get(status, "…")
        print(f"  {mark} {title} ({status})")
    return 0 if new and all(status == "ready" for _, status in new) else 1


if __name__ == "__main__":
    sys.exit(main())
