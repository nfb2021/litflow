# obsidian: the research vault (`obs`)

A literature project's memory as plain Obsidian markdown, kept valid by the `obs`
CLI. Papers come from Zotero's Better BibTeX export; what papers say is stored
as **claims** (one paper, one statement, a verbatim quote that `obs` finds in the
PDF); `obs trace` follows statements through the papers that repeat and cite
them; `obs lint` is the gate that agents and workflows must pass.

Obsidian does not need to be running. Open the folder in Obsidian for the
graph view and backlinks.

## Install

```bash
uv tool install "git+https://github.com/nfb2021/skills.git#subdirectory=obsidian"
obs --version
```

Optional, for checking quotes in PDFs:

- `pdftotext` (poppler) reads columns better than the built-in pypdf fallback:
  `brew install poppler` / `apt install poppler-utils`.
- `ocrmypdf` adds a text layer to scans of older papers (`obs ocr KEY -l deu+eng`):
  `brew install ocrmypdf tesseract-lang` / `apt install ocrmypdf tesseract-ocr-deu`.
  Tested on Einstein's 1905 photoelectric paper (Annalen der Physik 17): 17 pages
  in 16 s, prose quotes check cleanly, formulas do not survive OCR.

For Claude Code, link the skill: `ln -s ~/src/skills/obsidian ~/.claude/skills/obsidian`.
For Pi, add `~/src/skills` to `skills` in `~/.pi/agent/settings.json`.

## The vault

```
my-review/
├── obs.toml          marker + title
├── protocol.md       research question, scope, criteria, evidence rules
├── papers/           <citekey>.md   from the .bib, plus screening
├── statements/       S-0001.md      one proposition, worded once
├── claims/           C-0001.md      paper + statement + quote + page + role + cites
├── questions/        Q-0001.md      tickets on a map
├── maps/             M-0001.md      destination, decisions so far, fog, out of scope
├── concepts/         <slug>.md      glossary terms with aliases
└── decisions/        D-0001.md      method decisions
```

Links are `[[id]]` strings in the frontmatter, so Obsidian's graph shows how
claims, statements and papers connect.

## Walkthrough

```bash
obs init ~/research/vod-review --title "VOD diurnal cycle"
cd ~/research/vod-review
obs paper sync ~/Zotero/vod-review.bib          # Better BibTeX auto-export
obs paper screen doe2026gnsst --include --reason "I1: peer-reviewed GNSS-T study" --by screener

obs statement add "VOD increases with canopy water content"          # -> S-0001
obs pdf-text doe2026gnsst --grep "canopy water"                     # find the sentence
obs claim add -p doe2026gnsst -s S-0001 -r origin --by reader \
  -q "Vegetation optical depth increases with canopy water content"   # quote checked in the PDF
obs verify C-0001 --verified --by verifier --note "p. 4, Fig. 6, growing season 2023"
obs trace S-0001                                 # independent sources, citation hops, drift
obs lint                                         # exit 1 on rule violations
```

Large questions become maps of tickets, worked one per session:

```bash
obs map new "Diurnal VOD" -d "A synthesis section on what drives diurnal VOD"
obs q add M-0001 "Which drivers are in scope?" -k grilling            # the user answers
obs q add M-0001 "Which studies measure diurnal VOD in situ?" -k research -b Q-0001
obs frontier
```

## Why it is built like this

The vault is designed to be driven by smaller models. The rules sit in the
tool, not only in the prompt:

- a quote that is not in the PDF is refused;
- a claim cannot be verified by the agent that extracted it;
- a grilling question cannot be answered without the user's words;
- research answers must link the claims they rest on;
- support is counted in independent origin papers, not repetitions.

Ideas adapted from Matt Pocock's [skills](https://github.com/mattpocock/skills)
(MIT): wayfinder maps and frontier, grilling, domain glossary and decision records.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
