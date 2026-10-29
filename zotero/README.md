# zotero

A Claude Code skill and command-line tool, `zot`, for your Zotero library:

- **Import papers by DOI** (or arXiv ID, ISBN, PMID) with Zotero's own resolvers, PDFs included
- **List the local PDF paths** of a collection, or the items that are missing a PDF
- **Extract the DOIs a paper cites**, from Crossref or from the PDF's text
- **Upload a collection's PDFs to a Gemini Notebook**, through the [`gemini_notebook`](../gemini_notebook/) skill's `gnb`

Together these make a literature loop:

```text
DOIs ──zot add──▶ Zotero (+PDFs) ──zot push──▶ Gemini Notebook ──gnb ask──▶ answers
  ▲                    │
  └─────zot refs───────┘   (the references the papers cite, most-cited first)
```

`zot` does not scrape anything itself. It drives your running Zotero desktop app through
the [Zotero MCP plugin](https://github.com/cookjohn/zotero-mcp) by cookjohn (MIT). So the
items and PDFs are the same as when you use Zotero's magic wand, and that includes your
proxy or VPN access.

## Setup

1. **Zotero 7 or newer**, running.
2. **The plugin.** Download `zotero-mcp-plugin-*.xpi` from the
   [plugin releases](https://github.com/cookjohn/zotero-mcp/releases). Install it with
   Zotero → Tools → Add-ons → ⚙ → *Install Add-on From File…*, then restart Zotero.
3. **Plugin settings** (Zotero → Settings → Zotero MCP Plugin):
   - Leave the server enabled, on port 23120.
   - Tick **Enable Write Operations**, which `zot add` needs. Reading works without it.
4. **The command:**

   ```bash
   uv tool install --editable ~/src/skills/zotero   # from your clone of this repo
   zot status                                       # ✅ … Write operations enabled
   ```

5. **The skill for Claude Code:** `ln -s ~/src/skills/zotero ~/.claude/skills/zotero`

For PDFs of paywalled papers, be on your institution's network or VPN, or set up its
proxy in Zotero → Settings → General → *Proxies*. Otherwise Zotero finds only
open-access copies.

## Usage

```bash
zot add 10.1029/2023GL107121 arXiv:2304.00464 -c "GNSS-T"   # import with PDFs
zot add -f dois.txt -c "GNSS-T"          # one identifier per line ('-' reads stdin)
zot pdfs -c "GNSS-T"                     # PDF paths
zot pdfs -c "GNSS-T" --missing           # items without a PDF
zot refs -c "GNSS-T" -m 3 --counts       # DOIs cited by ≥ 3 of the papers
zot refs -c "GNSS-T" -m 3 | zot add -f - -c "GNSS-T/round 2"
zot push -c "GNSS-T" -n my-notebook      # PDFs → Gemini Notebook (needs gnb)
zot search "vegetation optical depth"
zot collections
```

`zot --help` and `zot COMMAND --help` list every option. Lists are printed to stdout and
progress to stderr, so the output pipes cleanly.

How it behaves:
- `zot add` never imports a duplicate. An identifier already in the library is reported
  as `exists`, and with `-c` it is put into the collection.
- A collection given to `-c` is created if it doesn't exist.
- `zot` has no command that deletes anything.

## Interactive guide

A [marimo](https://marimo.io) notebook that checks your setup and lets you browse a
collection's PDFs and references:

```bash
cd ~/src/skills/zotero
uvx --with-editable . marimo edit docs/guide.py   # or: marimo run (app view, code hidden)
```

`uvx` builds a throwaway environment with marimo and this package, so nothing is installed
into your project or system Python.

## Configuration

| Variable | Default | |
|---|---|---|
| `ZOTERO_MCP_URL` | `http://127.0.0.1:23120/mcp` | Plugin endpoint |

`zot refs` sends the papers' DOIs to the public [Crossref API](https://api.crossref.org).
Nothing else leaves your machine.
