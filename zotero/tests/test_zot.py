from zotero import cli, refs

WORK = {
    "title": ["Vegetation modeled as a <i>water</i> cloud"],
    "issued": {"date-parts": [[1978, 3]]},
}


class FakeZotero:
    """The library: one item without a DOI, as when a PDF was added by hand"""

    def __init__(self, doi=""):
        self.doi = doi
        self.calls = []

    def call(self, tool, /, **args):
        self.calls.append((tool, args))
        if tool == "search_library":
            return {
                "results": [
                    {"key": "AAAA1111", "title": "Something else", "date": "1978"},
                    {
                        "key": "BBBB2222",
                        "title": "Vegetation modeled as a water cloud.",
                        "date": "03/1978",
                    },
                ]
            }
        if tool == "get_item_details":
            return {"key": args["itemKey"], "DOI": self.doi}
        return {}


def test_title_key_ignores_case_punctuation_and_markup():
    assert refs.title_key("<i>Humulus</i> lupulus: a review.") == refs.title_key(
        "Humulus Lupulus - A Review"
    )


def test_doi_of_an_item_without_doi_is_filed_not_imported(monkeypatch):
    monkeypatch.setattr(refs, "crossref_work", lambda doi: WORK)
    zot = FakeZotero()
    rows = cli._file_title_matches(
        zot, ["https://doi.org/10.1029/RS013i002p00357"], {"key": "COLL0001"}, False
    )
    assert [(r["status"], r["item"]["itemKey"]) for r in rows] == [
        ("exists", "BBBB2222")
    ]
    tools = {tool: args for tool, args in zot.calls}
    assert tools["add_items_to_collection"]["itemKeys"] == ["BBBB2222"]
    assert tools["write_metadata"]["fields"] == {"DOI": "10.1029/rs013i002p00357"}


def test_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(refs, "crossref_work", lambda doi: WORK)
    zot = FakeZotero()
    assert cli._file_title_matches(zot, ["10.1029/abc"], {"key": "COLL0001"}, True)
    assert {t for t, _ in zot.calls} == {"search_library", "get_item_details"}


def test_no_match_when_the_item_has_a_doi_or_another_year(monkeypatch):
    monkeypatch.setattr(refs, "crossref_work", lambda doi: WORK)
    # an item with a DOI is a different paper, or Zotero's own DOI check finds it
    assert not cli._file_title_matches(
        FakeZotero("10.1029/other"), ["10.1029/abc"], None, False
    )
    later = {**WORK, "issued": {"date-parts": [[2001]]}}
    monkeypatch.setattr(refs, "crossref_work", lambda doi: later)
    assert not cli._file_title_matches(FakeZotero(), ["10.1029/abc"], None, False)


def test_short_or_unknown_titles_are_not_matched(monkeypatch):
    monkeypatch.setattr(refs, "crossref_work", lambda doi: {"title": ["Editorial"]})
    assert not cli._file_title_matches(FakeZotero(), ["10.1029/abc"], None, False)
    monkeypatch.setattr(refs, "crossref_work", lambda doi: {})
    assert not cli._file_title_matches(FakeZotero(), ["10.1029/abc"], None, False)
