"""Tests for analysis.on_this_day match selection (pure, offline)."""
from analysis import on_this_day as otd


def _m(headline, idx, score):
    return {"headline": headline, "article_idx": idx, "score": score}


def test_deep_dive_is_global_best():
    matches = [_m("a", 0, 0.40), _m("b", 1, 0.72), _m("c", 2, 0.60)]
    out = otd.select_matches(matches)
    assert out["deep_dive"]["headline"] == "b"
    assert out["deep_dive"]["article_idx"] == 1


def test_roundup_excludes_deep_dive_article_and_applies_threshold():
    matches = [_m("top", 1, 0.72), _m("ok", 2, 0.60), _m("weak", 3, 0.40)]
    out = otd.select_matches(matches, threshold=0.55, cap=6)
    ids = [r["headline"] for r in out["roundup"]]
    assert "top" not in ids          # the deep-dive is not repeated
    assert "ok" in ids               # 0.60 >= 0.55
    assert "weak" not in ids         # 0.40 < 0.55


def test_roundup_sorted_desc_and_capped():
    matches = [_m("dd", 0, 0.99)] + [_m(f"h{i}", i + 1, 0.60 + i * 0.01) for i in range(8)]
    out = otd.select_matches(matches, threshold=0.55, cap=6)
    scores = [r["score"] for r in out["roundup"]]
    assert scores == sorted(scores, reverse=True)
    assert len(out["roundup"]) == 6


def test_roundup_dedups_same_article_keeping_stronger():
    # two headlines map to the same article (idx 2); only the stronger survives
    matches = [_m("dd", 0, 0.90), _m("strong", 2, 0.70), _m("weak", 2, 0.58)]
    out = otd.select_matches(matches, threshold=0.55, cap=6)
    arts = [r["article_idx"] for r in out["roundup"]]
    assert arts.count(2) == 1
    assert any(r["headline"] == "strong" for r in out["roundup"])
    assert not any(r["headline"] == "weak" for r in out["roundup"])


def test_empty_and_single():
    assert otd.select_matches([]) == {"deep_dive": None, "roundup": []}
    single = otd.select_matches([_m("only", 0, 0.80)])
    assert single["deep_dive"]["headline"] == "only"
    assert single["roundup"] == []


def test_no_qualifiers_gives_empty_roundup():
    matches = [_m("dd", 0, 0.90), _m("a", 1, 0.40), _m("b", 2, 0.30)]
    out = otd.select_matches(matches, threshold=0.55)
    assert out["deep_dive"]["headline"] == "dd"
    assert out["roundup"] == []


def test_render_roundup_empty_is_blank():
    assert otd._render_roundup([]) == ""


def test_render_roundup_includes_headline_blurb_and_citation():
    items = [{
        "headline": "Markets wobble on Fed signals",
        "blurb": "I warned the Fed had become a market backstop.",
        "title": "The Fed's Quiet Backstop",
        "url": "https://example.com/fed",
        "year": "2021",
    }]
    html = otd._render_roundup(items)
    assert "In His Words" in html              # section header present
    assert "Markets wobble on Fed signals" in html
    assert "I warned the Fed had become a market backstop." in html
    assert 'href="https://example.com/fed"' in html
    assert "The Fed's Quiet Backstop" in html
    assert "2021" in html


def test_render_roundup_escapes_html():
    items = [{"headline": "Tech & Trade <war>", "blurb": "b",
              "title": "t", "url": "#", "year": "2020"}]
    html = otd._render_roundup(items)
    assert "Tech &amp; Trade &lt;war&gt;" in html
    assert "<war>" not in html
