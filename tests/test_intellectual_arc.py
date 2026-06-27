"""Tests for analysis.intellectual_arc — year-over-year theme evolution (roadmap #13).

Pure/offline: every helper operates on an in-memory ``themes.json``-shaped dict, so
these tests make no conductor calls and touch no disk.
"""

import json

import pytest

from analysis import intellectual_arc as arc


@pytest.fixture
def themes() -> dict:
    """A small synthetic themes.json: 3 clusters across 2020-2021.

    2020 is Tesla/markets-dominant; 2021 sees Crypto emerge and Fed grow while
    Tesla vanishes. One article has a blank date and must be ignored.
    """
    return {
        "num_clusters": 3,
        "clusters": [
            {"id": 0, "label": "Crypto / Bitcoin / Blockchain"},
            {"id": 1, "label": "Fed / Inflation / Rates"},
            {"id": 2, "label": "Tesla / Stocks / Markets"},
        ],
        "articles": [
            {"slug": "a", "date": "2020-01-01", "cluster_id": 2,
             "cluster_label": "Tesla / Stocks / Markets"},
            {"slug": "b", "date": "2020-06-01", "cluster_id": 2,
             "cluster_label": "Tesla / Stocks / Markets"},
            {"slug": "c", "date": "2020-09-01", "cluster_id": 1,
             "cluster_label": "Fed / Inflation / Rates"},
            {"slug": "d", "date": "2021-02-01", "cluster_id": 0,
             "cluster_label": "Crypto / Bitcoin / Blockchain"},
            {"slug": "e", "date": "2021-03-01", "cluster_id": 0,
             "cluster_label": "Crypto / Bitcoin / Blockchain"},
            {"slug": "f", "date": "2021-07-01", "cluster_id": 1,
             "cluster_label": "Fed / Inflation / Rates"},
            {"slug": "g", "date": "2021-08-01", "cluster_id": 1,
             "cluster_label": "Fed / Inflation / Rates"},
            {"slug": "x", "date": "", "cluster_id": 2,
             "cluster_label": "Tesla / Stocks / Markets"},
        ],
    }


# --- arc_by_year -----------------------------------------------------------

def test_arc_by_year_bins_and_counts(themes):
    by_year = arc.arc_by_year(themes)
    years = [y["year"] for y in by_year]
    assert years == ["2020", "2021"]  # sorted, blank-date article dropped

    y2020 = by_year[0]
    assert y2020["total"] == 3
    # dominant theme is the most frequent cluster that year
    assert y2020["dominant"]["cluster_id"] == 2
    assert y2020["dominant"]["count"] == 2
    assert y2020["dominant"]["share"] == pytest.approx(0.667, abs=0.001)


def test_arc_by_year_themes_sorted_desc_with_id_tiebreak(themes):
    y2021 = arc.arc_by_year(themes)[1]
    assert y2021["total"] == 4
    # clusters 0 and 1 both have 2 articles -> tie broken by lower cluster_id first
    ids = [t["cluster_id"] for t in y2021["themes"]]
    assert ids[:2] == [0, 1]
    assert y2021["dominant"]["cluster_id"] == 0
    assert all(t["share"] == pytest.approx(0.5) for t in y2021["themes"][:2])


def test_arc_by_year_uses_cluster_labels(themes):
    y2020 = arc.arc_by_year(themes)[0]
    assert y2020["dominant"]["label"] == "Tesla / Stocks / Markets"


# --- year_over_year_shifts -------------------------------------------------

def test_shifts_identify_rising_fading_emergent_vanished(themes):
    by_year = arc.arc_by_year(themes)
    shifts = arc.year_over_year_shifts(by_year)
    assert len(shifts) == 1
    s = shifts[0]
    assert s["from_year"] == "2020"
    assert s["to_year"] == "2021"

    rising_ids = [r["cluster_id"] for r in s["rising"]]
    assert rising_ids[0] == 0  # crypto rose the most

    fading_ids = [f["cluster_id"] for f in s["fading"]]
    assert 2 in fading_ids  # tesla faded

    emergent_ids = [e["cluster_id"] for e in s["emergent"]]
    assert emergent_ids == [0]  # crypto: 0% -> present

    vanished_ids = [v["cluster_id"] for v in s["vanished"]]
    assert vanished_ids == [2]  # tesla: present -> 0%


def test_shifts_dominant_change(themes):
    by_year = arc.arc_by_year(themes)
    s = arc.year_over_year_shifts(by_year)[0]
    assert s["dominant_change"]["from"]["cluster_id"] == 2
    assert s["dominant_change"]["to"]["cluster_id"] == 0


def test_shifts_empty_for_single_year():
    one_year = {
        "clusters": [{"id": 0, "label": "Solo"}],
        "articles": [{"slug": "a", "date": "2022-01-01", "cluster_id": 0,
                      "cluster_label": "Solo"}],
    }
    by_year = arc.arc_by_year(one_year)
    assert arc.year_over_year_shifts(by_year) == []


# --- overall_arc -----------------------------------------------------------

def test_overall_arc_most_grown_and_declined(themes):
    by_year = arc.arc_by_year(themes)
    overall = arc.overall_arc(by_year)
    assert overall["span"] == "2020–2021"
    assert overall["n_years"] == 2
    assert overall["n_articles"] == 7
    assert overall["most_grown"]["cluster_id"] == 0
    assert overall["most_declined"]["cluster_id"] == 2
    assert overall["first_dominant"]["cluster_id"] == 2
    assert overall["last_dominant"]["cluster_id"] == 0


def test_overall_arc_none_when_empty():
    assert arc.overall_arc([]) is None


# --- render_narrative ------------------------------------------------------

def test_render_narrative_mentions_span_and_key_themes(themes):
    by_year = arc.arc_by_year(themes)
    shifts = arc.year_over_year_shifts(by_year)
    overall = arc.overall_arc(by_year)
    text = arc.render_narrative(by_year, shifts, overall)
    assert isinstance(text, str) and text
    assert "2020–2021" in text
    assert "Tesla / Stocks / Markets" in text  # first dominant
    assert "Crypto / Bitcoin / Blockchain" in text  # last dominant / most grown


def test_render_narrative_handles_empty():
    text = arc.render_narrative([], [], None)
    assert isinstance(text, str) and text  # graceful, non-empty


# --- partial (low-volume) years -------------------------------------------

@pytest.fixture
def themes_partial_final() -> dict:
    """Two full years (2020, 2021) plus a thin partial 2022 (1 piece)."""
    arts = [
        {"slug": "a", "date": "2020-01-01", "cluster_id": 2, "cluster_label": "Markets"},
        {"slug": "b", "date": "2020-06-01", "cluster_id": 2, "cluster_label": "Markets"},
        {"slug": "c", "date": "2020-09-01", "cluster_id": 1, "cluster_label": "Fed"},
        {"slug": "d", "date": "2021-02-01", "cluster_id": 0, "cluster_label": "Crypto"},
        {"slug": "e", "date": "2021-03-01", "cluster_id": 0, "cluster_label": "Crypto"},
        {"slug": "f", "date": "2021-07-01", "cluster_id": 1, "cluster_label": "Fed"},
        {"slug": "g", "date": "2021-08-01", "cluster_id": 1, "cluster_label": "Fed"},
        {"slug": "h", "date": "2022-01-15", "cluster_id": 0, "cluster_label": "Crypto"},
    ]
    return {
        "clusters": [
            {"id": 0, "label": "Crypto"},
            {"id": 1, "label": "Fed"},
            {"id": 2, "label": "Markets"},
        ],
        "articles": arts,
    }


def test_partial_year_is_flagged(themes_partial_final):
    by_year = arc.arc_by_year(themes_partial_final)
    flags = {y["year"]: y["partial"] for y in by_year}
    assert flags == {"2020": False, "2021": False, "2022": True}


def test_overall_uses_last_full_year_for_summary(themes_partial_final):
    by_year = arc.arc_by_year(themes_partial_final)
    overall = arc.overall_arc(by_year)
    # arc summary spans only the full years; the thin 2022 is excluded from the endpoint
    assert overall["span"] == "2020–2021"
    assert overall["last_year"] == "2021"
    assert overall["partial_final_year"] is True
    assert overall["final_year"]["year"] == "2022"
    # but every year (incl. the partial one) is still reported in by_year + the totals
    assert overall["n_years"] == 3
    assert overall["n_articles"] == 8


def test_narrative_caveats_partial_year(themes_partial_final):
    by_year = arc.arc_by_year(themes_partial_final)
    overall = arc.overall_arc(by_year)
    text = arc.render_narrative(by_year, arc.year_over_year_shifts(by_year), overall)
    assert "So far in 2022" in text


# --- build_arc / run -------------------------------------------------------

def test_build_arc_assembles_full_document(themes):
    doc = arc.build_arc(themes)
    assert set(doc) >= {"generated", "overall", "by_year", "shifts", "narrative"}
    assert doc["overall"]["n_articles"] == 7
    assert len(doc["by_year"]) == 2
    assert doc["narrative"]


def test_build_arc_empty_corpus_is_safe():
    doc = arc.build_arc({"clusters": [], "articles": []})
    assert doc["by_year"] == []
    assert doc["overall"] is None
    assert doc["narrative"]  # still a string


def test_missing_cluster_label_falls_back_to_id():
    themes = {
        "clusters": [],  # no label map
        "articles": [{"slug": "a", "date": "2020-01-01", "cluster_id": 7,
                      "cluster_label": ""}],
    }
    y = arc.arc_by_year(themes)[0]
    assert y["dominant"]["label"] == "Cluster 7"


def test_run_writes_json(tmp_path, monkeypatch, themes):
    themes_path = tmp_path / "themes.json"
    themes_path.write_text(json.dumps(themes))
    out_path = tmp_path / "intellectual_arc.json"
    monkeypatch.setattr(arc, "THEMES_PATH", themes_path)
    monkeypatch.setattr(arc, "REPORT_PATH", out_path)

    result = arc.run()
    assert out_path.exists()
    on_disk = json.loads(out_path.read_text())
    assert on_disk["overall"]["n_articles"] == 7
    assert result["overall"]["n_articles"] == 7


def test_run_dry_run_writes_nothing(tmp_path, monkeypatch, themes):
    themes_path = tmp_path / "themes.json"
    themes_path.write_text(json.dumps(themes))
    out_path = tmp_path / "intellectual_arc.json"
    monkeypatch.setattr(arc, "THEMES_PATH", themes_path)
    monkeypatch.setattr(arc, "REPORT_PATH", out_path)

    arc.run(dry_run=True)
    assert not out_path.exists()
