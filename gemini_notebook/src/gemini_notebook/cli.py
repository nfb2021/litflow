"""
`gnb` - command-line interface for Gemini Notebook (formerly NotebookLM)

    gnb ask "question" [-n NOTEBOOK]
    gnb add [-n NOTEBOOK] --file F --url U --text T
    gnb library list|add|search|activate|remove|stats
    gnb auth setup|status|validate|clear|reauth
    gnb cleanup [--confirm]
"""

import contextlib
import json
import sys
from pathlib import Path

import typer

from . import __version__
from .config import DATA_DIR

app = typer.Typer(
    help="Ask Gemini Notebook (formerly NotebookLM) notebooks and add sources to them.",
    no_args_is_help=True,
    add_completion=False,
)
library_app = typer.Typer(help="Manage the notebook library.", no_args_is_help=True)
auth_app = typer.Typer(help="Google login.", no_args_is_help=True)
app.add_typer(library_app, name="library")
app.add_typer(auth_app, name="auth")

NOTEBOOK_HELP = (
    "Notebook ID from the library or a notebook URL (default: active notebook)"
)
SHOW_BROWSER_HELP = "Show the browser instead of running it in the background"


def _split(value: str | None) -> list[str] | None:
    """Comma-separated option -> list"""
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _resolve_notebook(notebook: str | None) -> str:
    """Notebook ID or URL (or the active notebook) -> URL; exits on failure"""
    from .library import NotebookLibrary

    if notebook and notebook.startswith("http"):
        return notebook

    library = NotebookLibrary()
    if notebook:
        nb = library.get_notebook(notebook)
        if not nb:
            typer.echo(f"❌ Notebook '{notebook}' not found. See: gnb library list")
            raise typer.Exit(1)
        return nb["url"]

    active = library.get_active_notebook()
    if active:
        typer.echo(f"📚 Using active notebook: {active['name']}")
        return active["url"]

    notebooks = library.list_notebooks()
    if notebooks:
        typer.echo("\n📚 Available notebooks:")
        for nb in notebooks:
            typer.echo(f"  {nb['id']}: {nb['name']}")
        typer.echo("\nChoose one with -n ID, or set a default: gnb library activate ID")
    else:
        typer.echo("❌ No notebooks in library. Add one first:")
        typer.echo("gnb library add URL --name NAME --description DESC --topics TOPICS")
    raise typer.Exit(1)


def _version(value: bool):
    if value:
        typer.echo(f"gnb {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version"
    ),
):
    pass


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question to ask"),
    notebook: str | None = typer.Option(None, "--notebook", "-n", help=NOTEBOOK_HELP),
    show_browser: bool = typer.Option(False, "--show-browser", help=SHOW_BROWSER_HELP),
    timeout: int = typer.Option(240, help="Seconds to wait for the answer"),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print only {question, notebook, answer} as JSON (progress goes to stderr)",
    ),
):
    """Ask a notebook a question; the answer comes only from its sources."""
    from .ask import ask_notebook

    notebook_url = _resolve_notebook(notebook)
    if as_json:
        with contextlib.redirect_stdout(sys.stderr):
            answer = ask_notebook(
                question,
                notebook_url,
                headless=not show_browser,
                timeout=timeout,
                reminder=False,
            )
        if not answer:
            typer.echo("❌ Failed to get answer", err=True)
            raise typer.Exit(1)
        out = {"question": question, "notebook": notebook_url, "answer": answer}
        typer.echo(json.dumps(out, ensure_ascii=False, indent=2))
        return
    answer = ask_notebook(
        question, notebook_url, headless=not show_browser, timeout=timeout
    )
    if not answer:
        typer.echo("\n❌ Failed to get answer")
        raise typer.Exit(1)

    typer.echo("\n" + "=" * 60)
    typer.echo(f"Question: {question}")
    typer.echo("=" * 60)
    typer.echo()
    typer.echo(answer)
    typer.echo()
    typer.echo("=" * 60)


@app.command()
def add(
    notebook: str | None = typer.Option(None, "--notebook", "-n", help=NOTEBOOK_HELP),
    file: list[Path] = typer.Option(
        [], "--file", "-f", help="Local file to upload (repeatable)"
    ),
    url: list[str] = typer.Option(
        [], "--url", "-u", help="Website or YouTube URL (repeatable)"
    ),
    text: str | None = typer.Option(None, help="Text to add as a pasted-text source"),
    text_file: Path | None = typer.Option(
        None, help="Add the contents of this file as a pasted-text source"
    ),
    show_browser: bool = typer.Option(False, "--show-browser", help=SHOW_BROWSER_HELP),
    timeout: int = typer.Option(
        300, help="Seconds to wait for the sources to be processed"
    ),
):
    """Add sources to a notebook: files, websites / YouTube, pasted text."""
    from .sources import add_sources

    if text_file:
        text = text_file.expanduser().read_text()
    if not (file or url or text):
        raise typer.BadParameter(
            "give at least one of --file, --url, --text, --text-file"
        )

    notebook_url = _resolve_notebook(notebook)
    new = add_sources(
        notebook_url,
        files=file,
        urls=url,
        text=text,
        headless=not show_browser,
        timeout=timeout,
    )
    if new is None:
        typer.echo("\n❌ Failed to add sources")
        raise typer.Exit(1)

    typer.echo("\nNew sources:")
    for title, status in new:
        mark = {"ready": "✓", "failed": "✗"}.get(status, "…")
        typer.echo(f"  {mark} {title} ({status})")
    if not (new and all(status == "ready" for _, status in new)):
        raise typer.Exit(1)


# --- library -----------------------------------------------------------------


@library_app.command("list")
def library_list():
    """List all notebooks."""
    from .library import NotebookLibrary

    library = NotebookLibrary()
    notebooks = library.list_notebooks()
    if not notebooks:
        typer.echo("📚 Library is empty. Add notebooks with: gnb library add")
        return
    typer.echo("\n📚 Notebook Library:")
    for nb in notebooks:
        active = " [ACTIVE]" if nb["id"] == library.active_notebook_id else ""
        typer.echo(f"\n  📓 {nb['name']}{active}")
        typer.echo(f"     ID: {nb['id']}")
        typer.echo(f"     Topics: {', '.join(nb['topics'])}")
        typer.echo(f"     Uses: {nb['use_count']}")


@library_app.command("add")
def library_add(
    url: str = typer.Argument(..., help="Notebook URL"),
    name: str = typer.Option(..., help="Display name (the ID is derived from it)"),
    description: str = typer.Option(..., help="What the notebook contains"),
    topics: str = typer.Option(..., help="Comma-separated topics"),
    use_cases: str | None = typer.Option(None, help="Comma-separated use cases"),
    tags: str | None = typer.Option(None, help="Comma-separated tags"),
):
    """Add a notebook to the library."""
    from .library import NotebookLibrary

    try:
        notebook = NotebookLibrary().add_notebook(
            url=url,
            name=name,
            description=description,
            topics=_split(topics),
            use_cases=_split(use_cases),
            tags=_split(tags),
        )
    except ValueError as e:
        typer.echo(f"❌ {e}")
        raise typer.Exit(1) from None
    typer.echo(json.dumps(notebook, indent=2))


@library_app.command("search")
def library_search(
    query: str = typer.Argument(..., help="Searches name, description, topics, tags"),
):
    """Search notebooks."""
    from .library import NotebookLibrary

    results = NotebookLibrary().search_notebooks(query)
    if not results:
        typer.echo(f"🔍 No notebooks found for: {query}")
        return
    typer.echo(f"\n🔍 Found {len(results)} notebooks:")
    for nb in results:
        typer.echo(f"\n  📓 {nb['name']} ({nb['id']})")
        typer.echo(f"     {nb['description']}")


@library_app.command("activate")
def library_activate(notebook_id: str = typer.Argument(..., help="Notebook ID")):
    """Set the default notebook."""
    from .library import NotebookLibrary

    try:
        NotebookLibrary().select_notebook(notebook_id)
    except ValueError as e:
        typer.echo(f"❌ {e}")
        raise typer.Exit(1) from None


@library_app.command("remove")
def library_remove(notebook_id: str = typer.Argument(..., help="Notebook ID")):
    """Remove a notebook from the library (the notebook itself is kept)."""
    from .library import NotebookLibrary

    if not NotebookLibrary().remove_notebook(notebook_id):
        raise typer.Exit(1)


@library_app.command("stats")
def library_stats():
    """Show library statistics."""
    from .library import NotebookLibrary

    stats = NotebookLibrary().get_stats()
    typer.echo("\n📊 Library Statistics:")
    typer.echo(f"  Total notebooks: {stats['total_notebooks']}")
    typer.echo(f"  Total topics: {stats['total_topics']}")
    typer.echo(f"  Total uses: {stats['total_use_count']}")
    if stats["active_notebook"]:
        typer.echo(f"  Active: {stats['active_notebook']['name']}")
    if stats["most_used_notebook"]:
        most = stats["most_used_notebook"]
        typer.echo(f"  Most used: {most['name']} ({most['use_count']} uses)")
    typer.echo(f"  Library path: {stats['library_path']}")


# --- auth --------------------------------------------------------------------


@auth_app.command("setup")
def auth_setup(
    timeout: float = typer.Option(10, help="Login timeout in minutes"),
    headless: bool = typer.Option(
        False, "--headless", help="Run without a visible browser"
    ),
):
    """Log in to Google in a visible Chrome window."""
    from .auth import AuthManager

    if not AuthManager().setup_auth(headless=headless, timeout_minutes=timeout):
        typer.echo("\n❌ Authentication setup failed")
        raise typer.Exit(1)
    typer.echo('\n✅ Authentication setup complete! Try: gnb ask "..."')


@auth_app.command("status")
def auth_status():
    """Show whether a login is saved and how old it is."""
    from .auth import AuthManager

    info = AuthManager().get_auth_info()
    typer.echo("\n🔐 Authentication Status:")
    typer.echo(f"  Authenticated: {'Yes' if info['authenticated'] else 'No'}")
    if info.get("state_age_hours"):
        typer.echo(f"  State age: {info['state_age_hours']:.1f} hours")
    if info.get("authenticated_at_iso"):
        typer.echo(f"  Last auth: {info['authenticated_at_iso']}")
    typer.echo(f"  Data folder: {DATA_DIR}")
    if not info["authenticated"]:
        raise typer.Exit(1)


@auth_app.command("validate")
def auth_validate():
    """Open Gemini Notebook and check that the saved login works."""
    from .auth import AuthManager

    if not AuthManager().validate_auth():
        typer.echo("Authentication is invalid or expired. Run: gnb auth reauth")
        raise typer.Exit(1)
    typer.echo("Authentication is valid and working")


@auth_app.command("clear")
def auth_clear():
    """Delete the saved login."""
    from .auth import AuthManager

    if not AuthManager().clear_auth():
        raise typer.Exit(1)
    typer.echo("Authentication cleared")


@auth_app.command("reauth")
def auth_reauth(timeout: float = typer.Option(10, help="Login timeout in minutes")):
    """Clear the login and log in again (also to switch accounts)."""
    from .auth import AuthManager

    if not AuthManager().re_auth(timeout_minutes=timeout):
        typer.echo("\n❌ Re-authentication failed")
        raise typer.Exit(1)
    typer.echo("\n✅ Re-authentication complete!")


# --- cleanup -----------------------------------------------------------------


@app.command()
def cleanup(
    confirm: bool = typer.Option(
        False, "--confirm", help="Actually delete (otherwise only a preview)"
    ),
    preserve_library: bool = typer.Option(
        False, "--preserve-library", help="Keep the notebook library"
    ),
    force: bool = typer.Option(False, "--force", help="Skip the confirmation prompt"),
):
    """Delete browser state and login (and the library unless --preserve-library)."""
    from .cleanup import CleanupManager

    manager = CleanupManager()
    if not confirm:
        manager.print_cleanup_preview(preserve_library)
        return

    if not force:
        manager.print_cleanup_preview(preserve_library)
        typer.confirm("\n⚠️  Delete the files shown above?", abort=True)

    typer.echo("\n🗑️ Performing cleanup...")
    result = manager.perform_cleanup(preserve_library, dry_run=False)
    typer.echo("\n✅ Cleanup complete!")
    typer.echo(f"  Deleted: {result['deleted_count']} items")
    typer.echo(f"  Freed: {manager._format_size(result['deleted_size'])}")
    if result["failed_count"]:
        typer.echo(f"  ⚠️ Failed: {result['failed_count']} items")
        raise typer.Exit(1)
