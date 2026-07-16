"""Tests for analysis.contradictions — the mind-change / contradiction finder (roadmap #15).

Offline and deterministic: every test feeds small hand-built fixtures (corpus article dicts +
the shape of `entities.json`) to the pure helpers. No corpus, no network, no model calls.
"""

from analysis import contradictions as c

# --- stance_score -----------------------------------------------------------

def test_stance_score_positive():
    assert c.stance_score("The plan is a brilliant success.") > 0


def test_stance_score_negative():
    assert c.stance_score("The plan is a reckless failure.") < 0


def test_stance_score_neutral_is_zero():
    assert c.stance_score("The meeting is scheduled for Tuesday.") == 0


def test_stance_score_nets_mixed_signals():
    # one positive ("strong") and one negative ("crisis") net to zero
    assert c.stance_score("A strong response to the crisis.") == 0


def test_stance_score_matches_on_word_boundaries():
    # "strongman" must not count as the positive word "strong"
    assert c.stance_score("The strongman tightened his grip.") == 0


# --- mentions ---------------------------------------------------------------

def test_mentions_case_insensitive():
    assert c.mentions("the fed raised rates", "Fed") is True


def test_mentions_absent():
    assert c.mentions("Bitcoin rallied hard", "Fed") is False


def test_mentions_whole_phrase():
    assert c.mentions("Jerome Powell spoke today", "Jerome Powell") is True
    assert c.mentions("Powell spoke today", "Jerome Powell") is False


# --- split_observations -----------------------------------------------------

def test_split_observations_even():
    obs = [{"date": f"2020-0{i}-01"} for i in range(1, 5)]
    early, late = c.split_observations(obs)
    assert [o["date"] for o in early] == ["2020-01-01", "2020-02-01"]
    assert [o["date"] for o in late] == ["2020-03-01", "2020-04-01"]


def test_split_observations_odd_gives_extra_to_late():
    obs = [{"date": f"2020-0{i}-01"} for i in range(1, 6)]
    early, late = c.split_observations(obs)
    assert len(early) == 2
    assert len(late) == 3


# --- detect_reversal --------------------------------------------------------

def _obs(date, stance, text="s"):
    return {"date": date, "stance": stance, "sentence": text, "slug": "x", "title": "T"}


def test_detect_reversal_flags_opposite_signs():
    obs = [
        _obs("2019-01-01", 2, "early praise"),
        _obs("2019-06-01", 2, "more praise"),
        _obs("2021-01-01", -2, "later doubt"),
        _obs("2021-06-01", -2, "more doubt"),
    ]
    rev = c.detect_reversal(obs, min_observations=4, min_delta=1.0)
    assert rev is not None
    assert rev["early_stance"] > 0
    assert rev["late_stance"] < 0
    assert rev["direction"] == "cooled"
    assert rev["n_observations"] == 4


def test_detect_reversal_warmed_direction():
    obs = [
        _obs("2019-01-01", -2),
        _obs("2019-06-01", -2),
        _obs("2021-01-01", 3),
        _obs("2021-06-01", 3),
    ]
    rev = c.detect_reversal(obs, min_observations=4, min_delta=1.0)
    assert rev is not None
    assert rev["direction"] == "warmed"


def test_detect_reversal_none_when_same_sign():
    obs = [_obs("2019-01-01", 2), _obs("2019-06-01", 1),
           _obs("2021-01-01", 2), _obs("2021-06-01", 3)]
    assert c.detect_reversal(obs, min_observations=4) is None


def test_detect_reversal_none_below_min_observations():
    obs = [_obs("2019-01-01", 2), _obs("2021-01-01", -2)]
    assert c.detect_reversal(obs, min_observations=4) is None


def test_detect_reversal_none_below_min_delta():
    # opposite signs but tiny magnitudes -> delta under threshold
    obs = [_obs("2019-01-01", 1), _obs("2019-06-01", 1),
           _obs("2021-01-01", -1), _obs("2021-06-01", -1)]
    assert c.detect_reversal(obs, min_observations=4, min_delta=5.0) is None


def test_detect_reversal_picks_extreme_representative_quotes():
    obs = [
        _obs("2019-01-01", 1, "mild early"),
        _obs("2019-06-01", 3, "strong early"),
        _obs("2021-01-01", -1, "mild late"),
        _obs("2021-06-01", -4, "strong late"),
    ]
    rev = c.detect_reversal(obs, min_observations=4, min_delta=1.0)
    assert rev["early_quote"]["sentence"] == "strong early"
    assert rev["late_quote"]["sentence"] == "strong late"


# --- find_contradictions (integration) --------------------------------------

def _entities(people=(), orgs=()):
    return {
        "top_people": [{"name": n, "article_count": ac} for n, ac in people],
        "top_organizations": [{"name": n, "article_count": ac} for n, ac in orgs],
    }


def test_find_contradictions_detects_a_flip():
    articles = [
        {"slug": "a", "date": "2019-01-01", "title": "A",
         "body": "The Fed is wise and effective. A brilliant, credible institution."},
        {"slug": "b", "date": "2019-05-01", "title": "B",
         "body": "The Fed remains strong and admirable in its judgment."},
        {"slug": "c", "date": "2021-01-01", "title": "C",
         "body": "The Fed is reckless now. A dangerous, incompetent failure."},
        {"slug": "d", "date": "2021-05-01", "title": "D",
         "body": "The Fed made a catastrophic mistake, a real disaster."},
    ]
    ents = _entities(orgs=[("Fed", 4)])
    result = c.find_contradictions(articles, ents, min_observations=4,
                                   min_mentions=3, min_delta=1.0)
    names = [r["entity"] for r in result["contradictions"]]
    assert "Fed" in names
    fed = next(r for r in result["contradictions"] if r["entity"] == "Fed")
    assert fed["type"] == "organization"
    assert fed["direction"] == "cooled"


def test_find_contradictions_skips_low_mention_entities():
    articles = [{"slug": "a", "date": "2019-01-01", "title": "A",
                 "body": "The ECB is brilliant. The ECB is a failure now."}]
    ents = _entities(orgs=[("ECB", 1)])  # below min_mentions
    result = c.find_contradictions(articles, ents, min_mentions=3)
    assert result["contradictions"] == []


def test_find_contradictions_excludes_boilerplate_by_default():
    articles = [{"slug": "a", "date": "2019-01-01", "title": "A",
                 "body": "George Calhoun is brilliant. George Calhoun is a failure."}]
    ents = _entities(people=[("George Calhoun", 50)])
    result = c.find_contradictions(articles, ents, min_mentions=1, min_observations=1)
    assert result["contradictions"] == []


# --- run --------------------------------------------------------------------

def test_run_write_false_returns_shape_without_io():
    articles = [
        {"slug": "a", "date": "2019-01-01", "title": "A",
         "body": "The Fed is wise and effective and credible."},
        {"slug": "c", "date": "2021-01-01", "title": "C",
         "body": "The Fed is reckless and dangerous and incompetent."},
    ]
    ents = _entities(orgs=[("Fed", 2)])
    result = c.run(articles=articles, entities_data=ents, min_observations=2,
                   min_mentions=1, min_delta=1.0, write=False)
    assert "meta" in result
    assert "contradictions" in result
    assert result["meta"]["params"]["min_delta"] == 1.0


def test_render_markdown_smoke():
    result = {
        "meta": {"num_contradictions": 1, "candidates_scanned": 3},
        "contradictions": [{
            "entity": "Fed", "type": "organization", "direction": "cooled",
            "early_stance": 2.0, "late_stance": -2.0, "delta": -4.0,
            "n_observations": 4,
            "early_quote": {"sentence": "praise", "date": "2019-01-01"},
            "late_quote": {"sentence": "doubt", "date": "2021-01-01"},
        }],
    }
    md = c.render_markdown(result)
    assert "Fed" in md
    assert "cooled" in md
