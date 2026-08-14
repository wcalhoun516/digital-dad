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

def test_mentions_matches_proper_noun_form():
    assert c.mentions("the Fed raised rates", "Fed") is True


def test_mentions_is_case_sensitive_to_avoid_common_word_collisions():
    # "Jack" the person must not match the verb "jack" in "jack up the stimulus"
    assert c.mentions("would jack up the stimulus", "Jack") is False


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
    # "Fed" is reported under its canonical name (see entity_aliases.ALIASES).
    names = [r["entity"] for r in result["contradictions"]]
    assert "Federal Reserve" in names
    fed = next(r for r in result["contradictions"] if r["entity"] == "Federal Reserve")
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


# --- _stance_observations (quote-quality word band) -------------------------

def test_stance_observations_drops_run_on_sentences():
    # A glued run-on far above the band should not become a stance observation/quote.
    run_on = "The Fed is strong " + "and ".join(["really"] * 60) + " good."
    articles = [{"slug": "a", "date": "2020-01-01", "title": "A", "body": run_on}]
    obs = c._stance_observations(articles, "Fed", max_sentence_words=45)
    assert obs == []


def test_stance_observations_keeps_focused_sentence():
    articles = [{"slug": "a", "date": "2020-01-01", "title": "A",
                 "body": "The Fed is a reckless failure."}]
    obs = c._stance_observations(articles, "Fed", max_sentence_words=45)
    assert len(obs) == 1
    assert obs[0]["stance"] < 0


# --- alias dedup ------------------------------------------------------------

def test_find_contradictions_dedupes_case_insensitive_aliases():
    articles = [
        {"slug": "a", "date": "2019-01-01", "title": "A",
         "body": "COVID is a disaster. COVID is a dangerous crisis."},
        {"slug": "b", "date": "2019-02-01", "title": "B",
         "body": "COVID is a failure and a threat."},
        {"slug": "c", "date": "2021-01-01", "title": "C",
         "body": "COVID is a success now. COVID is a strong recovery."},
        {"slug": "d", "date": "2021-02-01", "title": "D",
         "body": "COVID is a healthy, promising recovery."},
    ]
    ents = _entities(people=[("COVID", 4), ("Covid", 4)])
    result = c.find_contradictions(articles, ents, min_observations=4,
                                   min_mentions=3, min_delta=1.0)
    covid_rows = [r for r in result["contradictions"] if r["entity"].lower() == "covid"]
    assert len(covid_rows) == 1


# --- entity_groups (alias-merge) --------------------------------------------

def test_entity_groups_folds_surface_variants_onto_one_canonical_subject():
    ents = _entities(orgs=[("Fed", 10), ("the Federal Reserve", 8)])
    groups = c.entity_groups(ents, min_mentions=3, exclude=frozenset())
    assert len(groups) == 1
    assert groups[0]["name"] == "Federal Reserve"
    assert groups[0]["surfaces"] == ["Fed", "the Federal Reserve"]


def test_entity_groups_keeps_unrelated_subjects_apart():
    ents = _entities(orgs=[("Fed", 10), ("ECB", 8)])
    groups = c.entity_groups(ents, min_mentions=3, exclude=frozenset())
    assert [g["name"] for g in groups] == ["Federal Reserve", "European Central Bank"]


def test_entity_groups_without_aliases_keeps_raw_variants_separate():
    ents = _entities(orgs=[("Fed", 10), ("the Federal Reserve", 8)])
    groups = c.entity_groups(ents, min_mentions=3, exclude=frozenset(), aliases=False)
    assert [g["name"] for g in groups] == ["Fed", "the Federal Reserve"]


def test_entity_groups_collapses_case_only_variants_even_without_aliases():
    # The pre-alias behaviour: "COVID"/"Covid" were one subject. Still true with aliases off.
    ents = _entities(people=[("COVID", 5), ("Covid", 4)])
    groups = c.entity_groups(ents, min_mentions=3, exclude=frozenset(), aliases=False)
    assert len(groups) == 1
    assert groups[0]["surfaces"] == ["COVID", "Covid"]


def test_entity_groups_respects_mention_floor_and_exclude():
    ents = _entities(people=[("George Calhoun", 50), ("Jack Ma", 2)], orgs=[("ECB", 9)])
    groups = c.entity_groups(ents, min_mentions=3, exclude=c._DEFAULT_EXCLUDE)
    assert [g["name"] for g in groups] == ["European Central Bank"]


def test_entity_groups_takes_type_from_first_seen_surface():
    ents = _entities(people=[("Powell", 6)], orgs=[("Jerome Powell", 4)])
    groups = c.entity_groups(ents, min_mentions=3, exclude=frozenset())
    assert len(groups) == 1
    assert groups[0]["name"] == "Jerome Powell"
    assert groups[0]["type"] == "person"


# --- _group_observations (union + dedup across surface forms) ---------------

def test_group_observations_unions_every_surface_form():
    articles = [{"slug": "a", "date": "2020-01-01", "title": "A",
                 "body": "The Fed is reckless and dangerous. "
                         "The Federal Reserve is a real disaster."}]
    obs = c._group_observations(articles, ["Fed", "Federal Reserve"])
    assert len(obs) == 2


def test_group_observations_counts_a_two_variant_sentence_once():
    articles = [{"slug": "a", "date": "2020-01-01", "title": "A",
                 "body": "The Fed, the Federal Reserve, is a reckless disaster."}]
    obs = c._group_observations(articles, ["Fed", "Federal Reserve"])
    assert len(obs) == 1


def test_group_observations_counts_a_duplicated_article_once():
    # data/manifest.json carries 23 duplicate slugs (see scraper/README.md), so load_articles()
    # hands the same article back twice and its evidence would otherwise count double.
    article = {"slug": "a", "date": "2020-01-01", "title": "A",
               "body": "The Fed is reckless and dangerous."}
    assert len(c._group_observations([article, dict(article)], ["Fed"])) == 1


def test_group_observations_is_case_sensitive_per_surface():
    # Searching with both raw spellings is what recovers the "Covid" sentence.
    articles = [{"slug": "a", "date": "2020-01-01", "title": "A",
                 "body": "COVID is a disaster for everyone. "
                         "Covid is a catastrophe for everyone."}]
    assert len(c._group_observations(articles, ["COVID"])) == 1
    assert len(c._group_observations(articles, ["COVID", "Covid"])) == 2


# --- find_contradictions alias-merge ----------------------------------------

def _fed_flip_articles():
    return [
        {"slug": "a", "date": "2019-01-01", "title": "A",
         "body": "The Fed is wise and effective. The Federal Reserve is credible."},
        {"slug": "b", "date": "2019-05-01", "title": "B",
         "body": "The Fed remains strong and admirable in its judgment."},
        {"slug": "c", "date": "2021-01-01", "title": "C",
         "body": "The Fed is reckless and dangerous now. "
                 "The Federal Reserve is an incompetent failure."},
        {"slug": "d", "date": "2021-05-01", "title": "D",
         "body": "The Fed made a catastrophic mistake, a real disaster."},
    ]


def test_find_contradictions_merges_variants_into_one_canonical_row():
    ents = _entities(orgs=[("Fed", 4), ("Federal Reserve", 4)])
    result = c.find_contradictions(_fed_flip_articles(), ents, min_observations=4,
                                   min_mentions=3, min_delta=1.0)
    assert [r["entity"] for r in result["contradictions"]] == ["Federal Reserve"]


def test_find_contradictions_merged_row_uses_every_variants_observations():
    ents = _entities(orgs=[("Fed", 4), ("Federal Reserve", 4)])
    merged = c.find_contradictions(_fed_flip_articles(), ents, min_observations=4,
                                   min_mentions=3, min_delta=1.0)["contradictions"][0]
    fed_only = c.find_contradictions(_fed_flip_articles(), _entities(orgs=[("Fed", 4)]),
                                     min_observations=4, min_mentions=3,
                                     min_delta=1.0)["contradictions"][0]
    assert merged["n_observations"] > fed_only["n_observations"]


def test_find_contradictions_no_aliases_keeps_variants_separate():
    ents = _entities(orgs=[("Fed", 4), ("Federal Reserve", 4)])
    result = c.find_contradictions(_fed_flip_articles(), ents, min_observations=4,
                                   min_mentions=3, min_delta=1.0, aliases=False)
    assert [r["entity"] for r in result["contradictions"]] == ["Fed"]


def test_find_contradictions_scans_canonical_subjects_not_raw_surfaces():
    ents = _entities(orgs=[("Fed", 4), ("Federal Reserve", 4)])
    result = c.find_contradictions(_fed_flip_articles(), ents, min_observations=4,
                                   min_mentions=3, min_delta=1.0)
    assert result["meta"]["candidates_scanned"] == 1


def test_find_contradictions_records_aliases_param():
    ents = _entities(orgs=[("Fed", 4)])
    result = c.find_contradictions(_fed_flip_articles(), ents, min_mentions=3)
    assert result["meta"]["params"]["aliases"] is True


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
