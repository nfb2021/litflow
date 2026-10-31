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
`rsx init PATH --title "..."`, then ask the user to point a Better BibTeX
auto-export of their Zotero collection at `PATH/refs.bib`.

1. `rsx next`. It prints one stage: the role, the items, the exact commands,
   and the gate. With `--json` it adds a `workflow` for Pi.
2. By role:
   - **human**: the protocol and `grilling` tickets. Ask the user ONE question
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
| protocol | human | protocol.md filled in and settled (`rsx protocol --settle`) |
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
| `rsx doctor`, `rsx pi install` | setup |

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

- `rsx notebook use` is the user's decision (a notebook, or `none`): ask the
  user, never run it yourself.
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
