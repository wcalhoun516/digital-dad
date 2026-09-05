"""Semantic search over the article corpus.

All embeddings flow through the local-llm-conductor's OpenAI-compatible
``/v1/embeddings`` endpoint with ``sbert-mpnet-v2`` pinned for index
consistency. Vectors from different embedders aren't comparable, so the
persistent index must pin one model on both sides.

The article matrix is cached at ``data/analysis/embeddings.npy``; the
slug→index map and a corpus+model fingerprint live in
``data/analysis/embeddings_meta.json``. A flat JSON export for the
dashboard lives at ``data/analysis/embeddings.json``.

CLI usage:
    python -m analysis.semantic_search "what does he think about nuclear energy"
    python -m analysis.semantic_search "spectrum policy" --top-k 3
"""

import argparse
import hashlib
import json

import numpy as np

from .utils import DATA_DIR, clean_text, load_articles, log

# Pinned embedder. The conductor will route directly here when this id is
# passed in the request body, bypassing its smart-routing classifier. The
# index and any query MUST use the same embedder for cosine to be meaningful.
EMBED_MODEL = "sbert-mpnet-v2"
CONDUCTOR_BASE_URL = "http://127.0.0.1:8080/v1"

EMBEDDINGS_PATH = DATA_DIR / "analysis" / "embeddings.npy"
METADATA_PATH = DATA_DIR / "analysis" / "embeddings_meta.json"
DASHBOARD_EXPORT_PATH = DATA_DIR / "analysis" / "embeddings.json"

# Keep embedding inputs to a sane prefix; mpnet's encoder context is short
# (~512 tokens) and the first 2k words of an article carry the gist.
_MAX_WORDS_PER_ARTICLE = 2000


# ---------------------------------------------------------------------------
# Conductor client
# ---------------------------------------------------------------------------

def _get_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError(
            "openai package not installed. Run: pip install -e '.[analyze]'"
        ) from exc
    return OpenAI(base_url=CONDUCTOR_BASE_URL, api_key="local")


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via the conductor with sbert-mpnet-v2 pinned."""
    if not texts:
        return []
    client = _get_client()
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    # OpenAI shape: data is sorted by index already, but be defensive.
    items = sorted(resp.data, key=lambda d: d.index)
    return [item.embedding for item in items]


def _embed_one(text: str) -> list[float]:
    return _embed_batch([text])[0]


# ---------------------------------------------------------------------------
# Cache fingerprinting
# ---------------------------------------------------------------------------

def _corpus_hash(articles: list[dict]) -> str:
    """Stable hash of corpus contents + the pinned embed model id.

    Including the model id forces a re-embed if the embedder changes — the
    vector spaces aren't comparable across models, so the cached matrix is
    invalid the moment EMBED_MODEL changes, even if dimensions still match.
    """
    parts = []
    for a in sorted(articles, key=lambda x: x.get("slug", "")):
        h = a.get("content_hash") or hashlib.md5(
            (a.get("body") or "").encode()
        ).hexdigest()
        parts.append(f"{a.get('slug', '')}:{h}")
    key = EMBED_MODEL + "|" + "|".join(parts)
    return hashlib.md5(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Build / load
# ---------------------------------------------------------------------------

def _truncate_for_embed(body: str) -> str:
    text = clean_text(body or "")
    words = text.split()
    if len(words) > _MAX_WORDS_PER_ARTICLE:
        text = " ".join(words[:_MAX_WORDS_PER_ARTICLE])
    return text


def build_embeddings(
    articles: list[dict] | None = None,
    batch_size: int = 16,
) -> tuple[np.ndarray, list[dict]]:
    """Return (embeddings, metadata). Re-embeds only when the corpus changes.

    Embeddings are written to ``data/analysis/embeddings.npy`` and the
    dashboard JSON export is refreshed.
    """
    if articles is None:
        articles = load_articles()

    if not articles:
        raise ValueError("No articles to embed. Run `make scrape` first.")

    current_hash = _corpus_hash(articles)

    # Cache hit
    if EMBEDDINGS_PATH.exists() and METADATA_PATH.exists():
        meta = json.loads(METADATA_PATH.read_text())
        if meta.get("hash") == current_hash and meta.get("model") == EMBED_MODEL:
            embeddings = np.load(EMBEDDINGS_PATH)
            # Make sure the dashboard export still exists; rebuild if missing.
            if not DASHBOARD_EXPORT_PATH.exists():
                _write_dashboard_export(embeddings, meta["articles"], articles)
            return embeddings, meta["articles"]

    log.info("Embedding %d articles via conductor → %s...", len(articles), EMBED_MODEL)

    texts = [_truncate_for_embed(a.get("body", "")) for a in articles]
    meta_articles: list[dict] = [
        {
            "slug": a.get("slug"),
            "title": a.get("title"),
            "date": a.get("date"),
            "url": a.get("url"),
        }
        for a in articles
    ]

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        end = min(start + batch_size, len(texts))
        log.debug("  batch %d: articles %d-%d", start // batch_size + 1, start + 1, end)
        vectors.extend(_embed_batch(chunk))

    embeddings = np.array(vectors, dtype=np.float32)

    EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(EMBEDDINGS_PATH, embeddings)
    METADATA_PATH.write_text(
        json.dumps(
            {
                "hash": current_hash,
                "model": EMBED_MODEL,
                "articles": meta_articles,
            },
            indent=2,
        )
    )
    _write_dashboard_export(embeddings, meta_articles, articles)
    log.info("Saved embeddings → %s", EMBEDDINGS_PATH)

    return embeddings, meta_articles


def _write_dashboard_export(
    embeddings: np.ndarray,
    meta_articles: list[dict],
    articles: list[dict] | None = None,
) -> None:
    """Write a flat JSON the dashboard can inline.

    Shape: ``{"model": ..., "slugs": [...], "titles": [...], "dates": [...],
              "urls": [...], "vectors": [[...], ...], "snippets": [...]}``.

    Floats are rounded to 5 decimals to keep the inlined size manageable
    (~6 chars/float vs. 18+ for full precision); the precision loss is
    cosmetic for cosine similarity.

    The ``snippets`` array provides the first ~2000 chars of each article
    body for the "Ask Dad" RAG chat tab. If raw articles aren't available,
    snippets are empty strings (search still works, chat won't).
    """
    DASHBOARD_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rounded = np.round(embeddings.astype(np.float32), 5).tolist()

    # Build slug→snippet map from full articles if available
    snippet_map = {}
    if articles:
        for a in articles:
            body = clean_text(a.get("body", ""))
            # First ~2000 chars — enough for RAG context
            snippet_map[a.get("slug", "")] = body[:2000]

    payload = {
        "model": EMBED_MODEL,
        "dim": embeddings.shape[1] if embeddings.ndim == 2 else 0,
        "slugs": [m.get("slug") for m in meta_articles],
        "titles": [m.get("title") for m in meta_articles],
        "dates": [m.get("date") for m in meta_articles],
        "urls": [m.get("url") for m in meta_articles],
        "vectors": rounded,
        "snippets": [snippet_map.get(m.get("slug", ""), "") for m in meta_articles],
    }
    DASHBOARD_EXPORT_PATH.write_text(json.dumps(payload))


def export_for_dashboard(articles: list[dict] | None = None) -> None:
    """Re-export the dashboard JSON from the cached .npy + meta files."""
    if not (EMBEDDINGS_PATH.exists() and METADATA_PATH.exists()):
        raise FileNotFoundError(
            "embeddings cache not found — run build_embeddings() first"
        )
    if articles is None:
        articles = load_articles()
    embeddings = np.load(EMBEDDINGS_PATH)
    meta = json.loads(METADATA_PATH.read_text())
    _write_dashboard_export(embeddings, meta["articles"], articles)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(
    query: str,
    top_k: int = 5,
    articles: list[dict] | None = None,
) -> list[dict]:
    """Return the top_k most similar articles to *query* by cosine similarity."""
    embeddings, meta_articles = build_embeddings(articles)
    query_vec = np.array(_embed_one(query), dtype=np.float32)

    norms = np.linalg.norm(embeddings, axis=1)
    query_norm = np.linalg.norm(query_vec)
    similarities = (embeddings @ query_vec) / (norms * query_norm + 1e-10)

    top_indices = np.argsort(similarities)[::-1][:top_k]
    return [
        {**meta_articles[idx], "similarity": float(similarities[idx])}
        for idx in top_indices
    ]


# ---------------------------------------------------------------------------
# Module entry point — invoked by `python -m analysis` via __main__.py
# ---------------------------------------------------------------------------

def run(articles: list[dict] | None = None) -> None:
    """Build (or refresh) the corpus embedding index."""
    embeddings, meta = build_embeddings(articles)
    log.info(
        "  Embedded %d articles via %s (%d-d vectors)",
        len(meta), EMBED_MODEL, embeddings.shape[1],
    )
    log.info("  Index → %s", EMBEDDINGS_PATH)
    log.info("  Dashboard export → %s", DASHBOARD_EXPORT_PATH)


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Semantic search over Dr. Calhoun's article corpus",
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--top-k", type=int, default=5, metavar="K",
        help="Number of results to return (default: 5)",
    )
    args = parser.parse_args()

    results = search(args.query, top_k=args.top_k)
    print(f"\nTop {len(results)} results for: {args.query!r}\n")
    for i, r in enumerate(results, 1):
        print(f"  {i}. [{r['similarity']:.3f}] {r['title']} ({r['date']})")
        print(f"       {r['url']}")


if __name__ == "__main__":
    _cli()
