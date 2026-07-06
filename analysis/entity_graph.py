"""Entity co-occurrence graph — who shows up alongside whom (roadmap #14).

Reads the entity extraction already on disk (`data/analysis/entities.json`) and builds an
undirected co-occurrence graph: nodes are the people/organizations Dr. Calhoun writes about,
and an edge between two entities is weighted by the number of articles they appear in together.
It's the data layer for a future dashboard **network viz** — this module ships the deterministic
builder; the D3 rendering is a later slice.

Deliberately **deterministic and offline**: it consumes `entities.json` (`per_article` entity
lists) and writes `entity_graph.json`. It makes no conductor, network, or LLM calls, so it is
safe to run unattended. The output carries only public entity names, co-occurrence counts, and
public slugs — no article-body text — so it is committable exactly like `entities.json`.
"""

import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from .utils import ANALYSIS_DIR

ENTITIES_PATH = ANALYSIS_DIR / "entities.json"
OUTPUT_PATH = ANALYSIS_DIR / "entity_graph.json"

# Boilerplate the extractor picks up that isn't a *subject* Dr. Calhoun writes about: his own
# byline / Stevens-Institute bio ("George Calhoun", "Calhoun", "Rafael", "Stevens") and the
# Forbes photo-credit line ("Getty Images", "AFP"). Excluded by default so the graph reflects
# the people/orgs in his arguments, not the page furniture. Overridable via `exclude=` / the
# `--exclude` / `--no-exclude` CLI flags. Matched case-insensitively on the entity name.
_DEFAULT_EXCLUDE = frozenset({
    "getty images", "afp", "getty",
    "george calhoun", "calhoun", "rafael", "stevens",
})


def _norm_exclude(exclude) -> frozenset[str]:
    """Normalize an exclude collection to a lowercased frozenset (None → the default set)."""
    if exclude is None:
        return _DEFAULT_EXCLUDE
    return frozenset(name.lower() for name in exclude)


def entity_id(name: str, entity_type: str) -> str:
    """Stable node id for an entity. Namespacing by type keeps a person and an org that
    happen to share a surface form (e.g. "Covid") from collapsing into one node."""
    return f"{entity_type}:{name}"


def article_entities(
    record: dict, *, min_mentions: int = 1, exclude=None
) -> set[tuple[str, str]]:
    """The set of ``(name, type)`` entities in one ``per_article`` record.

    ``record`` is one entry of ``entities.json``'s ``per_article`` list: ``{slug, date,
    orgs: [[name, count], ...], people: [[name, count], ...]}``. Entities mentioned fewer than
    ``min_mentions`` times, blank names, and names in ``exclude`` (case-insensitive; defaults
    to :data:`_DEFAULT_EXCLUDE`) are dropped.
    """
    excluded = _norm_exclude(exclude)
    out: set[tuple[str, str]] = set()
    for kind, entity_type in (("orgs", "org"), ("people", "person")):
        for name, count in record.get(kind, []):
            if name and count >= min_mentions and name.lower() not in excluded:
                out.add((name, entity_type))
    return out


def cooccurrence_edges(
    per_article: list[dict], *, min_mentions: int = 1, exclude=None
) -> dict:
    """Count the articles in which each entity pair co-occurs.

    Returns ``{(id_a, id_b): {"weight": n, "articles": [slug, ...]}}`` where ``id_a < id_b``
    (canonical order, no self-pairs). ``weight`` is the number of articles both entities appear
    in together.
    """
    edges: dict[tuple[str, str], dict] = {}
    for record in per_article:
        ids = sorted(
            entity_id(name, entity_type)
            for name, entity_type in article_entities(
                record, min_mentions=min_mentions, exclude=exclude
            )
        )
        slug = record.get("slug")
        for a, b in combinations(ids, 2):
            edge = edges.setdefault((a, b), {"weight": 0, "articles": []})
            edge["weight"] += 1
            if slug:
                edge["articles"].append(slug)
    return edges


def entity_nodes(per_article: list[dict], *, min_mentions: int = 1, exclude=None) -> dict:
    """Aggregate per-entity stats across all articles.

    Returns ``{id: {id, name, type, article_count, total_mentions}}``. ``article_count`` is the
    number of distinct articles the entity appears in (with at least ``min_mentions`` mentions);
    ``total_mentions`` sums the raw counts. Names in ``exclude`` are dropped (see
    :func:`article_entities`).
    """
    excluded = _norm_exclude(exclude)
    nodes: dict[str, dict] = {}
    for record in per_article:
        for kind, entity_type in (("orgs", "org"), ("people", "person")):
            for name, count in record.get(kind, []):
                if not name or count < min_mentions or name.lower() in excluded:
                    continue
                nid = entity_id(name, entity_type)
                node = nodes.setdefault(
                    nid,
                    {"id": nid, "name": name, "type": entity_type,
                     "article_count": 0, "total_mentions": 0},
                )
                node["article_count"] += 1
                node["total_mentions"] += count
    return nodes


def top_pairs(edges: list[dict], nodes_by_id: dict, *, limit: int = 15) -> list[dict]:
    """The strongest co-occurrence pairs, rendered with readable entity names."""
    out = []
    for edge in edges[:limit]:
        a = nodes_by_id.get(edge["source"], {})
        b = nodes_by_id.get(edge["target"], {})
        out.append({
            "a": a.get("name", edge["source"]),
            "b": b.get("name", edge["target"]),
            "a_type": a.get("type"),
            "b_type": b.get("type"),
            "weight": edge["weight"],
        })
    return out


def build_graph(
    entities_data: dict,
    *,
    top_n: int = 40,
    min_cooccur: int = 2,
    min_mentions: int = 1,
    exclude=None,
) -> dict:
    """Assemble the co-occurrence graph (pure; no I/O).

    Keeps the ``top_n`` most-written-about entities (by article_count, then total_mentions),
    draws edges between them for pairs that co-occur at least ``min_cooccur`` times, and records
    each node's ``degree``. ``exclude`` drops boilerplate entities (defaults to
    :data:`_DEFAULT_EXCLUDE`). Fully deterministic: nodes and edges sort on stable keys.
    """
    per_article = entities_data.get("per_article", [])
    all_nodes = entity_nodes(per_article, min_mentions=min_mentions, exclude=exclude)

    selected = sorted(
        all_nodes.values(),
        key=lambda n: (-n["article_count"], -n["total_mentions"], n["id"]),
    )[:top_n]
    kept = {n["id"] for n in selected}

    raw = cooccurrence_edges(per_article, min_mentions=min_mentions, exclude=exclude)
    edges = []
    degree: Counter = Counter()
    for (a, b), info in raw.items():
        if a in kept and b in kept and info["weight"] >= min_cooccur:
            edges.append({
                "source": a,
                "target": b,
                "weight": info["weight"],
                "articles": sorted(set(info["articles"])),
            })
            degree[a] += 1
            degree[b] += 1
    edges.sort(key=lambda e: (-e["weight"], e["source"], e["target"]))

    for node in selected:
        node["degree"] = degree.get(node["id"], 0)

    nodes_by_id = {n["id"]: n for n in selected}
    return {
        "meta": {
            "total_articles": entities_data.get("total_articles_analyzed"),
            "n_nodes": len(selected),
            "n_edges": len(edges),
            "params": {
                "top_n": top_n,
                "min_cooccur": min_cooccur,
                "min_mentions": min_mentions,
                "excluded": sorted(_norm_exclude(exclude)),
            },
        },
        "nodes": selected,
        "edges": edges,
        "top_pairs": top_pairs(edges, nodes_by_id),
    }


def render_markdown(graph: dict) -> str:
    """A short human-readable summary (for `--dry-run` and logs)."""
    meta = graph["meta"]
    lines = [
        "# Entity co-occurrence graph",
        "",
        f"{meta['n_nodes']} entities, {meta['n_edges']} edges "
        f"(from {meta.get('total_articles')} articles).",
    ]
    pairs = graph.get("top_pairs") or []
    if pairs:
        lines += ["", "## Strongest pairings"]
        lines += [f"- {p['a']} + {p['b']} ({p['weight']} articles)" for p in pairs]
    nodes = graph.get("nodes") or []
    if nodes:
        by_degree = sorted(nodes, key=lambda n: (-n["degree"], -n["article_count"], n["id"]))
        lines += ["", "## Most connected"]
        lines += [
            f"- {n['name']} ({n['type']}) — degree {n['degree']}, {n['article_count']} articles"
            for n in by_degree[:10]
        ]
    return "\n".join(lines)


def _load_entities(path: Path = ENTITIES_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No entities analysis at {path}. Run `make analyze entities` first."
        )
    return json.loads(path.read_text())


def run(
    *,
    entities_data: dict | None = None,
    out_path: Path = OUTPUT_PATH,
    top_n: int = 40,
    min_cooccur: int = 2,
    min_mentions: int = 1,
    exclude=None,
    write: bool = True,
) -> dict:
    """Build the entity co-occurrence graph and (unless ``write=False``) write it to disk.

    Deterministic and offline: reads ``entities.json`` (or the injected ``entities_data``) and
    writes ``entity_graph.json``. Makes no conductor/network/LLM calls.
    """
    if entities_data is None:
        entities_data = _load_entities()

    graph = build_graph(
        entities_data,
        top_n=top_n,
        min_cooccur=min_cooccur,
        min_mentions=min_mentions,
        exclude=exclude,
    )

    if write:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False))

    return graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Entity co-occurrence graph builder (roadmap #14)."
    )
    parser.add_argument("--top", type=int, default=40,
                        help="Keep the N most-written-about entities (default 40).")
    parser.add_argument("--min-cooccur", type=int, default=2,
                        help="Minimum shared articles for an edge (default 2).")
    parser.add_argument("--min-mentions", type=int, default=1,
                        help="Minimum mentions for an entity to count in an article (default 1).")
    parser.add_argument("--exclude", action="append", metavar="NAME", default=None,
                        help="Extra entity name to drop (repeatable); adds to the default "
                             "boilerplate set.")
    parser.add_argument("--no-exclude", action="store_true",
                        help="Disable the default boilerplate exclude set (keep all entities).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the summary without writing entity_graph.json.")
    args = parser.parse_args(argv)

    if args.no_exclude:
        exclude: frozenset[str] | None = frozenset()
    elif args.exclude:
        exclude = _DEFAULT_EXCLUDE | {name.lower() for name in args.exclude}
    else:
        exclude = None

    graph = run(
        top_n=args.top,
        min_cooccur=args.min_cooccur,
        min_mentions=args.min_mentions,
        exclude=exclude,
        write=not args.dry_run,
    )
    print(render_markdown(graph))
    if args.dry_run:
        print("\nDry run — nothing written.")
    else:
        print(f"\nWrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
