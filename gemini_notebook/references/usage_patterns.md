# Gemini Notebook Skill Usage Patterns

Workflows for using the skill well. All commands are `gnb`, which runs from any directory
(see SKILL.md, Step 0, if it is not installed).

## First run

```bash
gnb auth status          # not logged in?
gnb auth setup           # visible Chrome: the user logs in to Google
gnb library list         # empty on a fresh install
```

## Adding a notebook

**User shares a URL without details** → ask the notebook first, never invent metadata:

```bash
gnb ask "What is the content of this notebook? What topics are covered? Provide a complete overview briefly and concisely" -n "https://notebook.google.com/notebook/..."

gnb library add "https://notebook.google.com/notebook/..." \
  --name "GNSS-T VOD" \
  --description "Papers on GNSS-transmissometry vegetation optical depth" \
  --topics "GNSS-T,VOD,forest structure"
```

**User gives the details** → add directly. If description or topics are missing, ask the
user or use the discovery query above.

## Asking questions

```bash
gnb library list                       # pick the notebook for the topic
gnb ask "Question with full context" -n notebook-id
```

### Follow-ups

Each `gnb ask` is a new browser session with no memory. When the answer ends with
*"Is that ALL you need to know?"*, compare it with the user's request and ask again with
the full context:

```bash
gnb ask "What are the main retrieval methods for VOD?" -n gnss-t-vod
gnb ask "For the GNSS-T VOD retrieval methods (single-antenna vs. paired-receiver), what are the reported accuracies and their validation data?" -n gnss-t-vod
```

Then synthesize all answers before replying.

### Long answers

Source inventories and long summaries can take minutes: `--timeout 400`.

### Comparing notebooks

```bash
gnb ask "How is the footprint defined?" -n gnss-ir-footprint-and-gridding
gnb ask "How is the footprint defined?" -n gnss-t-vod
```

## Adding sources

Only add sources the user asked for: it changes their notebook.

```bash
gnb add -n gnss-t-vod --file ~/papers/new_paper.pdf
gnb add -n gnss-t-vod --url "https://example.org/article" --url "https://youtu.be/..."
gnb add -n gnss-t-vod --text-file meeting_notes.md       # e.g. Claude's own summaries
```

Check the result list: a `failed` website (paywall, blocked site) can be added again as a
PDF or as pasted text. After adding, a question that mentions the new source confirms
Gemini can read it.

## Login problems

```bash
gnb auth status          # how old is the login?
gnb auth reauth          # visible browser, log in again (or with another account)

# Browser profile broken:
gnb cleanup --confirm --preserve-library
gnb auth setup
```

## Batch questions from a script

```python
import subprocess


def ask(question, notebook):
    r = subprocess.run(
        ["gnb", "ask", question, "-n", notebook], capture_output=True, text=True
    )
    return r.stdout.split("=" * 60)[2].strip() if r.returncode == 0 else None


for q in ["Main findings?", "Study sites?", "Open problems?"]:
    print(q, ask(q, "gnss-t-vod"))
```

Mind the ≈50 questions/day limit on free accounts.

## Best practices

1. **Check auth first** - `gnb auth status`
2. **Pick the notebook explicitly** - `-n ID` instead of relying on the active one
3. **Self-contained questions** - every question is a new session
4. **Follow up** until the user's request is fully covered
5. **Never invent notebook metadata** - discover it or ask
6. **Confirm before adding sources** that the user wanted them added

## Quick reference

```bash
gnb auth status | setup | reauth
gnb library list | add URL ... | activate ID | search Q
gnb ask "..." [-n ID|URL] [--timeout 400] [--show-browser]
gnb add [-n ID|URL] --file F --url U --text T --text-file P
gnb cleanup [--confirm] [--preserve-library]
```
