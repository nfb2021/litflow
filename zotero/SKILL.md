---
name: zotero
description: Use this skill to work with the user's Zotero library from Claude Code - import papers by DOI (also arXiv, ISBN, PMID) with Zotero's own resolvers and PDF download, list collections and the local PDF paths of their items, find items without a PDF, extract the DOIs a paper cites (Crossref or PDF text), and upload a collection's PDFs to a Gemini Notebook. Literature pipelines - DOIs -> Zotero -> Gemini Notebook -> new references.
---

# Zotero Skill

Talk to the user's running Zotero through the **Zotero MCP plugin**
([cookjohn/zotero-mcp](https://github.com/cookjohn/zotero-mcp)), with the `zot` command.
Zotero does the real work: its own DOI resolvers (the "Add Item by Identifier" magic wand)
and its own PDF finder, so items and PDFs are exactly what the desktop app would produce.

## When to Use This Skill

Trigger when the user:
- Gives DOIs / a list of papers and wants them in Zotero, with PDFs
- Asks what is in a Zotero collection, or for the PDFs of a collection
- Wants the references of a paper or a collection ("what do these papers cite?")
- Wants to feed Zotero PDFs into a Gemini Notebook (NotebookLM) - see the `gemini_notebook` skill
- Wants a snowball literature search: papers -> their references -> import -> repeat

## Step 0: Make Sure `zot` Works

```bash
command -v zot || uv tool install --editable <this skill's directory>
zot status
```

`zot` is a uv tool: it runs from any directory. Never use pip or the system Python.
`zot status` must report the plugin. If it fails:
- "No Zotero MCP server": Zotero is not running, or the plugin is not installed. Ask the
  user to start Zotero; the plugin install is in [README.md](README.md#setup).
- "Write operations disabled" (exit code 2): reading works, `zot add` does not. Ask the
  user to tick *Enable Write Operations* in Zotero → Settings → Zotero MCP Plugin.

## Commands

Lists go to **stdout**, one entry per line; progress and summaries go to **stderr**. So
`zot` output can be piped into another `zot` or into `gnb`.

```bash
zot collections [-q TEXT]               # KEY  path
zot search "query" [-l 20] [--fulltext] # KEY  YEAR  PDF  title
zot add DOI... [-c COLLECTION]          # import + fetch PDFs
zot add -f dois.txt -c COLLECTION       # one identifier per line, '#' comments; '-' = stdin
zot add --dry-run DOI...                # only check that the identifiers parse
zot pdfs -c COLLECTION                  # local PDF paths, one per line
zot pdfs -c COLLECTION --missing        # DOI  title of items WITHOUT a PDF
zot refs DOI|KEY... | -c COLLECTION     # DOIs the papers cite, most-cited first
zot refs -c COLLECTION -m 3 --counts    # cited by >= 3 papers, with counts
zot push -c COLLECTION -n NOTEBOOK      # upload the PDFs to a Gemini Notebook (gnb add)
```

Collections are given by name, path (`Parent/Child`) or 8-character key.

- `zot add`:
  - Uses `-c` to file items into a collection. The collection is created when it is missing.
  - Does not import an identifier that is already in the library; with `-c` the existing item is put into the collection instead.
  - Prints one line per identifier: `imported`, `exists`, `duplicate_trashed` or `error`, and whether a PDF arrived.
  - Up to 200 identifiers per call. Larger lists run as a background job, and `zot` waits for it.
- `zot refs` asks Crossref for the reference list first, which most publishers deposit. When Crossref has none, it falls back to DOIs printed in the PDF's text, which Zotero indexes; that works only for items in the library. Use `--source crossref|pdf` to force one. Papers given as input are left out of the output.
- `zot push` calls `gnb add -n NOTEBOOK -f …` in batches of 10. It warns above 50 PDFs, the Gemini Notebook source limit on the free plan.

## The Literature Pipeline

```bash
# 1. Seed papers -> Zotero, with PDFs
zot add -f seed_dois.txt -c "Project/seed"
zot pdfs -c "Project/seed" --missing        # tell the user which PDFs to get by hand

# 2. PDFs -> Gemini Notebook, then ask it (gemini_notebook skill)
zot push -c "Project/seed" -n NOTEBOOK
gnb ask "Which methods do these papers use for X? Cite sources." -n NOTEBOOK

# 3. New references for the next round
zot refs -c "Project/seed" -m 2 > round2.txt
zot add -f round2.txt -c "Project/round2"
```

Gemini Notebook answers name papers but not DOIs. To turn the papers it names into
identifiers, look them up with `zot search` (if in the library) or ask Crossref, then `zot add`.

## Rules

- **Confirm before big imports.** `zot add` writes to the user's library. More than about
  20 new identifiers → show the count (and `--dry-run` result) first and ask.
- **Never delete** items or collections. `zot` has no delete command, and the plugin's
  trash/delete tools must not be called directly.
- Missing PDFs are normal for paywalled papers. Zotero only finds open-access copies,
  unless the user is on the university network/VPN or has a proxy set up in Zotero. Report
  the `--missing` list, don't retry in a loop.
- Be polite to Crossref: `zot refs` on a few hundred papers is fine, don't run it in tight loops.

## Environment

- `$ZOTERO_MCP_URL` - plugin endpoint (default `http://127.0.0.1:23120/mcp`)
