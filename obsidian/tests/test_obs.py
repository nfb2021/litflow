import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from obs import bib, pdftext
from obs.cli import app

FIXTURE = Path(__file__).parent / "fixtures" / "paper.pdf"
QUOTE = "Vegetation optical depth increases with canopy water content, as shown by our dual-receiver GNSS transmissometry"
BIB = r"""
@comment{ignored}
@article{doe2026gnsst,
  title = {{GNSS-T} ecohydrological monitoring in a beech forest},
  author = {Doe, Jane F. and M{\"u}ller, Anna},
  journal = {Remote Sensing of Environment},
  year = {2026},
  doi = {10.1016/J.RSE.2026.1},
  file = {PDFPATH}
}
@article{smith2020diurnal,
  title = "Diurnal {VOD} \& more",
  author = {Smith, John},
  journaltitle = {GRL}, date = {2020-05-01}
}
@inproceedings{lee2021,
  title = {Third},
  author = {Lee, A.},
  booktitle = {IGARSS},
  year = 2021
}
"""


@pytest.fixture
def obs(tmp_path, monkeypatch):
    """Run obs in a fresh vault; returns a function obs(*args) -> Result."""
    runner = CliRunner()
    root = tmp_path / "vault"
    monkeypatch.setenv("OBS_VAULT", str(root))

    def run(*args, ok=True):
        r = runner.invoke(app, [str(a) for a in args])
        if ok is not None:
            assert (r.exit_code == 0) == ok, r.output
        return r

    monkeypatch.delenv("OBS_VAULT")
    run("init", root)
    monkeypatch.setenv("OBS_VAULT", str(root))
    (tmp_path / "refs.bib").write_text(BIB.replace("PDFPATH", str(FIXTURE)))
    run("paper", "sync", tmp_path / "refs.bib")
    for key in ("doe2026gnsst", "smith2020diurnal", "lee2021"):
        run("paper", "screen", key, "--include", "--reason", "I1", "--by", "screener")
    run.root = root
    return run


def out(r):
    return r.stdout.strip()


# --- bib --------------------------------------------------------------------
def test_bib_fields():
    entries = bib.parse_bib(BIB.replace("PDFPATH", "/x/a.pdf"))
    assert [e["ID"] for e in entries] == [
        "doe2026gnsst",
        "smith2020diurnal",
        "lee2021",
    ]
    f = bib.paper_fields(entries[0])
    assert f["title"] == "GNSS-T ecohydrological monitoring in a beech forest"
    assert f["authors"] == ["Jane F. Doe", "Anna Müller"]
    assert f["doi"] == "10.1016/j.rse.2026.1"
    assert f["pdf"] == "/x/a.pdf"
    f = bib.paper_fields(entries[1])
    assert (
        f["title"] == "Diurnal VOD & more" and f["year"] == 2020 and f["venue"] == "GRL"
    )
    assert bib.paper_fields(entries[2])["venue"] == "IGARSS"


def test_bib_zotero_file_field():
    assert bib.pdf_files(
        "Full Text:/a/b c.pdf:application/pdf;Snapshot:/a/s.html:text/html"
    ) == ["/a/b c.pdf"]


# --- quote matching ---------------------------------------------------------
@pytest.mark.parametrize("backend", ["pdftotext", "pypdf"])
def test_find_quote_exact_page_and_approx(backend, monkeypatch):
    if backend == "pypdf":
        monkeypatch.setattr(pdftext.shutil, "which", lambda *a, **k: None)
    elif not pdftext.shutil.which("pdftotext"):
        pytest.skip("pdftotext not installed")
    pages = pdftext.pages(FIXTURE)
    assert pdftext.find_quote(QUOTE, pages) == {
        "status": "found",
        "page": 1,
        "score": 1.0,
    }
    r = pdftext.find_quote(
        "The diurnal cycle of VOD follows leaf water potential", pages
    )
    assert r["status"] == "found" and r["page"] == 2
    # one word changed: approximate, still located
    r = pdftext.find_quote(
        "Vegetation optical depth increases with canopy water content, as shown by the dual-receiver GNSS transmissometry",
        pages,
    )
    assert r["status"] == "approx" and r["page"] == 1
    assert (
        pdftext.find_quote(
            "VOD always follows leaf water potential exactly at noon", pages
        )["status"]
        == "not-found"
    )


def test_scan_without_text_layer():
    assert (
        pdftext.find_quote("any quote of reasonable length", ["", " ", "12"])["status"]
        == "no-text"
    )


def test_quote_with_lost_spaces():
    assert (
        pdftext.find_quote(
            "the number of looks per pixel is four",
            [
                "The numberof looks per pi xel is four. "
                + "Filler text with letters. " * 10
            ],
        )["status"]
        == "found"
    )


def test_normalize_hyphenation_and_ligatures():
    assert pdftext.normalize("trans-\nmissometry ﬁeld") == "transmissometry field"


# --- statements and claims --------------------------------------------------
def test_statement_duplicate_refused(obs):
    assert (
        out(obs("statement", "add", "VOD increases with canopy water content"))
        == "S-0001"
    )
    r = obs("statement", "add", "Canopy water content increases VOD", ok=False)
    assert "S-0001" in r.output
    assert (
        out(obs("statement", "add", "Canopy water content increases VOD", "--force"))
        == "S-0002"
    )


def test_claim_quote_checked(obs):
    obs("statement", "add", "VOD increases with canopy water content")
    r = obs(
        "claim",
        "add",
        "-p",
        "doe2026gnsst",
        "-s",
        "S-0001",
        "-q",
        QUOTE,
        "-r",
        "origin",
        "--by",
        "reader",
    )
    assert out(r) == "C-0001"
    c = json.loads(obs("show", "C-0001", "--json").stdout)["fm"]
    assert c["quote_check"] == "found" and c["page"] == "1"
    r = obs(
        "claim",
        "add",
        "-p",
        "doe2026gnsst",
        "-s",
        "S-0001",
        "-q",
        "A sentence that is not in the paper at all",
        "-r",
        "origin",
        "--by",
        "reader",
        ok=False,
    )
    assert "NOT found" in r.output
    assert not (obs.root / "claims" / "C-0002.md").exists()


def test_claim_rules(obs):
    obs("statement", "add", "VOD increases with canopy water content")
    r = obs(
        "claim",
        "add",
        "-p",
        "doe2026gnsst",
        "-s",
        "S-0001",
        "-q",
        QUOTE,
        "-r",
        "restates",
        "--by",
        "reader",
        ok=False,
    )
    assert "--cites" in r.output
    obs(
        "claim",
        "add",
        "-p",
        "nope",
        "-s",
        "S-0001",
        "-q",
        QUOTE,
        "-r",
        "origin",
        "--by",
        "reader",
        ok=False,
    )
    obs("paper", "screen", "lee2021", "--exclude", "--reason", "E1", "--by", "screener")
    r = obs(
        "claim",
        "add",
        "-p",
        "lee2021",
        "-s",
        "S-0001",
        "-q",
        "whatever text here",
        "-r",
        "origin",
        "--by",
        "reader",
        ok=False,
    )
    assert "excluded" in r.output


def test_verify_needs_another_agent(obs):
    obs("statement", "add", "VOD increases with canopy water content")
    obs(
        "claim",
        "add",
        "-p",
        "doe2026gnsst",
        "-s",
        "S-0001",
        "-q",
        QUOTE,
        "-r",
        "origin",
        "--by",
        "reader",
    )
    r = obs("verify", "C-0001", "--verified", "--by", "reader", "--note", "x", ok=False)
    assert "different agent" in r.output
    obs("verify", "C-0001", "--verified", "--by", "verifier", "--note", "p1")
    t = json.loads(obs("trace", "S-0001", "--json").stdout)
    assert t["verdict"] == "supported" and t["independent_sources"] == 1


def test_verify_refused_in_the_lead_pi_session(obs, monkeypatch):
    obs("statement", "add", "VOD increases with canopy water content")
    claim = ["claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", QUOTE]
    claim += ["-r", "origin", "--by", "lit-reader"]
    monkeypatch.setenv("PI_SESSION_ID", "lead-session")
    assert "lead's session" in obs(*claim, ok=False).output
    monkeypatch.delenv("PI_SESSION_ID")
    obs(*claim)
    monkeypatch.setenv("PI_SESSION_ID", "lead-session")
    verify = ["verify", "C-0001", "--verified", "--by", "lit-verifier", "--note", "p1"]
    assert "Delegate it" in obs(*verify, ok=False).output
    monkeypatch.setenv("PI_SUBAGENT_CHILD", "1")  # a background child
    obs(*verify)


def test_hand_edit_breaks_the_seal(obs):
    obs("statement", "add", "VOD increases with canopy water content")
    obs("statement", "add", "Something else entirely")
    obs(
        *["claim", "add", "-p", "doe2026gnsst", "-s", "S-0001", "-q", QUOTE],
        *["-r", "origin", "--by", "reader"],
    )
    obs("verify", "C-0001", "--verified", "--by", "verifier", "--note", "p1")
    assert json.loads(obs("lint", "--gate").stdout)["verdict"] == "pass"
    path = obs.root / "claims" / "C-0001.md"
    path.write_text(path.read_text().replace("[[S-0001]]", "[[S-0002]]"))
    g = json.loads(obs("lint", "--gate").stdout)
    assert [i["code"] for i in g["issues"] if i["level"] == "error"] == ["hand-edited"]
    obs("reseal", "C-0001", "--by", "lead")
    assert "verification: unverified" in path.read_text()
    assert json.loads(obs("lint", "--gate").stdout)["errors"] == 0


def test_hand_written_claim_has_no_seal(obs):
    obs("statement", "add", "VOD increases with canopy water content")
    (obs.root / "claims").mkdir(exist_ok=True)
    (obs.root / "claims" / "C-0009.md").write_text(
        "---\nid: C-0009\ntype: claim\nstatement: '[[S-0001]]'\n"
        "paper: '[[doe2026gnsst]]'\nrole: origin\nquote: x\npage: '1'\n"
        "verification: verified\nextracted_by: a\nverified_by: b\n---\n"
    )
    issues = json.loads(obs("lint", "--gate").stdout)["issues"]
    assert any(i["code"] == "hand-edited" and i["note"] == "C-0009" for i in issues)


# --- provenance ---------------------------------------------------------------
def _claim(obs, paper, st, role, *cites, quote=None):
    args = [
        "claim",
        "add",
        "-p",
        paper,
        "-s",
        st,
        "-q",
        quote or f"{paper} says it in some words",
        "-r",
        role,
        "--by",
        "reader",
        "--force",
    ]
    for c in cites:
        args += ["-c", c]
    return out(obs(*args))


def test_trace_chain_and_independence(obs):
    obs("statement", "add", "VOD diurnal cycle follows leaf water potential")
    c1 = _claim(
        obs,
        "doe2026gnsst",
        "S-0001",
        "restates",
        "smith2020diurnal",
        quote="The diurnal cycle of VOD follows leaf water potential",
    )
    t = json.loads(obs("trace", "S-0001", "--json").stdout)
    assert t["verdict"] == "unsupported"
    assert t["hops"] == [
        {
            "from": "doe2026gnsst",
            "claim": c1,
            "to": "smith2020diurnal",
            "status": "unchecked",
        }
    ]
    c2 = _claim(obs, "smith2020diurnal", "S-0001", "origin")
    obs("verify", c2, "--verified", "--by", "verifier", "--note", "fig 3")
    obs("verify", c1, "--verified", "--by", "verifier", "--note", "intro")
    t = json.loads(obs("trace", "S-0001", "--json").stdout)
    assert t["verdict"] == "supported"
    assert t["origins"] == ["smith2020diurnal"]
    assert t["independent_sources"] == 1  # repetition by doe adds no evidence
    assert t["hops"][0]["status"] == "ok"


def test_trace_cycle_missing_and_rejected(obs):
    obs("statement", "add", "Some proposition about forests")
    _claim(obs, "doe2026gnsst", "S-0001", "restates", "smith2020diurnal")
    _claim(obs, "smith2020diurnal", "S-0001", "restates", "doe2026gnsst")
    _claim(obs, "lee2021", "S-0001", "restates", "doi:10.1/xyz")
    t = json.loads(obs("trace", "S-0001", "--json").stdout)
    kinds = {p["kind"] for p in t["problems"]}
    assert {"circular-citation", "missing-paper"} <= kinds
    r = obs("lint", ok=False)
    assert "circular-citation" in r.stdout


def test_citation_does_not_support(obs):
    obs("statement", "add", "Some proposition about forests")
    _claim(obs, "doe2026gnsst", "S-0001", "restates", "smith2020diurnal")
    c = _claim(obs, "smith2020diurnal", "S-0001", "origin")
    obs(
        "verify",
        c,
        "--rejected",
        "--by",
        "verifier",
        "--note",
        "smith does not say this",
    )
    t = json.loads(obs("trace", "S-0001", "--json").stdout)
    assert t["hops"][0]["status"] == "not-in-cited"


# --- lint -------------------------------------------------------------------
def test_lint_gate_json(obs):
    r = obs("lint", "--gate")
    g = json.loads(r.stdout)
    assert g["verdict"] == "pass" and g["errors"] == 0
    obs("statement", "add", "Some proposition about forests")
    _claim(
        obs,
        "doe2026gnsst",
        "S-0001",
        "origin",
        quote="not in the pdf at all, really not",
    )
    g = json.loads(obs("lint", "--gate").stdout)
    assert g["verdict"] == "blocked"
    assert any(i["code"] == "quote-not-found" for i in g["issues"])


def test_rejected_claim_is_a_record_not_an_error(obs):
    obs("statement", "add", "Some proposition about forests")
    c = _claim(
        obs,
        "doe2026gnsst",
        "S-0001",
        "origin",
        quote="not in the pdf at all, really not",
    )
    obs("verify", c, "--rejected", "--by", "verifier", "--note", "not in the paper")
    assert json.loads(obs("lint", "--gate").stdout)["verdict"] == "pass"


def test_lint_broken_link_and_bad_yaml(obs):
    (obs.root / "statements" / "S-0009.md").write_text(
        "---\ntype: statement\nconcepts: ['[[ghost]]']\n---\nx\n"
    )
    (obs.root / "claims" / "C-0009.md").write_text("---\ntype: [unclosed\n---\n")
    r = obs("lint", "--json", ok=False)
    codes = {i["code"] for i in json.loads(r.stdout)["issues"]}
    assert {"broken-link", "unreadable"} <= codes


# --- wayfinder ----------------------------------------------------------------
def test_frontier_and_grilling_guard(obs):
    assert (
        out(obs("map", "new", "VOD review", "-d", "A protocol for the review"))
        == "M-0001"
    )
    q1 = out(
        obs(
            "q",
            "add",
            "M-0001",
            "Which frequency bands are in scope?",
            "-k",
            "grilling",
        )
    )
    q2 = out(
        obs(
            "q",
            "add",
            "M-0001",
            "Which L-band GNSS-T studies exist?",
            "-k",
            "research",
            "-b",
            q1,
        )
    )
    assert [q["id"] for q in json.loads(obs("frontier", "--json").stdout)] == [q1]
    r = obs("q", "answer", q1, "--gist", "L-band only", "--by", "planner", ok=False)
    assert "only the user" in r.output
    obs(
        "q",
        "answer",
        q1,
        "--gist",
        "L-band only",
        "--human-said",
        "Only L-band, GNSS and SMAP/SMOS.",
        "--by",
        "planner",
    )
    assert [q["id"] for q in json.loads(obs("frontier", "--json").stdout)] == [q2]
    # research answers need evidence
    obs("q", "claim", q2, "--by", "scout")
    obs("q", "claim", q2, "--by", "scout2", ok=False)
    obs("q", "answer", q2, "--gist", "three studies", "--by", "scout", ok=False)
    obs("statement", "add", "Some proposition about forests")
    obs(
        "q",
        "answer",
        q2,
        "--gist",
        "three studies",
        "--statement",
        "S-0001",
        "--by",
        "scout",
    )
    shown = out(obs("map", "show", "M-0001"))
    assert "Destination: A protocol for the review" in shown
    body = (obs.root / "maps" / "M-0001.md").read_text()
    assert "L-band only" in body and "three studies" in body
    obs("lint")


def test_drop_needs_reason_and_unblocks(obs):
    obs("map", "new", "m", "-d", "d")
    q1 = out(obs("q", "add", "M-0001", "Do we need C-band?", "-k", "research"))
    q2 = out(obs("q", "add", "M-0001", "Then what?", "-k", "task", "-b", q1))
    obs("q", "drop", q1, "--reason", "beyond the L-band destination")
    assert [q["id"] for q in json.loads(obs("frontier", "--json").stdout)] == [q2]
    assert "beyond the L-band" in (obs.root / "maps" / "M-0001.md").read_text()


# --- query --------------------------------------------------------------------
def test_ls_filters_sql_neighbors(obs):
    assert out(obs("ls", "paper", "year>2020")).count("\n") == 1  # bader, lee
    assert "smith2020diurnal" in out(obs("ls", "paper", "venue~grl"))
    obs("statement", "add", "VOD increases with canopy water content")
    obs(
        "claim",
        "add",
        "-p",
        "doe2026gnsst",
        "-s",
        "S-0001",
        "-q",
        QUOTE,
        "-r",
        "origin",
        "--by",
        "reader",
    )
    rows = json.loads(
        obs("sql", "select src, dst from links where field='paper'", "--json").stdout
    )
    assert rows == [{"src": "C-0001", "dst": "doe2026gnsst"}]
    obs("sql", "delete from notes", ok=False)
    nb = json.loads(obs("neighbors", "S-0001", "--json").stdout)
    assert {"dir": "<-", "field": "statement", "note": "C-0001"} in nb["S-0001"]


def test_glossary_and_decision(obs):
    obs(
        "term",
        "add",
        "Vegetation optical depth",
        "-d",
        "Attenuation of microwaves by the canopy, nepers",
        "--alias",
        "VOD",
        "--alias",
        "tau",
    )
    assert "aka VOD, tau" in out(obs("glossary"))
    assert (
        out(
            obs(
                "decision",
                "Exclude preprints",
                "--decision",
                "no preprints",
                "--context",
                "rigour",
                "--alternatives",
                "allow arXiv",
                "--by",
                "human",
            )
        )
        == "D-0001"
    )


def test_no_vault(tmp_path, monkeypatch):
    monkeypatch.delenv("OBS_VAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["status"])
    assert r.exit_code == 1 and "obs init" in r.output


def test_vault_found_through_litflow_project(tmp_path, monkeypatch):
    from obs.vault import find_root

    monkeypatch.delenv("OBS_VAULT", raising=False)
    runner = CliRunner()
    assert runner.invoke(app, ["init", str(tmp_path / "notes")]).exit_code == 0
    (tmp_path / "rsx.toml").write_text('title = "x"\nvault = "notes"\n')
    (tmp_path / "paper").mkdir()
    assert find_root(tmp_path / "paper") == (tmp_path / "notes").resolve()
    (tmp_path / "rsx.toml").write_text('vault = "elsewhere"\n')
    with pytest.raises(Exception, match="no vault found"):
        find_root(tmp_path / "paper")
