import json
import shlex
import shutil
from pathlib import Path

import pytest
from obs.cli import app as obs_app
from typer.testing import CliRunner

from rsx import cite, gates
from rsx.cli import app as rsx_app

FIXTURE = Path(__file__).parents[2] / "obsidian" / "tests" / "fixtures" / "paper.pdf"
QUOTE = "Vegetation optical depth increases with canopy water content, as shown by our dual-receiver GNSS transmissometry"
BIB = r"""
@article{doe2026gnsst,
  title = {{GNSS-T} ecohydrological monitoring in a beech forest},
  author = {Doe, Jane F.},
  journal = {Remote Sensing of Environment},
  year = {2026},
  file = {PDFPATH}
}
@article{roe2019review,
  title = {A review of canopy water},
  author = {Roe, Richard},
  journal = {Reviews},
  year = {2019}
}
"""
FILLED = {
    "_one sentence_": "Does VOD track canopy water content?",
    "- Phenomenon / variables:": "- Phenomenon / variables: VOD",
    "- Sensors, methods, platforms:": "- Sensors, methods, platforms: GNSS-T",
    "- Region, ecosystems:": "- Region, ecosystems: forests",
    "- Time span of publications:": "- Time span of publications: 2000-2026",
    "- I2:": "- I2: Reports VOD measurements.",
    "- E2:": "- E2: none",
    "- Seed papers:": "- Seed papers: doe2026gnsst",
    "- Search strings (use the glossary aliases):": "- Search strings (use the glossary aliases): VOD",
}


@pytest.fixture
def lf(tmp_path, monkeypatch):
    """A fresh project; lf.rsx(...) and lf.obs(...) run in it."""
    runner = CliRunner()
    root = tmp_path / "proj"
    for var in ("OBS_VAULT", "RSX_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    # CI has no typst; compiling is tested separately
    monkeypatch.setattr(gates, "compile_doc", lambda x: [])

    def make(app):
        def run(*args, ok=True):
            r = runner.invoke(app, [str(a) for a in args])
            if ok is not None:
                assert (r.exit_code == 0) == ok, r.output
            return r

        return run

    class LF:
        rsx = staticmethod(make(rsx_app))
        obs = staticmethod(make(obs_app))

    LF.rsx("init", root, "--title", "VOD")
    monkeypatch.chdir(root)
    (root / "refs.bib").write_text(BIB.replace("PDFPATH", str(FIXTURE)))
    LF.root = root
    return LF


def nxt(lf) -> dict:
    return json.loads(lf.rsx("next", "--json").stdout)[0]


def gate(lf, *args) -> dict:
    return json.loads(lf.rsx("gate", *args).stdout)


def fill_protocol(root: Path) -> None:
    p = root / "vault" / "protocol.md"
    s = p.read_text()
    for a, b in FILLED.items():
        s = s.replace(a, b)
    p.write_text(s)


# --- project ---------------------------------------------------------------------
def test_init_layout_and_obs_finds_the_vault(lf):
    for p in ("rsx.toml", "vault/obs.toml", "refs.bib", "paper/main.typ", "reviews"):
        assert (lf.root / p).exists(), p
    assert '#bibliography("../refs.bib"' in (lf.root / "paper/main.typ").read_text()
    # obs, run from the project root, uses the vault named in rsx.toml
    r = lf.obs("status", "--json")
    assert json.loads(r.stdout)["vault"] == str((lf.root / "vault").resolve())
    lf.rsx("init", lf.root, "--title", "again", ok=False)


def test_protocol_gaps_block_settling(lf):
    assert nxt(lf)["stage"] == "protocol"
    r = lf.rsx("protocol", "--settle", ok=False)
    assert "Research question" in r.output
    assert gate(lf, "protocol")["verdict"] == "blocked"
    fill_protocol(lf.root)
    lf.rsx("protocol", "--settle")
    assert gate(lf, "protocol")["verdict"] == "pass"
    assert nxt(lf)["stage"] == "map"


# --- the whole workflow -------------------------------------------------------------
def test_workflow_end_to_end(lf):
    fill_protocol(lf.root)
    lf.rsx("protocol", "--settle")
    lf.obs("map", "new", "VOD and water", "-d", "evidence for the link")
    lf.obs("q", "add", "M-0001", "Does VOD rise with canopy water?", "-k", "query")
    lf.obs("q", "add", "M-0001", "Include airborne studies?", "-k", "grilling")

    a = nxt(lf)
    assert (a["stage"], a["role"], a["items"]) == ("grilling", "human", ["Q-0002"])
    lf.obs(
        "q", "answer", "Q-0002", "--gist", "no", "--human-said", "No.", "--by", "lead"
    )

    a = nxt(lf)
    assert a["stage"] == "sync" and set(a["items"]) == {"doe2026gnsst", "roe2019review"}
    lf.obs("paper", "sync", "refs.bib")

    a = nxt(lf)
    assert a["stage"] == "screen" and a["role"] == "lit-reader"
    # a reason without a criterion id does not count
    lf.obs(
        "paper",
        "screen",
        "doe2026gnsst",
        "--include",
        "--reason",
        "fits",
        "--by",
        "lit-reader",
    )
    assert "doe2026gnsst" in nxt(lf)["items"]
    lf.obs(
        "paper",
        "screen",
        "doe2026gnsst",
        "--include",
        "--reason",
        "I2: VOD data",
        "--by",
        "lit-reader",
    )
    lf.obs(
        "paper",
        "screen",
        "roe2019review",
        "--include",
        "--reason",
        "I1: review",
        "--by",
        "lit-reader",
    )

    # extraction and the missing PDF come together
    acts = json.loads(lf.rsx("next", "--json").stdout)
    assert [(x["stage"], x["items"]) for x in acts] == [
        ("extract", ["doe2026gnsst"]),
        ("pdf", ["roe2019review"]),
    ]
    assert acts[0]["workflow"]["script"].endswith("extract-verify.js")
    assert acts[0]["gate"] == "rsx gate extract --paper doe2026gnsst"
    lf.rsx("unavailable", "roe2019review", "--reason", "paywalled", "--by", "lit-scout")

    lf.obs("statement", "add", "VOD increases with canopy water content")
    assert gate(lf, "extract", "--paper", "doe2026gnsst")["verdict"] == "blocked"
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader", ok=False)  # no claims
    lf.obs(
        "claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", QUOTE,
        "-r", "origin", "--by", "lit-reader",
    )  # fmt: skip
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader")
    assert gate(lf, "extract", "--paper", "doe2026gnsst")["verdict"] == "pass"

    a = nxt(lf)
    assert (a["stage"], a["role"]) == ("verify", "lit-verifier")
    assert gate(lf, "verify", "--paper", "doe2026gnsst")["verdict"] == "blocked"
    lf.obs("verify", "C-0001", "--verified", "--by", "lit-verifier", "--note", "p1")
    assert gate(lf, "verify")["verdict"] == "pass"

    a = nxt(lf)
    assert (a["stage"], a["role"], a["items"]) == ("answer", "lit-reader", ["Q-0001"])
    assert "obs q claim Q-0001 --by lit-reader" in a["commands"]
    assert gate(lf, "answer", "--question", "Q-0001")["verdict"] == "blocked"
    lf.obs("q", "answer", "Q-0001", "--gist", "yes", "--text", "Yes (C-0001).",
           "--claim", "C-0001", "--by", "lit-reader")  # fmt: skip
    assert gate(lf, "answer", "--question", "Q-0001")["verdict"] == "pass"

    a = nxt(lf)
    assert (a["stage"], a["role"]) == ("review", "lit-critic")
    g = gate(lf, "review", "--question", "Q-0001")
    assert g["verdict"] == "blocked" and g["reviews"]["Q-0001"] == "none"
    lf.rsx("review", "Q-0001", "--ok", "--note", "x", "--by", "lit-reader", ok=False)
    lf.rsx(
        "review", "Q-0001", "--block", "--note", "one site only", "--by", "lit-critic"
    )
    assert (
        gate(lf, "review", "--question", "Q-0001")["reviews"]["Q-0001"]
        == "current-blocked"
    )
    assert nxt(lf)["stage"] == "answer"  # back on the frontier
    lf.obs("q", "answer", "Q-0001", "--gist", "yes, at one site", "--text", "At one beech site (C-0001).",
           "--claim", "C-0001", "--by", "lit-reader")  # fmt: skip
    assert gate(lf, "review", "--question", "Q-0001")["reviews"]["Q-0001"] == "stale"
    lf.rsx(
        "review", "Q-0001", "--ok", "--note", "matches the quote", "--by", "lit-critic"
    )

    a = nxt(lf)
    assert (a["stage"], a["role"]) == ("write", "lit-writer")
    doc = lf.root / "paper" / "main.typ"
    text = doc.read_text()
    doc.write_text(
        text.replace(
            "#bibliography",
            "At one beech site, VOD rose with canopy water content @doe2026gnsst.\n\n#bibliography",
        )
    )
    g = gate(lf, "write")
    assert g["verdict"] == "blocked"
    assert any("citation-without-claim" in i for i in g["issues"])
    lf.rsx("draft", "submit", "--by", "lit-writer", ok=False)
    doc.write_text(
        doc.read_text().replace("@doe2026gnsst.", "@doe2026gnsst. // C-0001")
    )
    assert "submit it" in gate(lf, "write")["issues"][0]
    lf.rsx("draft", "submit", "--by", "lit-writer")
    assert gate(lf, "write")["verdict"] == "pass"

    a = nxt(lf)
    assert (a["stage"], a["role"]) == ("draft-review", "lit-critic")
    lf.rsx("draft", "review", "--ok", "--text", "fine", "--by", "lit-writer", ok=False)
    lf.rsx(
        "draft",
        "review",
        "--block",
        "--text",
        "line 18: add the site",
        "--by",
        "lit-critic",
    )
    a = nxt(lf)
    assert a["stage"] == "write" and a["title"] == "Revise the draft"
    # an edit after submission needs a new submission before review
    doc.write_text(
        doc.read_text().replace("At one beech site", "At one beech site in 2025")
    )
    lf.rsx("draft", "review", "--ok", "--text", "fine", "--by", "lit-critic", ok=False)
    lf.rsx("draft", "submit", "--by", "lit-writer")
    lf.rsx(
        "draft",
        "review",
        "--ok",
        "--text",
        "each sentence matches C-0001",
        "--by",
        "lit-critic",
    )
    assert gate(lf, "draft") == {
        "verdict": "pass",
        "stage": "draft",
        "review": "ok",
        "review_file": "reviews/004-review.md",
        "issues": [],
    }
    assert nxt(lf)["stage"] == "done"
    assert gate(lf, "all")["verdict"] == "pass"


def test_lint_errors_come_first(lf):
    fill_protocol(lf.root)
    lf.rsx("protocol", "--settle")
    lf.obs("paper", "sync", "refs.bib")
    lf.obs("statement", "add", "VOD increases with canopy water content")
    lf.obs("claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", QUOTE,
           "-r", "origin", "--by", "lit-reader")  # fmt: skip
    claim = lf.root / "vault" / "claims" / "C-0001.md"
    claim.write_text(
        claim.read_text().replace("quote_check: found", "quote_check: not-found")
    )
    a = nxt(lf)
    assert (a["stage"], a["role"], a["items"]) == ("fix", "lit-reader", ["C-0001"])
    assert gate(lf, "vault")["verdict"] == "blocked"


def test_trace_chases_unsupported_statements_until_resolved(lf):
    fill_protocol(lf.root)
    lf.rsx("protocol", "--settle")
    lf.obs("map", "new", "m", "-d", "d")
    lf.obs("q", "add", "M-0001", "q?", "-k", "query")
    lf.obs("paper", "sync", "refs.bib")
    for k in ("doe2026gnsst", "roe2019review"):
        lf.obs(
            "paper", "screen", k, "--include", "--reason", "I1: x", "--by", "lit-reader"
        )
    lf.obs("statement", "add", "VOD increases with canopy water content")
    # doe only restates it, citing roe (no PDF) and smith (not in the vault)
    lf.obs("claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", QUOTE, "-r", "restates",
           "-c", "roe2019review", "-c", "smith2020", "--by", "lit-reader")  # fmt: skip
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader")
    lf.rsx("unavailable", "roe2019review", "--reason", "x", "--by", "lit-scout")
    lf.obs("verify", "C-0001", "--verified", "--by", "lit-verifier", "--note", "p1")
    a = nxt(lf)
    assert (a["stage"], a["role"], a["items"]) == (
        "trace-import",
        "lit-scout",
        ["smith2020"],
    )
    assert gate(lf, "trace")["verdict"] == "blocked"
    lf.rsx("unavailable", "smith2020", "--reason", "no DOI found", "--by", "lit-scout")
    assert gate(lf, "trace")["verdict"] == "pass"
    assert nxt(lf)["stage"] == "answer"


def test_not_in_ends_a_trace_read(lf):
    fill_protocol(lf.root)
    lf.rsx("protocol", "--settle")
    lf.obs("map", "new", "m", "-d", "d")
    lf.obs("q", "add", "M-0001", "q?", "-k", "query")
    lf.obs("paper", "sync", "refs.bib")
    for k in ("doe2026gnsst", "roe2019review"):
        lf.obs("paper", "screen", k, "--include", "--reason", "I1: x", "--by", "r")
    # roe gets a PDF, so it can be read
    p = lf.root / "vault" / "papers" / "roe2019review.md"
    p.write_text(p.read_text().replace("year: 2019", f"year: 2019\npdf: {FIXTURE}"))
    lf.obs("statement", "add", "VOD increases with canopy water content")
    lf.obs("claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", QUOTE, "-r", "restates",
           "-c", "roe2019review", "--by", "lit-reader")  # fmt: skip
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader")
    lf.rsx(
        "extracted", "roe2019review", "--none", "--by", "lit-reader", ok=False
    )  # needs --note
    lf.rsx(
        "extracted",
        "roe2019review",
        "--none",
        "--note",
        "off topic",
        "--by",
        "lit-reader",
    )
    lf.obs("verify", "C-0001", "--verified", "--by", "lit-verifier", "--note", "p1")
    a = nxt(lf)
    assert (a["stage"], a["role"], a["items"]) == (
        "trace-read",
        "lit-reader",
        ["roe2019review"],
    )
    assert "# roe2019review: check S-0001" in a["commands"]
    assert gate(lf, "trace")["verdict"] == "blocked"
    lf.rsx(
        "not-in",
        "roe2019review",
        "S-0001",
        "--note",
        "about soil",
        "--by",
        "lit-reader",
    )
    assert gate(lf, "trace")["verdict"] == "pass"
    assert nxt(lf)["stage"] == "answer"
    # a paper that has a claim on the statement cannot be marked not-in
    lf.rsx(
        "not-in",
        "doe2026gnsst",
        "S-0001",
        "--note",
        "x",
        "--by",
        "lit-reader",
        ok=False,
    )


# --- cite-check ------------------------------------------------------------------
def test_paragraphs_parse_typst():
    src = "\n".join(
        [
            "// header comment C-9999 is not a claim of a paragraph",
            '#set text(lang: "en")',
            "= Intro <sec-intro>",
            "",
            "A sentence @doe2026gnsst. // C-0001",
            'continues here #cite(<roe2019>) and #cite(label("lee2021")).',
            "// C-0002, C-0003",
            "",
            "See @sec-intro. Mail me at a\\@b.org; `@notacite` in raw.",
            "/* @hidden C-0004 */",
            "```",
            "@inraw",
            "```",
            "Visit https://example.org/path @smith:2020.",
        ]
    )
    paras, labels = cite.paragraphs(src)
    assert "sec-intro" in labels
    body = [p for p in paras if not p.text.strip().startswith("=")]
    assert body[0].cites == ["doe2026gnsst", "roe2019", "lee2021"]
    assert body[0].claims == ["C-0001", "C-0002", "C-0003"]
    assert body[0].line == 5
    assert body[1].cites == []  # label ref, escaped @, raw
    assert body[2].cites == ["smith:2020"]


def test_cite_check_without_vault_papers(lf):
    r = lf.rsx("cite-check", "--json")  # the template cites nothing: no errors
    assert json.loads(r.stdout)["errors"] == 0
    doc = lf.root / "paper" / "main.typ"
    doc.write_text("Claim @ghost. // C-0042\n")
    r = json.loads(lf.rsx("cite-check", "--json", ok=False).stdout)
    codes = {i["code"] for i in r["issues"]}
    assert codes == {"cite-not-in-vault", "claim-unknown"}


@pytest.mark.skipif(not shutil.which("typst"), reason="typst not installed")
def test_compile_doc_runs_typst(lf, monkeypatch):
    monkeypatch.undo()
    from rsx import project
    from rsx.plan import Ctx

    monkeypatch.chdir(lf.root)
    x = Ctx.of(project.find())
    assert gates.compile_doc(x) == []
    (lf.root / "paper" / "main.typ").write_text("@nobody\n")
    assert gates.compile_doc(x)[0] == "typst compile failed:"


# --- setup -----------------------------------------------------------------------
def test_pi_install_is_idempotent(tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "pi"))
    repo = tmp_path / "litflow"
    repo.mkdir()
    (repo / "package.json").write_text("{}")
    (tmp_path / "pi").mkdir()
    (tmp_path / "pi" / "settings.json").write_text(json.dumps({"packages": ["npm:x"]}))
    args = [
        "pi",
        "install",
        "--repo",
        str(repo),
        "--typst-skills",
        str(tmp_path / "none"),
    ]
    r = runner.invoke(rsx_app, args)
    assert r.exit_code == 0, r.output
    data = json.loads((tmp_path / "pi" / "settings.json").read_text())
    assert data["packages"] == ["npm:x", str(repo.resolve())]
    assert (tmp_path / "pi" / "settings.json.bak").exists()
    r = runner.invoke(rsx_app, args)
    assert "already set up" in r.output
    r = runner.invoke(rsx_app, ["pi", "install", "--repo", str(tmp_path)])
    assert r.exit_code == 1


def test_gate_unknown_stage(lf):
    lf.rsx("gate", "nonsense", ok=False)


def test_agents_and_workflows_are_wired():
    root = Path(__file__).parents[1]
    agents = {p.stem for p in (root / "pi" / "agents").glob("*.md")}
    assert agents == {
        "lit-scout",
        "lit-reader",
        "lit-verifier",
        "lit-critic",
        "lit-writer",
    }
    for p in (root / "pi" / "agents").glob("*.md"):
        head = p.read_text().split("---")[1]
        assert f"name: {p.stem}" in head and "description:" in head
    pkg = json.loads((root.parent / "package.json").read_text())
    assert pkg["pi"]["subagents"]["agents"] == ["./research/pi/agents"]
    for skill in pkg["pi"]["skills"]:
        assert (root.parent / skill / "SKILL.md").exists(), skill
    # every workflow the planner names exists
    src = (root / "src" / "rsx" / "plan.py").read_text()
    import re

    for script in set(re.findall(r'"script": "([^"]+)"', src)):
        assert (root / "pi" / "workflows" / script).exists(), script


def test_drive_stops_for_the_user_and_on_a_stall(lf, monkeypatch):
    from rsx import cli, plan

    monkeypatch.setenv("SHELL", "/bin/sh")
    r = lf.rsx("drive", "--pi", "exit 9 #")
    assert "protocol" in r.output  # human step: Pi is not started
    step = plan.Action("extract", "lit-reader", "Extract", "why")
    monkeypatch.setattr(cli.plan, "plan", lambda p, ctx=None: [step])
    r = lf.rsx("drive", "--pi", "true #", ok=False)
    assert "no progress in two rounds" in r.output
    assert len(list((lf.root / ".rsx" / "drive").glob("round-*.jsonl"))) == 2
    r = lf.rsx("drive", "--pi", "exit 9 #", ok=False)
    assert "pi exited 9" in r.output
    end = {
        "type": "agent_end",
        "messages": [{"stopReason": "error", "errorMessage": "Request timed out."}],
    }
    r = lf.rsx(
        "drive", "--pi", f"echo noise; echo {shlex.quote(json.dumps(end))} #", ok=False
    )
    assert "did not answer in round 1: Request timed out." in r.output


def test_review_refused_in_the_lead_pi_session(lf, monkeypatch):
    monkeypatch.setenv("PI_SESSION_ID", "lead-session")
    r = lf.rsx(
        "review", "Q-0001", "--ok", "--note", "x", "--by", "lit-critic", ok=False
    )
    assert "lit-critic's job" in r.output
