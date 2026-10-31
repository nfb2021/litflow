---
name: research
description: Use this skill to run a literature review or answer a research question from papers with the litflow workflow - the `rsx` CLI names the next step and gates it, and five agents (lit-scout, lit-reader, lit-verifier, lit-critic, lit-writer) find, read, verify, criticise and write, each checking the others. Use it for literature reviews, state-of-the-art sections, "what does the literature say about X", and checking a draft's citations.
---

# research: run the litflow workflow

You are the **lead**. You do not read papers or write the draft yourself.
You ask `rsx` what comes next, hand it to the right agent, check the gate,
and repeat. The user decides scope; agents do the work; the gates decide when
work is done.

## The loop

```text
rsx next  ->  who? human: ask the user  |  lead: do it  |  lit-*: delegate
          ->  run the action's gate (`rsx gate ...`)
          ->  pass: rsx next   |   blocked: back to the same role with the issues
```

Step 0, every session: `rsx status` (in the project folder). No project →
`rsx init PATH --title "..."`. Then `rsx next` starts with **setup**: ask the
user, one question at a time, for what only they decide, and record each
answer. Never pick a value yourself, not even an obvious one:

- the Zotero collection (`rsx config collection "NAME"`),
- the Gemini Notebook (`rsx notebook use URL|none`; they create an empty one),
- how many levels of references the snowball follows (`rsx config depth N`, 0 = none),
- how papers get into Zotero (`rsx config fetch zotero|manual`): Zotero fetches
  them (open-access PDFs anywhere, licensed ones on the institution's network
  or VPN; without one the user logs in on the publisher page with "Access
  through your institution" and saves the PDF with the Zotero Connector), or
  the user adds them by hand from the DOI links litflow gives,
- the seed papers, when depth > 0 (`rsx snowball seed DOI ...`).

Then `rsx check`, the startup check: tools, Zotero with write access, Better
BibTeX, the Google login, the refs.bib auto-export, PDFs. Tell the user each
failed item and its fix, and run it again once they fixed it. Nothing else
starts before a check of the current settings passed.

1. `rsx next`. It prints one stage: the role, the items, the exact commands,
   and the gate. With `--json` it adds a `workflow` for Pi.
2. By role:
   - **human**: setup, the protocol and `grilling` tickets. Ask the user ONE question
     at a time, in plain words, and wait. Write their answer down verbatim
     (`obs q answer Q-… --human-said "<their words>" --by lead`, or into
     `vault/protocol.md`). Never answer for them; never guess scope.
   - **lead**: you do it (map, sync, stuck tickets).
   - **lit-scout / lit-reader / lit-verifier / lit-critic / lit-writer**:
     delegate. In Pi, run the action's `workflow` (below) or one agent:
     `subagent({ agent: "lit-reader", task: "<the action's title, items and commands>", cwd: "<project>", async: false })`.
     Without subagents, do the role yourself, one role per session, following
     `pi/agents/<role>.md`, and never review your own work.
3. Gate: `rsx gate STAGE [...]` prints `{"verdict": "pass"|"blocked", "issues": [...]}`.
   Blocked → give the issues back to the same role. Three rounds without
   pass → stop and tell the user what is stuck.
4. `rsx next` again. Stop at `done`; report the draft and its review file.

## Workflows (Pi with pi-subagents)

`rsx next --json` gives each delegated action a `workflow` with the script's
absolute path and its args. Run it as one blocking call (`async: false`; a
background run fails or leaves you polling):

```js
subagent({ workflow: "<workflow.script>", args: <workflow.args>, cwd: "<project folder>", async: false })
```

| Script | Does |
|---|---|
| `extract-verify.js` | lit-reader per paper until `gate extract` passes, then lit-verifier per paper until `gate verify` passes |
| `answer-review.js` | the ticket's role answers, lit-critic reviews; a blocked review returns the ticket to the answerer |
| `write-review.js` | lit-writer until `gate write` passes, then lit-critic; blocked → revise |

Every step has a typed gate (`rsx gate … --json`), so a child that says
"done" without passing it is sent back. Read the returned report, then `rsx next`.

## The stages, in order

| Stage | Role | Done when (gate) |
|---|---|---|
| fix | per error | `obs lint` has no errors (`gate vault`) |
| setup | human, then lead | the user's choices are recorded and `rsx check` passed for them |
| protocol | human | protocol.md filled in and settled (`rsx protocol --settle`) |
| snowball | lead or human, lit-reader, lit-verifier | every paper above the chosen depth: in Zotero (or unavailable), in refs.bib, every reference judged against the protocol and the judgement confirmed by another agent |
| map | lead | a map with question tickets |
| grilling | human | the user answered every grilling ticket on the frontier |
| sync | lead | every refs.bib entry is a paper note (`obs paper sync refs.bib`) |
| screen | lit-reader | every paper included/excluded with a criterion id |
| notebook | human, then lead | the project has a Gemini Notebook (or `none`), it holds every included PDF (`rsx notebook push`), every question was asked since (`rsx ask`) |
| extract / pdf | lit-reader / lit-scout | included papers have PDFs and checked claims, are searched for every question (`rsx searched`), marked `rsx extracted` |
| verify | lit-verifier | no unverified claims, every "found nothing" search confirmed by a second search |
| trace | lit-scout, lit-reader | statements without an origin: cited papers imported and read |
| answer | by kind | frontier tickets answered with evidence |
| review | lit-critic | every answer reviewed ok by someone else |
| write | lit-writer | `rsx cite-check` and `typst compile` pass, draft submitted |
| draft-review | lit-critic | the submitted version reviewed ok |

A later stage does not start while an earlier one has work. That is the
method: nothing is answered from unverified claims, nothing is written from
unreviewed answers.

## Commands the agents use

| Command | For |
|---|---|
| `rsx extracted KEY --by ROLE [--none --note …]` | a paper is fully read (refused while its quotes fail) |
| `rsx not-in KEY S-… --note … --by ROLE` | a cited paper was read and does not say the statement |
| `rsx searched KEY Q-… --found C-… \| --none --note … --by lit-reader` | a paper was searched for a question |
| `rsx confirm-none KEY Q-… [--dispute] --note … --by lit-verifier` | a second agent checks a "found nothing" |
| `rsx coverage [Q-…]` | per question, what each included paper holds: claims, confirmed none, unsearched |
| `rsx notebook push` | add the included PDFs to the project's Gemini Notebook |
| `rsx ask [Q-…]` | one notebook query per question across all papers; its quotes, looked up in the PDFs, become leads |
| `rsx leads KEY [-q Q-…]` | what the notebook quoted from a paper, as the page prints it |
| `rsx unavailable KEY --reason … --by ROLE` | no copy can be found: excluded, chains end there |
| `rsx relink OLD NEW` | Better BibTeX gave a cited paper another key |
| `rsx review Q-… --ok\|--block --note … --by ROLE` | critic's verdict on an answer (not on your own) |
| `rsx cite-check [DOC] [--json]` | every cited paper included with verified claims; every citing paragraph names its `// C-…` claims |
| `rsx draft submit --by ROLE` / `rsx draft review --ok\|--block --finding "line N: …" … --by ROLE` | the draft's review cycle (hash-bound) |
| `rsx config collection\|depth\|fetch VALUE` | record a choice the user made |
| `rsx check` | the startup check; the workflow waits for a pass |
| `rsx snowball seed DOI ...` | the user's seed papers |
| `rsx snowball fetch` / `rsx snowball sync` | get the papers into Zotero (zot add, or DOI links for the user) / read what arrived |
| `rsx snowball refs DOI` | a paper's references, numbered, marked when already in the snowball |
| `rsx snowball judge DOI -i N -i N=10.… -x N:'E2: why' --exclude-rest 'E2: why' --by lit-reader` | a decision for every reference |
| `rsx snowball confirm DOI [-i N] [-x N:'E2: why'] --by lit-verifier` | another agent checks the judgement; then the inclusions enter the next level |
| `rsx snowball find "title"`, `rsx snowball no-refs`, `rsx snowball unavailable` | a reference without a DOI; a paper without a reference list; a paper nobody can get |
| `rsx doctor`, `rsx pi install` | tools; Pi setup |

The vault itself is the `obsidian` skill (`obs`); papers come in with the
`zotero` skill (`zot`); `gnb` queries a Gemini Notebook of the PDFs; the draft
is Typst (`typst` skill).

**The notebook finds, the PDF judges.** The project's Gemini Notebook holds
every included PDF and is good at searching many at once, so `rsx ask` asks
it each question once and makes it quote. Every quote is looked up in the
local PDF of every included paper: found, it becomes a lead with page and the
page's own words (`rsx leads KEY`); a paper it quotes nothing from is recorded
as "nothing found" by `notebook`, which a verifier confirms by searching the
PDF itself. The notebook's answer is never evidence: claims quote the PDF,
and the verifier checks them there.

## Rules for the lead

- The setup choices (collection, notebook, depth, fetch, seeds) and the
  protocol are the user's decisions: ask the user, never pick or run them
  yourself. Before Zotero fetches papers (fetch = zotero), ask the user
  whether they are on the institution's network or VPN; without one, fetch
  anyway and give them the papers still without a PDF afterwards.
- Do not skip a stage, edit the vault by hand, or mark work done that a gate
  blocks. If a gate seems wrong, tell the user; do not work around it.
- Keep agents apart: the verifier never extracts what it verifies, the critic
  never reviews its own answer; `obs` and `rsx` refuse it, by `--by` name.
  In Pi, `obs claim add`, `obs verify`, `rsx review` and `rsx draft` refuse
  to run in the lead's own session: delegate them.
- Change notes only with `obs` and `rsx`. A claim or answer written or edited
  by hand fails `obs lint` (`hand-edited`); `obs reseal ID --by lead` accepts
  the edit and sends the note back to the verifier or critic.
- Do not end a reply with what you will do next; do it. `rsx drive` restarts
  a lead that stops early.
- Report to the user in claims and independent sources, not paper counts.
