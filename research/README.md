# research: run the literature workflow (`rsx`)

`rsx` runs a literature review as a sequence of steps that agents cannot skip. It reads the
project (vault, `refs.bib`, Typst draft) and says what comes next, who does it, which
commands to run and which check must pass before the step counts as done. Five agents do
the work in [Pi](https://pi.dev) and check each other; any agent, Claude Code included, can
follow the same steps.

It is built for small models (the free university models in Pi): the rules are in the
commands and the checks, not only in the prompts.

## Setup

```bash
uv tool install --editable ~/src/litflow/research      # rsx (brings obs's code along)
rsx doctor                                              # obs, zot, gnb, typst, Zotero, Pi
rsx pi install                                          # Pi: load litflow skills, agents, typst
```

`rsx pi install` adds `~/src/litflow` to `packages` and the typst skill folder to `skills` in
`~/.pi/agent/settings.json` (a backup is kept as `settings.json.bak`). Restart Pi or run
`/reload`.

## A project

```bash
rsx init ~/research/vod-review --title "VOD and canopy water"
cd ~/research/vod-review
rsx next
```

```text
vod-review/
  rsx.toml          title and paths
  refs.bib          Better BibTeX auto-export of the project's Zotero collection
  vault/            the obs vault: papers, statements, claims, questions, protocol.md
  paper/main.typ    the draft
  reviews/          draft submissions and reviews
```

In Zotero, export the project's collection with Better BibLaTeX to `refs.bib` and tick
*Keep updated*. `obs` run anywhere in the project uses `vault/`.

## The steps

`rsx next` returns the first step that has open work. A later step does not start while an
earlier one has work, so nothing is answered from unverified claims and nothing is written
from unreviewed answers.

| Step | Who | Done when |
|---|---|---|
| fix | depends on the error | `obs lint` reports no errors |
| protocol | you | `vault/protocol.md` is filled in and `rsx protocol --settle` accepted it |
| map | lead | there is a map with question tickets |
| grilling | you | you answered the scope questions the agents may not decide |
| sync | lead | every entry of `refs.bib` is a paper in the vault |
| screen | lit-reader | every paper is included or excluded, with a criterion id from the protocol |
| extract, pdf | lit-reader, lit-scout | every included paper has a PDF and quote-checked claims, marked with `rsx extracted` |
| verify | lit-verifier | no claim is unverified |
| trace | lit-scout, lit-reader | statements without an origin have their cited papers imported and read |
| answer | by ticket kind | the frontier tickets are answered, with the claims they rest on |
| review | lit-critic | each answer was reviewed ok by an agent that did not write it |
| write | lit-writer | `rsx cite-check` and `typst compile` pass and the draft was submitted |
| draft review | lit-critic | the submitted version was reviewed ok |

Each step names its check, e.g. `rsx gate extract --paper doe2026gnsst`. A gate prints one
JSON verdict, `pass` or `blocked` with the issues, and exits 0 either way, so a workflow can
read it:

```json
{"verdict": "blocked", "stage": "extract", "paper": "doe2026gnsst",
 "issues": ["C-0003: quote not-found in the PDF; copy it from `obs pdf-text`"]}
```

## The agents

| Agent | Does | Never |
|---|---|---|
| `lit-scout` | finds papers, imports them by DOI with `zot add`, fetches PDFs | types a DOI from memory, screens |
| `lit-reader` | screens; extracts claims with verbatim quotes; reads cited papers; answers query tickets | verifies |
| `lit-verifier` | re-reads every claim on its page: verified or rejected | verifies its own extraction (`obs` refuses) |
| `lit-critic` | tries to break answers and the draft; falsify tickets | reviews its own work (`rsx` refuses) |
| `lit-writer` | writes the Typst draft from reviewed answers and verified claims | writes from its own knowledge |

They are in [`pi/agents/`](pi/agents/) and load through the repository's `package.json`. The
lead is the main Pi session (or Claude Code) following [SKILL.md](SKILL.md).

The lead only orchestrates. In Pi, `obs claim add`, `obs verify`, `rsx review` and `rsx draft
submit|review` refuse to run in the lead's own session (its shell has Pi's session variables; its subagents'
shells do not), and `obs lint` blocks claims and answers written by hand. So the lead cannot
quietly do the reader's, verifier's or critic's job.

Weak models often end a run with a plan instead of a tool call. `rsx drive --model
aqueduct/qwen-3.6-35b` starts the lead again on the same project until `rsx next` says done or
needs the user, and stops after two rounds without progress. Logs go to `.rsx/drive/`.

## Workflows

For steps with many items, `rsx next --json` names a pi-subagents workflow script and its
arguments. The lead runs it in one call:

```js
subagent({ workflow: "~/src/litflow/research/pi/workflows/extract-verify.js",
           args: { papers: ["doe2026gnsst", "roe2019review"] }, cwd: "~/research/vod-review",
           async: false })
```

| Script | Loop |
|---|---|
| [`extract-verify.js`](pi/workflows/extract-verify.js) | a lit-reader per paper until its extract gate passes, then a lit-verifier per paper until its verify gate passes |
| [`answer-review.js`](pi/workflows/answer-review.js) | the ticket's agent answers, lit-critic reviews; a blocked review sends the ticket back with the critic's note |
| [`write-review.js`](pi/workflows/write-review.js) | lit-writer until the write gate passes, then lit-critic; blocked means revise |

Every agent step carries a typed gate (`gate: { command: "rsx gate …", output: "json" }`):
an agent that reports success without passing its gate gets the issues back, up to `rounds`
times (default 2). After that the lead decides, or asks you.

## Citations in the draft

`typst compile` already fails on a key missing from `refs.bib`. `rsx cite-check` adds what
Typst cannot know. Each cited sentence ends with a comment naming the verified claims it
rests on:

```typst
One light quantum gives its whole energy to one electron @einstein1905heuristischen. // C-0004
```

| Check | Error when |
|---|---|
| `cite-not-in-vault` | the cited key is not a paper in the vault |
| `cite-not-included` | the paper was excluded in screening, or not screened |
| `cite-no-verified-claim` | the paper has no verified claim |
| `citation-without-claim` | the paragraph cites a paper but names none of its claims |
| `claim-not-verified`, `claim-unknown` | a named claim is unverified, rejected or does not exist |
| `claim-paper-not-cited` | a named claim belongs to a paper the paragraph does not cite |
| `cites-restating-paper` (warning) | the claim only restates the statement; the vault knows the origin |

## Reviews

A review is tied to what it reviewed. `rsx review Q-0003 --block --note "…"` reopens the
ticket; once it is answered again, the old review no longer counts. `rsx draft submit` records
a hash of the draft; `rsx draft review` refuses a version that changed after submission. Both
refuse a reviewer whose `--by` name is the author's.

## Commands

| Command | |
|---|---|
| `rsx init PATH --title T` | new project |
| `rsx next [--role R] [--json]` | the next step |
| `rsx status [--json]` | counts, current step, draft state |
| `rsx gate STAGE [--paper K] [--question Q]` | one JSON verdict; stages: vault, protocol, map, grilling, sync, screen, pdf, extract, verify, trace, answer, review, write, draft, all |
| `rsx protocol [--settle]` | what the protocol still lacks; settle it |
| `rsx extracted KEY --by R [--none --note N]` | a paper is fully read |
| `rsx not-in KEY S-… --note N --by R` | a cited paper does not state the statement |
| `rsx unavailable KEY --reason N --by R` | no copy can be found: excluded, chains end there |
| `rsx relink OLD NEW` | point claim citations at a paper's real key |
| `rsx review Q-… --ok\|--block --note N --by R` | review an answer |
| `rsx cite-check [DOC] [--json]` | check the draft's citations |
| `rsx draft submit\|review\|show` | the draft's review cycle |
| `rsx drive [--model M] [--rounds N] [--pi CMD]` | run the Pi lead again until done, a human step, two rounds without progress, or a model error (e.g. a timeout) |
| `rsx doctor`, `rsx pi install` | setup |

## Development

```bash
cd ~/src/litflow/research
uv run --group dev pytest -q
```

The tests run the whole workflow on a small project with the obsidian skill's fixture PDF.
