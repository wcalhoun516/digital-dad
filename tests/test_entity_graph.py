"""Tests for analysis.entity_graph — the entity co-occurrence graph (roadmap #14).

Offline and deterministic: every test feeds a small hand-built `per_article` fixture (the
shape of `entities.json`'s `per_article` list) to the pure helpers. No corpus, no network.
"""

import json

import pytest

from analysis import entity_graph as eg


@pytest.fixture
def per_article():
    """Four articles over two people (Powell, Buffett) and three orgs (Fed, ECB, Berkshire).

    Co-occurrences (article-level):
      - Fed+Powell: a1, a2, a3  -> weight 3
      - Fed+ECB:    a1, a2      -> weight 2
      - ECB+Powell: a1, a2      -> weight 2
      - Berkshire+Buffett: a4   -> weight 1
    """
    return [
        {"slug": "a1", "date": "2020-01-01",
         "orgs": [["Fed", 5], ["ECB", 2]], "people": [["Powell", 3]]},
        {"slug": "a2", "date": "2021-01-01",
         "orgs": [["Fed", 4], ["ECB", 1]], "people": [["Powell", 2]]},
        {"slug": "a3", "date": "2022-01-01",
         "orgs": [["Fed", 6]], "people": [["Powell", 1]]},
        {"slug": "a4", "date": "2023-01-01",
         "orgs": [["Berkshire", 3]], "people": [["Buffett", 4]]},
    ]


@pytest.fixture
def entities_data(per_article):
    return {"total_articles_analyzed": 4, "per_article": per_article}


# --- article_entities -------------------------------------------------------

def test_article_entities_types_and_ids():
    rec = {"slug": "x", "orgs": [["Fed", 2]], "people": [["Powell", 1]]}
    ents = eg.article_entities(rec)
    assert ("Fed", "org") in ents
    assert ("Powell", "person") in ents
    assert len(ents) == 2


def test_article_entities_min_mentions_filters():
    rec = {"slug": "x", "orgs": [["Fed", 3], ["ECB", 1]], "people": [["Powell", 1]]}
    ents = eg.article_entities(rec, min_mentions=2)
    assert ("Fed", "org") in ents
    assert ("ECB", "org") not in ents
    assert ("Powell", "person") not in ents


def test_article_entities_skips_blank_names():
    rec = {"slug": "x", "orgs": [["", 5]], "people": [[None, 3]]}
    assert eg.article_entities(rec) == set()


# --- cooccurrence_edges -----------------------------------------------------

def test_cooccurrence_weights(per_article):
    edges = eg.cooccurrence_edges(per_article)
    fed = eg.entity_id("Fed", "org")
    ecb = eg.entity_id("ECB", "org")
    powell = eg.entity_id("Powell", "person")
    key = tuple(sorted((fed, powell)))
    assert edges[key]["weight"] == 3
    assert sorted(edges[key]["articles"]) == ["a1", "a2", "a3"]
    assert edges[tuple(sorted((fed, ecb)))]["weight"] == 2


def test_cooccurrence_no_self_pairs(per_article):
    edges = eg.cooccurrence_edges(per_article)
    assert all(a != b for (a, b) in edges)


def test_cooccurrence_keys_are_ordered(per_article):
    edges = eg.cooccurrence_edges(per_article)
    assert all(a < b for (a, b) in edges)


# --- entity_nodes -----------------------------------------------------------

def test_entity_nodes_aggregate(per_article):
    nodes = eg.entity_nodes(per_article)
    fed = nodes[eg.entity_id("Fed", "org")]
    assert fed["article_count"] == 3
    assert fed["total_mentions"] == 15
    assert fed["type"] == "org"
    assert fed["name"] == "Fed"


# --- build_graph ------------------------------------------------------------

def test_build_graph_shape(entities_data):
    g = eg.build_graph(entities_data, top_n=10, min_cooccur=1)
    assert g["meta"]["total_articles"] == 4
    assert g["meta"]["n_nodes"] == len(g["nodes"])
    assert g["meta"]["n_edges"] == len(g["edges"])
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids


def test_build_graph_min_cooccur_prunes_weak_edges(entities_data):
    g = eg.build_graph(entities_data, top_n=10, min_cooccur=2)
    weights = [e["weight"] for e in g["edges"]]
    assert weights and min(weights) >= 2
    # Berkshire+Buffett (weight 1) must be gone
    assert all("Berkshire" not in (e["source"] + e["target"]) for e in g["edges"])


def test_build_graph_top_n_limits_nodes(entities_data):
    g = eg.build_graph(entities_data, top_n=2, min_cooccur=1)
    assert len(g["nodes"]) == 2
    # highest article_count entity (Fed=3) must be kept
    assert any(n["name"] == "Fed" for n in g["nodes"])


def test_build_graph_edges_sorted_desc(entities_data):
    g = eg.build_graph(entities_data, top_n=10, min_cooccur=1)
    weights = [e["weight"] for e in g["edges"]]
    assert weights == sorted(weights, reverse=True)


def test_build_graph_degree_counted(entities_data):
    g = eg.build_graph(entities_data, top_n=10, min_cooccur=1)
    by_name = {n["name"]: n for n in g["nodes"]}
    # Fed co-occurs with ECB and Powell -> degree 2
    assert by_name["Fed"]["degree"] == 2
    assert by_name["Buffett"]["degree"] == 1


def test_build_graph_deterministic(entities_data):
    a = eg.build_graph(entities_data, top_n=10, min_cooccur=1)
    b = eg.build_graph(entities_data, top_n=10, min_cooccur=1)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --- top_pairs / render_markdown -------------------------------------------

def test_top_pairs_readable(entities_data):
    g = eg.build_graph(entities_data, top_n=10, min_cooccur=1)
    pairs = g["top_pairs"]
    assert pairs[0]["weight"] == 3
    assert {pairs[0]["a"], pairs[0]["b"]} == {"Fed", "Powell"}


def test_render_markdown_mentions_strongest_pair(entities_data):
    g = eg.build_graph(entities_data, top_n=10, min_cooccur=1)
    md = eg.render_markdown(g)
    assert "Fed" in md and "Powell" in md
    assert md.startswith("#")


# --- exclude / boilerplate filtering (§8.5 deepen) --------------------------

def test_article_entities_exclude_is_case_insensitive():
    rec = {"slug": "x", "orgs": [["Getty Images", 4], ["Fed", 2]], "people": []}
    ents = eg.article_entities(rec, exclude={"getty images"})
    assert ("Getty Images", "org") not in ents
    assert ("Fed", "org") in ents


def test_default_exclude_drops_boilerplate():
    per_article = [
        {"slug": "a1", "orgs": [["Getty Images", 3], ["Fed", 2]],
         "people": [["George Calhoun", 1], ["Powell", 2]]},
    ]
    nodes = eg.entity_nodes(per_article)  # exclude=None -> default set
    names = {n["name"] for n in nodes.values()}
    assert "Getty Images" not in names
    assert "George Calhoun" not in names
    assert {"Fed", "Powell"} <= names


def test_no_exclude_keeps_everything():
    per_article = [{"slug": "a1", "orgs": [["Getty Images", 3]], "people": []}]
    nodes = eg.entity_nodes(per_article, exclude=frozenset())
    assert any(n["name"] == "Getty Images" for n in nodes.values())


def test_build_graph_records_excluded_param(entities_data):
    g = eg.build_graph(entities_data, exclude={"Fed"}, min_cooccur=1)
    assert "fed" in g["meta"]["params"]["excluded"]
    assert all(n["name"] != "Fed" for n in g["nodes"])


# --- run (offline, injected data) ------------------------------------------

def test_run_writes_json(tmp_path, entities_data):
    out = tmp_path / "entity_graph.json"
    result = eg.run(entities_data=entities_data, out_path=out, top_n=10, min_cooccur=1)
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["meta"]["n_nodes"] == result["meta"]["n_nodes"]


def test_run_dry_run_writes_nothing(tmp_path, entities_data):
    out = tmp_path / "entity_graph.json"
    eg.run(entities_data=entities_data, out_path=out, write=False, min_cooccur=1)
    assert not out.exists()
