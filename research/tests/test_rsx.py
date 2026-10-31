import json
import shlex
import shutil
from pathlib import Path

import pytest
from obs.cli import app as obs_app
from typer.testing import CliRunner

from rsx import cite, gates, notebook
from rsx import project as proj
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
    LF.rsx("notebook", "use", "none")  # the notebook has its own test
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
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader", ok=False)  # unsearched
    lf.rsx(
        "searched", "doe2026gnsst", "Q-0001", "--found", "C-0001", "--by", "lit-reader"
    )
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
        "--finding",
        "line 18: add the site -> name it",
        "-f",
        "line 20: no citation -> cite C-0001",
        "--by",
        "lit-critic",
    )
    review_md = sorted((lf.root / "reviews").glob("*-review.md"))[-1].read_text()
    assert "line 18: add the site -> name it\nline 20: no citation" in review_md
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


def test_each_paper_is_searched_for_each_question(lf):
    fill_protocol(lf.root)
    lf.rsx("protocol", "--settle")
    lf.obs("map", "new", "VOD and water", "-d", "evidence")
    lf.obs("q", "add", "M-0001", "Does VOD rise with canopy water?", "-k", "research")
    lf.obs("q", "add", "M-0001", "Does VOD depend on frequency?", "-k", "research")
    lf.obs("paper", "sync", "refs.bib")
    for key in ("doe2026gnsst", "roe2019review"):
        lf.obs("paper", "screen", key, "--include", "--reason", "I1: x", "--by", "lit-reader")  # fmt: skip
    lf.rsx("unavailable", "roe2019review", "--reason", "paywalled", "--by", "lit-scout")
    lf.obs("statement", "add", "VOD increases with canopy water content")
    lf.obs(
        "claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", QUOTE,
        "-r", "origin", "--by", "lit-reader",
    )  # fmt: skip
    a = nxt(lf)
    assert (
        a["stage"] == "extract"
        and "# Q-0002: Does VOD depend on frequency?" in a["commands"]
    )
    lf.rsx(
        "searched", "doe2026gnsst", "Q-0001", "--found", "C-0001", "--by", "lit-reader"
    )
    issues = gate(lf, "extract", "--paper", "doe2026gnsst")["issues"]
    assert any("not searched for Q-0002" in i for i in issues)
    lf.rsx(
        "searched", "doe2026gnsst", "Q-0002", "--none", "--by", "lit-reader", ok=False
    )  # no note
    lf.rsx("searched", "doe2026gnsst", "Q-0002", "--found", "C-9999", "--by", "lit-reader", ok=False)  # fmt: skip
    lf.rsx("searched", "doe2026gnsst", "Q-0002", "--none", "--note", "grep frequency, GHz: no hits", "--by", "lit-reader")  # fmt: skip
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader")

    # the 'nothing found' record waits for a second agent, like a claim
    a = nxt(lf)
    assert a["stage"] == "verify" and "'not in this paper'" in a["title"]
    lf.obs("verify", "C-0001", "--verified", "--by", "lit-verifier", "--note", "p1")
    assert gate(lf, "verify")["verdict"] == "blocked"
    lf.rsx("confirm-none", "doe2026gnsst", "Q-0002", "--note", "x", "--by", "lit-reader", ok=False)  # fmt: skip
    lf.rsx("confirm-none", "doe2026gnsst", "Q-0002", "--dispute", "--note", "p1 names L-band", "--by", "lit-verifier")  # fmt: skip
    a = nxt(lf)
    assert a["stage"] == "extract"  # back to the reader
    assert "p1 names L-band" in lf.obs("show", "doe2026gnsst").stdout
    lf.rsx("searched", "doe2026gnsst", "Q-0002", "--none", "--note", "read p1 again", "--by", "lit-reader")  # fmt: skip
    lf.rsx("confirm-none", "doe2026gnsst", "Q-0002", "--note", "grep band, GHz", "--by", "lit-verifier")  # fmt: skip
    assert gate(lf, "verify")["verdict"] == "pass"
    assert nxt(lf)["stage"] == "answer"
    cov = json.loads(lf.rsx("coverage", "--json").stdout)
    assert cov == {
        "Q-0001": {"doe2026gnsst": "found C-0001"},
        "Q-0002": {"doe2026gnsst": "none (confirmed)"},
    }

    # a search whose claims were all rejected counts as not done
    lf.obs(
        "verify",
        "C-0001",
        "--rejected",
        "--by",
        "lit-verifier",
        "--note",
        "other topic",
    )
    issues = gate(lf, "extract", "--paper", "doe2026gnsst")["issues"]
    assert any("every claim found for Q-0001 was rejected" in i for i in issues)

    # search records are sealed: a hand edit is a lint error
    note = lf.root / "vault" / "papers" / "doe2026gnsst.md"
    note.write_text(
        note.read_text().replace(
            "confirmed_by: lit-verifier", "confirmed_by: lit-critic"
        )
    )
    assert any(
        i["code"] == "hand-edited"
        for i in json.loads(lf.obs("lint", "--json", ok=None).stdout)["issues"]
    )
    lf.obs("reseal", "doe2026gnsst", "--by", "lead")  # drops the search records
    assert gate(lf, "vault")["verdict"] == "pass"
    issues = gate(lf, "extract", "--paper", "doe2026gnsst")["issues"]
    assert any("not searched for Q-0002" in i for i in issues)


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
    lf.rsx(
        "searched", "doe2026gnsst", "Q-0001", "--found", "C-0001", "--by", "lit-reader"
    )
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
    lf.rsx(
        "searched", "doe2026gnsst", "Q-0001", "--found", "C-0001", "--by", "lit-reader"
    )
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader")
    lf.rsx("searched", "roe2019review", "Q-0001", "--none", "--note", "grep VOD: no hits", "--by", "lit-reader")  # fmt: skip
    lf.rsx("confirm-none", "roe2019review", "Q-0001", "--note", "grep VOD, water", "--by", "lit-verifier")  # fmt: skip
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


# --- the notebook finds, the PDF judges ------------------------------------------
FAKE_GNB = """#!/bin/sh
if [ "$1" = add ]; then echo "$@" >> "{log}"; exit 0; fi
cat "{answer}"
"""
SENTENCE = (
    "Vegetation optical depth increases with canopy water content, as shown by our "
    "dual-receiver GNSS transmissometry experiment over a full growing season in a beech forest."
)


def test_quotes_are_split_and_cleaned():
    answer = (
        'Doe writes "VOD increases with canopy water content [1, 2] ... over a full growing season" '
        "and \u201ca short one\u201d and \u201eein deutsches Zitat aus dem Aufsatz\u201c."
    )
    assert notebook.quotes(answer) == [
        "VOD increases with canopy water content",
        "over a full growing season",
        "ein deutsches Zitat aus dem Aufsatz",
    ]
    diurnal = "The diurnal cycle of VOD follows leaf water potential, with a minimum in the early afternoon."
    page = f"Canopy transmissivity\n{SENTENCE}\n\nDiurnal cycle\n{diurnal}"
    found = notebook.anchor(
        [
            "vegetation optical depth increases with canopy water content",
            "The diurnal cycle of VOD tracks the leaf water status, with a minimum around noon",
            "Der Tagesgang der VOD folgt dem Blattwasserpotential",
        ],
        {"doe": [page]},
    )
    # the page's own words, heading left out: ready for `obs claim add`
    first, second = found["leads"]["doe"]
    assert (first["status"], first["text"]) == ("found", SENTENCE)
    assert (second["status"], second["text"]) == ("weak", diurnal)
    assert found["unanchored"] == [
        "Der Tagesgang der VOD folgt dem Blattwasserpotential"
    ]


def test_the_notebook_finds_and_the_pdf_judges(lf, tmp_path, monkeypatch):
    log, answer = tmp_path / "gnb.log", tmp_path / "answer.json"
    fake = tmp_path / "gnb"
    fake.write_text(FAKE_GNB.format(log=log, answer=answer))
    fake.chmod(0o755)
    monkeypatch.setenv("RSX_GNB", str(fake))

    def says(text):
        answer.write_text(json.dumps({"answer": text}))

    fill_protocol(lf.root)
    lf.rsx("protocol", "--settle")
    lf.obs("map", "new", "VOD and water", "-d", "evidence")
    lf.obs("q", "add", "M-0001", "Does VOD rise with canopy water?", "-k", "research")
    lf.obs("q", "add", "M-0001", "Does VOD have a diurnal cycle?", "-k", "research")
    lf.obs("paper", "sync", "refs.bib")
    for key in ("doe2026gnsst", "roe2019review"):
        lf.obs("paper", "screen", key, "--include", "--reason", "I1: x", "--by", "lit-reader")  # fmt: skip
    lf.rsx("unavailable", "roe2019review", "--reason", "paywalled", "--by", "lit-scout")

    # the user decides: a notebook, or local PDFs only
    proj.set_key(proj.load(lf.root), "notebook", "")
    a = nxt(lf)
    assert (a["stage"], a["role"]) == ("notebook", "human")
    assert gate(lf, "notebook")["verdict"] == "blocked"
    lf.rsx("notebook", "use", "https://notebook.google.com/notebook/test")
    lf.rsx("ask", ok=False)  # nothing in the notebook yet
    a = nxt(lf)
    assert a["role"] == "lead" and a["commands"] == ["rsx notebook push"]
    lf.rsx("notebook", "push")
    assert str(FIXTURE) in log.read_text()
    assert "every included PDF" in lf.rsx("notebook", "push").output
    a = nxt(lf)
    assert a["stage"] == "notebook" and a["items"] == ["Q-0001", "Q-0002"]

    # one query per question; quotes become leads, silence becomes a 'none'
    says(
        'Doe (2026): "vegetation optical depth increases with the canopy water content [1]". '
        'Roe: "VOD peaks at noon in all tropical forests of the world [2]".'
    )
    r = lf.rsx("ask", "Q-0001")
    assert "1 lead(s) in 1 paper(s); 1 quote(s) in no PDF" in r.output
    says("None of the sources addresses a diurnal cycle.")
    r = lf.rsx("ask")  # the questions not asked yet: Q-0002
    assert "nothing quoted from: doe2026gnsst" in r.output
    assert gate(lf, "notebook")["verdict"] == "pass"
    rec = json.loads((lf.root / ".rsx/notebook/Q-0001.json").read_text())
    assert rec["leads"]["doe2026gnsst"][0]["text"] == SENTENCE

    a = nxt(lf)
    assert a["stage"] == "extract" and "rsx leads doe2026gnsst" in a["commands"][2]
    r = lf.rsx("leads", "doe2026gnsst")
    assert f'p. 1 (found): "{SENTENCE}"' in r.output
    assert "in no PDF (translated or paraphrased?)" in r.output
    assert "the notebook quoted nothing from this paper" in r.output
    # the lead is copied from the page, so its quote is found as is
    lf.obs("statement", "add", "VOD increases with canopy water content")
    lf.obs(
        "claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", SENTENCE,
        "-r", "origin", "--by", "lit-reader",
    )  # fmt: skip
    lf.rsx("searched", "doe2026gnsst", "Q-0001", "--found", "C-0001", "--by", "lit-reader")  # fmt: skip
    lf.rsx("extracted", "doe2026gnsst", "--by", "lit-reader")

    # the notebook's 'none' is checked by searching the PDF itself
    a = nxt(lf)
    assert a["stage"] == "verify" and "1 'not in this paper' record(s)" in a["title"]
    lf.obs("verify", "C-0001", "--verified", "--by", "lit-verifier", "--note", "p1")
    lf.rsx("confirm-none", "doe2026gnsst", "Q-0002", "--note", "grep diurnal: no hits", "--by", "lit-verifier")  # fmt: skip
    cov = json.loads(lf.rsx("coverage", "--json").stdout)
    assert cov["Q-0002"]["doe2026gnsst"] == "none (confirmed)"

    # asked again and quoted after all: the 'none' goes, the reader reads it
    says('Doe: "The diurnal cycle of VOD follows leaf water potential [1]".')
    lf.rsx("ask", "Q-0002")
    cov = json.loads(lf.rsx("coverage", "--json").stdout)
    assert cov["Q-0002"]["doe2026gnsst"] == "unsearched"
    assert nxt(lf)["stage"] == "extract"

    # a new question is asked; the old ones are not asked again
    lf.obs("q", "add", "M-0001", "Does VOD depend on frequency?", "-k", "research")
    a = nxt(lf)
    assert a["stage"] == "notebook" and a["items"] == ["Q-0003"]
