"""Files `obs init` writes into a new vault."""

PROTOCOL = """---
type: protocol
title: "{title} - protocol"
status: draft
---

# {title}: review protocol

Settled by grilling the user (`kind: grilling` questions). Agents read this
before searching, screening or extracting. Change it only through a decision
note (`obs decision`).

## Research question

_one sentence_

## Scope

- Phenomenon / variables:
- Sensors, methods, platforms:
- Region, ecosystems:
- Time span of publications:

## Inclusion criteria

- I1: Peer-reviewed journal article, peer-reviewed conference paper, or thesis.
- I2:

## Exclusion criteria

- E1: Not peer-reviewed (web pages, blogs, press releases). Preprints only if the user approves them in a decision note.
- E2:

## Search

- Seed papers:
- Search strings (use the glossary aliases):
- Snowballing: backward (references) and forward (citing papers), rounds:

## Evidence rules

1. Every sentence in a deliverable rests on verified claims, each with a verbatim quote and page.
2. The agent's own background knowledge chooses search directions only; it never becomes a statement.
3. Support is counted in independent origin papers, not in how often a statement is repeated.
4. A restated claim is traced to what it cites; drift (hedges dropped, ranges narrowed) is recorded.
"""

VAULT_README = """# {title}

A research vault managed with the `obs` CLI. Open it in Obsidian for the graph;
change it through `obs` so the structure stays valid. Run `obs lint` after edits.

| Folder | Note type | Id | What it is |
|---|---|---|---|
| papers/ | paper | citekey | one paper, from the Better BibTeX export (`obs paper sync`) |
| statements/ | statement | S-0001 | one proposition, worded once, without citations |
| claims/ | claim | C-0001 | one paper asserting one statement: quote, page, role, what it cites |
| questions/ | question | Q-0001 | a ticket on a map, answered with the claims it rests on |
| maps/ | map | M-0001 | a destination and its tickets (frontier, fog, out of scope) |
| concepts/ | concept | slug | glossary term with aliases (= search synonyms) |
| decisions/ | decision | D-0001 | a method decision that is hard to reverse |

`protocol.md` holds the research question, criteria and evidence rules.

Claim roles: `origin` (the paper shows it itself), `restates` (asserts it, citing
others), `restates-uncited`, `disputes`. `obs trace S-0001` follows the citations.
"""
