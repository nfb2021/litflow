"""
Authentication Manager for NotebookLM
Handles Google login and browser state persistence
Based on the MCP server implementation

Implements hybrid auth approach:
- Persistent browser profile (user_data_dir) for fingerprint consistency
- Manual cookie injection from state.json for session cookies (Playwright bug workaround)
See: https://github.com/microsoft/playwright/issues/36139
"""

import json
import re
import shutil
import time
from typing import Any

from patchright.sync_api import BrowserContext, sync_playwright

from .browser import BrowserFactory
from .config import AUTH_INFO_FILE, BROWSER_STATE_DIR, DATA_DIR, STATE_FILE


class AuthManager:
    """
    Manages authentication and browser state for NotebookLM

    Features:
    - Interactive Google login
    - Browser state persistence
    - Session restoration
    - Account switching
    """

    def __init__(self):
        """Initialize the authentication manager"""
        # Ensure directories exist
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)

        self.state_file = STATE_FILE
        self.auth_info_file = AUTH_INFO_FILE
        self.browser_state_dir = BROWSER_STATE_DIR

    def is_authenticated(self) -> bool:
        """Check if valid authentication exists"""
        if not self.state_file.exists():
            return False

        # Check if state file is not too old (7 days)
        age_days = (time.time() - self.state_file.stat().st_mtime) / 86400
        if age_days > 7:
            print(
                f"⚠️ Browser state is {age_days:.1f} days old, may need re-authentication"
            )

        return True

    def get_auth_info(self) -> dict[str, Any]:
        """Get authentication information"""
        info = {
            "authenticated": self.is_authenticated(),
            "state_file": str(self.state_file),
            "state_exists": self.state_file.exists(),
        }

        if self.auth_info_file.exists():
            try:
                with open(self.auth_info_file) as f:
                    saved_info = json.load(f)
                    info.update(saved_info)
            except Exception:
                pass

        if info["state_exists"]:
            age_hours = (time.time() - self.state_file.stat().st_mtime) / 3600
            info["state_age_hours"] = age_hours

        return info

    def setup_auth(self, headless: bool = False, timeout_minutes: int = 10) -> bool:
        """
        Perform interactive authentication setup

        Args:
            headless: Run browser in headless mode (False for login)
            timeout_minutes: Maximum time to wait for login

        Returns:
            True if authentication successful
        """
        print("🔐 Starting authentication setup...")
        print(f"  Timeout: {timeout_minutes} minutes")

        playwright = None
        context = None

        try:
            playwright = sync_playwright().start()

            # Launch using factory
            context = BrowserFactory.launch_persistent_context(
                playwright, headless=headless
            )

            # Navigate to NotebookLM (Google rebranded notebooklm.google.com -> notebook.google.com)
            page = context.new_page()
            page.goto("https://notebook.google.com", wait_until="domcontentloaded")

            # Let client-side redirects (e.g. to accounts.google.com) happen before judging the URL;
            # checking right after domcontentloaded gave false "Already authenticated" results.
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(3)

            def _has_session_cookie():
                return any(
                    c["name"] in ("SID", "__Secure-1PSID")
                    for c in context.cookies("https://www.google.com")
                )

            # Check if already authenticated
            if (
                "notebook.google.com" in page.url
                and "accounts.google.com" not in page.url
                and _has_session_cookie()
            ):
                print("  ✅ Already authenticated!")
                self._save_browser_state(context)
                return True

            # Wait for manual login
            print("\n  ⏳ Please log in to your Google account...")
            print(f"  ⏱️  Waiting up to {timeout_minutes} minutes for login...")

            try:
                # Wait for URL to change to NotebookLM (regex ensures it's the actual domain, not a parameter)
                timeout_ms = int(timeout_minutes * 60 * 1000)
                page.wait_for_url(
                    re.compile(r"^https://notebook\.google\.com/"), timeout=timeout_ms
                )
                # The logged-out landing page is also on notebook.google.com: require a Google session cookie
                deadline = time.time() + timeout_minutes * 60
                while not _has_session_cookie():
                    if time.time() > deadline:
                        raise TimeoutError("no Google session cookie after login wait")
                    time.sleep(2)

                print("  ✅ Login successful!")

                # Save authentication state
                self._save_browser_state(context)
                self._save_auth_info()
                return True

            except Exception as e:
                print(f"  ❌ Authentication timeout: {e}")
                return False

        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False

        finally:
            # Clean up browser resources
            if context:
                try:
                    context.close()
                except Exception:
                    pass

            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass

    def _save_browser_state(self, context: BrowserContext):
        """Save browser state to disk"""
        try:
            # Save storage state (cookies, localStorage)
            context.storage_state(path=str(self.state_file))
            print(f"  💾 Saved browser state to: {self.state_file}")
        except Exception as e:
            print(f"  ❌ Failed to save browser state: {e}")
            raise

    def _save_auth_info(self):
        """Save authentication metadata"""
        try:
            info = {
                "authenticated_at": time.time(),
                "authenticated_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(self.auth_info_file, "w") as f:
                json.dump(info, f, indent=2)
        except Exception:
            pass  # Non-critical

    def clear_auth(self) -> bool:
        """
        Clear all authentication data

        Returns:
            True if cleared successfully
        """
        print("🗑️ Clearing authentication data...")

        try:
            # Remove browser state
            if self.state_file.exists():
                self.state_file.unlink()
                print("  ✅ Removed browser state")

            # Remove auth info
            if self.auth_info_file.exists():
                self.auth_info_file.unlink()
                print("  ✅ Removed auth info")

            # Clear entire browser state directory
            if self.browser_state_dir.exists():
                shutil.rmtree(self.browser_state_dir)
                self.browser_state_dir.mkdir(parents=True, exist_ok=True)
                print("  ✅ Cleared browser data")

            return True

        except Exception as e:
            print(f"  ❌ Error clearing auth: {e}")
            return False

    def re_auth(self, headless: bool = False, timeout_minutes: int = 10) -> bool:
        """
        Perform re-authentication (clear and setup)

        Args:
            headless: Run browser in headless mode
            timeout_minutes: Login timeout in minutes

        Returns:
            True if successful
        """
        print("🔄 Starting re-authentication...")

        # Clear existing auth
        self.clear_auth()

        # Setup new auth
        return self.setup_auth(headless, timeout_minutes)

    def validate_auth(self) -> bool:
        """
        Validate that stored authentication works
        Uses persistent context to match actual usage pattern

        Returns:
            True if authentication is valid
        """
        if not self.is_authenticated():
            return False

        print("🔍 Validating authentication...")

        playwright = None
        context = None

        try:
            playwright = sync_playwright().start()

            # Launch using factory
            context = BrowserFactory.launch_persistent_context(
                playwright, headless=True
            )

            # Try to access NotebookLM
            page = context.new_page()
            page.goto(
                "https://notebook.google.com",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Check if we can access NotebookLM
            if (
                "notebook.google.com" in page.url
                and "accounts.google.com" not in page.url
            ):
                print("  ✅ Authentication is valid")
                return True
            else:
                print("  ❌ Authentication is invalid (redirected to login)")
                return False

        except Exception as e:
            print(f"  ❌ Validation failed: {e}")
            return False

        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass
