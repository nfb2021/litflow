---
name: obsidian
description: Use this skill to read and write the research vault (Obsidian markdown) with the `obs` CLI - papers from the Better BibTeX export, statements, claims with verbatim quotes checked against the PDF, citation provenance (`obs trace`), question maps and their frontier, glossary, decisions, and the `obs lint` gate. Use it whenever literature findings are recorded, looked up, verified or queried.
---

# obs: the research vault

The vault is the memory of a literature project. Everything you learn from a
paper goes in as a **claim**; everything you write later comes out of claims.
Work through `obs` only: it keeps ids, links and frontmatter valid. Reading
the markdown files directly is fine; editing them by hand is how vaults break.

Step 0, every session: `obs status`. It names the vault, the counts, the
frontier and the lint state. In a litflow project (a folder with `rsx.toml`)
`obs` finds the project's vault by itself, and `rsx next` says what to do; see
the `research` skill. No vault found → ask the user for the path, or
`obs init PATH`.

## The model

| Note | Id | Holds |
|---|---|---|
| paper | citekey (from the .bib) | metadata, PDF path, screening decision |
| statement | S-0001 | ONE proposition, worded once, no citation inside |
| claim | C-0001 | ONE paper asserting ONE statement: verbatim quote, page, role, what it cites |
| question | Q-0001 | a ticket on a map; its answer links the claims it rests on |
| map | M-0001 | a destination; its questions; fog (not yet specified); out of scope |
| concept | slug | glossary term; aliases = synonyms = search terms |
| decision | D-0001 | a method decision that is hard to reverse |

Claim **roles**:

- `origin`: the paper shows it itself (its own data, experiment, derivation).
- `restates`: asserts it and cites other papers for it. Record the cited papers with `-c`.
- `restates-uncited`: asserts it, cites nothing for it.
- `disputes`: argues or shows the opposite.

**Drift** (`--drift`): how the wording changed against what it cites. `none`,
`weakened` (hedges added, range widened), `strengthened` (hedges dropped:
"may" became "does"; one site became "forests"), `changed` (different claim).

## Recording what a paper says

1. `obs pdf-text KEY --grep "word"` finds the sentence; `--page N` shows a page.
2. `obs statement find "the proposition"`. Reuse an existing statement whenever it
   says the same thing. Otherwise `obs statement add "..."`: one sentence, ONE
   proposition, in the source's own strength (an assumption stays an
   assumption), no author names. A sentence that joins a paper's own result
   with a result it cites ("predicts X, matching Lenard's measurements") is two
   statements: the paper's part is `origin`, the cited part is `restates -c`.
   Modern notation the paper does not use (hν for Einstein's (R/N)βν) belongs in
   a glossary alias, not in the statement.
3. `obs claim add -p KEY -s S-0001 -q "exact sentence from the PDF" -r ROLE [-c CITED_KEY ...] --by YOUR_ROLE --note "site, sensor, conditions"`.
   The quote is looked up in the PDF. Not found → nothing is saved: copy the
   wording again from `obs pdf-text`. The page is filled in from the PDF.
4. For `restates`: every paper it cites for the statement goes in `-c`. A cited
   paper missing from the vault → note it for `zot add`; `obs trace` lists it.

Done when every finding you report is a claim id, and `obs lint --note C-…`
shows no errors for your claims.

## Verifying (a different agent than the extractor)

Read the claim (`obs show C-0001`), then the page of the PDF it names. Judge
only: does the quote say the statement, in this paper, without overreach?

`obs verify C-0001 --verified|--rejected --by YOUR_ROLE --note "what the page says"`
(add `--drift strengthened` etc. when the statement is stronger than the quote).
`obs` refuses a verifier who is also the extractor.

## Seals

`obs` seals every claim and answered question it writes, and the search
records `rsx searched` adds to papers. A note written or changed by hand
(Write/Edit tools, an editor) fails `obs lint` with `hand-edited`. Redo it
with `obs`/`rsx`, or run `obs reseal ID --by YOUR_ROLE`: that accepts the
edit, makes the claim unverified again (a question loses its review, a paper
its search records), and `rsx next` sends it back to be checked.

## Provenance

`obs trace S-0001` follows the citations of a statement:

- **independent sources** = papers with a verified `origin` claim. Ten papers
  repeating one origin are one source.
- hop states: `ok`, `unverified`, `unchecked` (the cited paper has no claim on
  it yet: read it), `missing-paper`, `not-in-cited` (checked, it does not say it).
- problems: circular citation, drift, restates without citation.

Report support as "N independent sources", never as a count of papers.

Quotes are checked against the PDF text. A scan without text → `obs ocr KEY
-l deu+eng` once (needs ocrmypdf). Formulas rarely survive OCR: quote the prose
around them, and leave the formula to the verifier reading the page.

## Maps and questions (wayfinding)

A big question is a **map**; its questions are tickets, each answerable in one
session from a bounded set of sources.

- `obs map new "name" -d "what done looks like"` → M-0001
- `obs q add M-0001 "sharp question" -k KIND [-b Q-0001]` with KIND:
  `grilling` (only the user answers), `research` (find sources), `query`
  (answer from the vault), `falsify` (search for counterexamples), `task`.
- `obs frontier` lists what can be worked on now. Take ONE: `obs q claim Q --by ROLE`.
- Answering a `query` ticket: `obs ls claim …`, `obs neighbors`, `obs trace` first;
  `gnb ask` second; reading PDFs third.
- `obs q answer Q --gist "one line" --text "..." --claim C-… --statement S-… --by ROLE`.
  Research, query and falsify answers must link their evidence.
- `grilling` tickets: put the question to the user, stop, wait. Record their
  words verbatim with `--human-said "..."`.
- Questions you can see coming but cannot phrase sharply yet: `obs map fog M "..."`.
  Beyond the destination: `obs q drop Q --reason "..."`.

## Looking things up

```bash
obs ls claim verification=unverified          # filters: = != ~(contains) > <
obs ls paper year>2020 venue~remote -f year,venue
obs ls claim paper=doe2026gnsst --json
obs show S-0001                               # note + backlinks
obs neighbors S-0001 --depth 2                # the local graph
obs sql "select id, title from notes where type='statement'"   # tables: notes, links(src, field, dst)
obs glossary
```

## Glossary and decisions

- Two papers use one word differently, or two words for one thing → a term:
  `obs term add "Vegetation optical depth" -d "meaning in THIS project" --alias VOD --alias τ --not "optical thickness (optics)"`.
  Use the aliases when writing search strings.
- A method choice that is hard to reverse and was a real trade-off (exclude
  preprints, L-band only) → `obs decision "title" --decision … --context … --alternatives … --by human|ROLE`.

## Gate

`obs lint` exits 1 on errors; `obs lint --gate` prints one JSON verdict
(`pass` | `blocked`) for workflow gates; `--strict` also fails on warnings.
Errors are broken rules (missing quote, quote not in PDF, self-verified, agent
answered a grilling question, circular citation). Warnings are open work
(unverified, unchecked hop, unscreened paper). Each issue carries a `fix`.

## Papers

- `obs paper sync refs.bib` after Zotero changes (Better BibTeX keeps refs.bib
  current). Creates new paper notes, refreshes bib fields, keeps screening.
- `obs paper screen KEY --include|--exclude --reason "I2: …" --by ROLE`, citing
  the criterion from `protocol.md`.
