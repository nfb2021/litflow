# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-29

### Added
- `zot` command (Typer, uv tool) driving Zotero through the Zotero MCP plugin
  (cookjohn/zotero-mcp) on `localhost:23120`
- `zot add`: import DOIs / arXiv / ISBN / PMID with Zotero's resolvers and PDF download,
  into a collection (created if missing), duplicates skipped, PDF status per item
- `zot pdfs`: local PDF paths of a collection, `--missing` for items without one
- `zot refs`: cited DOIs from Crossref, with a fallback to the PDF text; most-cited first,
  `--min-cited` and `--counts`
- `zot push`: upload a collection's PDFs to a Gemini Notebook via `gnb add`
- `zot status`, `zot collections`, `zot search`
- Skill instructions (`SKILL.md`), README and a marimo guide (`docs/guide.py`)
