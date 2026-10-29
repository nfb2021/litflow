# Authentication Architecture

## Overview

This skill uses a **hybrid authentication approach** that combines the best of both worlds:

1. **Persistent Browser Profile** (`user_data_dir`) for consistent browser fingerprinting
2. **Manual Cookie Injection** from `state.json` for reliable session cookie persistence

## Why This Approach?

### The Problem

Playwright/Patchright has a known bug ([#36139](https://github.com/microsoft/playwright/issues/36139)) where **session cookies** (cookies without an `Expires` attribute) do not persist correctly when using `launch_persistent_context()` with `user_data_dir`.

**What happens:**
- ✅ Persistent cookies (with `Expires` date) → Saved correctly to browser profile
- ❌ Session cookies (without `Expires`) → **Lost after browser restarts**

**Impact:**
- Some Google auth cookies are session cookies
- Users experience random authentication failures
- "Works on my machine" syndrome (depends on which cookies Google uses)

### TypeScript vs Python

The **MCP Server** (TypeScript) can work around this by passing `storage_state` as a parameter:

```typescript
// TypeScript - works!
const context = await chromium.launchPersistentContext(userDataDir, {
  storageState: "state.json",  // ← Loads cookies including session cookies
  channel: "chrome"
});
```

But **Python's Playwright API doesn't support this** ([#14949](https://github.com/microsoft/playwright/issues/14949)):

```python
# Python - NOT SUPPORTED!
context = playwright.chromium.launch_persistent_context(
    user_data_dir=profile_dir,
    storage_state="state.json",  # ← Parameter not available in Python!
    channel="chrome",
)
```

## Our Solution: Hybrid Approach

We use a **two-phase authentication system**:

### Phase 1: Setup (`auth_manager.py setup`)

1. Launch persistent context with `user_data_dir`
2. User logs in manually
3. **Save state to TWO places:**
   - Browser profile directory (automatic, for fingerprint + persistent cookies)
   - `state.json` file (explicit save, for session cookies)

```python
context = playwright.chromium.launch_persistent_context(
    user_data_dir="browser_profile/", channel="chrome"
)
# User logs in...
context.storage_state(path="state.json")  # Save all cookies
```

### Phase 2: Runtime (`ask_question.py`)

1. Launch persistent context with `user_data_dir` (loads fingerprint + persistent cookies)
2. **Manually inject cookies** from `state.json` (adds session cookies)

```python
# Step 1: Launch with browser profile
context = playwright.chromium.launch_persistent_context(
    user_data_dir="browser_profile/", channel="chrome"
)

# Step 2: Manually inject cookies from state.json
with open("state.json", "r") as f:
    state = json.load(f)
    context.add_cookies(state["cookies"])  # ← Workaround for session cookies!
```

## Benefits

| Feature | Our Approach | Pure `user_data_dir` | Pure `storage_state` |
|---------|--------------|----------------------|----------------------|
| **Browser Fingerprint Consistency** | ✅ Same across restarts | ✅ Same | ❌ Changes each time |
| **Session Cookie Persistence** | ✅ Manual injection | ❌ Lost (bug) | ✅ Native support |
| **Persistent Cookie Persistence** | ✅ Automatic | ✅ Automatic | ✅ Native support |
| **Google Trust** | ✅ High (same browser) | ✅ High | ❌ Low (new browser) |
| **Cross-platform Reliability** | ✅ Chrome required | ⚠️ Chromium issues | ✅ Portable |
| **Cache Performance** | ✅ Keeps cache | ✅ Keeps cache | ❌ No cache |

## File Structure

```
~/Library/Application Support/gemini-notebook/   # macOS; $GEMINI_NOTEBOOK_HOME overrides
├── auth_info.json              # Metadata about authentication
├── browser_state/
│   ├── state.json             # Cookies + localStorage (for manual injection)
│   └── browser_profile/       # Chrome user profile (for fingerprint + cache)
│       ├── Default/
│       │   ├── Cookies        # Persistent cookies only (session cookies missing!)
│       │   ├── Local Storage/
│       │   └── Cache/
│       └── ...
```

## Why `state.json` is Critical

Even though we use `user_data_dir`, we **still need `state.json`** because:

1. **Session cookies** are not saved to the browser profile (Playwright bug)
2. **Manual injection** is the only reliable way to load session cookies
3. **Validation** - we can check if cookies are expired before launching

## Code References

- **Launch + cookie injection:** `BrowserFactory.launch_persistent_context()` and
  `_inject_cookies()` in `src/gemini_notebook/browser.py` (`channel="chrome"`, then
  cookies from `state.json`). Every command that opens a browser goes through it.
- **Setup:** `AuthManager.setup_auth()` in `src/gemini_notebook/auth.py`; saves
  `state.json` via `context.storage_state()` once a Google session cookie exists.
- **Validation:** `AuthManager.validate_auth()` in the same file (`gnb auth validate`).

## Related Issues

- [microsoft/playwright#36139](https://github.com/microsoft/playwright/issues/36139) - Session cookies not persisting
- [microsoft/playwright#14949](https://github.com/microsoft/playwright/issues/14949) - Storage state with persistent context
- [StackOverflow Question](https://stackoverflow.com/questions/79641481/) - Session cookie persistence issue

## Future Improvements

If Playwright adds support for `storage_state` parameter in Python's `launch_persistent_context()`, we can simplify to:

```python
# Future (when Python API supports it):
context = playwright.chromium.launch_persistent_context(
    user_data_dir="browser_profile/",
    storage_state="state.json",  # ← Would handle everything automatically!
    channel="chrome",
)
```

Until then, our hybrid approach is the most reliable solution.
