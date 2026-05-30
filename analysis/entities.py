"""Named entity recognition — who and what does Dr. Calhoun cite?

Uses spaCy (en_core_web_sm) to extract ORG and PERSON entities across the corpus.
No API costs — runs fully locally.

Install: pip install spacy && python -m spacy download en_core_web_sm
"""

import re
from collections import defaultdict

from .utils import load_articles, clean_text, save_analysis


def _normalize_entity(text: str) -> str:
    """Normalize entity text for deduplication."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"'s$", "", text)  # strip possessives
    return text


def run(articles: list[dict] | None = None) -> dict:
    """Extract named entities from the corpus and save results."""
    try:
        import spacy
    except ImportError:
        raise ImportError(
            "spacy not installed. Run:\n"
            "  pip install spacy\n"
            "  python -m spacy download en_core_web_sm"
        )

    if articles is None:
        articles = load_articles()

    if not articles:
        raise ValueError("No articles to analyze. Run `make scrape` first.")

    print(f"Loading spaCy model...")
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        raise OSError(
            "spaCy model not found. Run: python -m spacy download en_core_web_sm"
        )

    print(f"Extracting entities from {len(articles)} articles...")

    # Global counts: name → {count, article_slugs}
    org_counts: dict = defaultdict(lambda: {"count": 0, "slugs": set()})
    person_counts: dict = defaultdict(lambda: {"count": 0, "slugs": set()})

    per_article = []

    for i, article in enumerate(articles, 1):
        if i % 20 == 0:
            print(f"  {i}/{len(articles)}...", flush=True)

        text = clean_text(article.get("body", ""))
        # Cap at ~50k chars for speed (covers ~8k words, well above typical article length)
        doc = nlp(text[:50_000])

        slug = article.get("slug", "")
        orgs_here: dict = defaultdict(int)
        people_here: dict = defaultdict(int)

        for ent in doc.ents:
            name = _normalize_entity(ent.text)
            if not name or len(name) < 2:
                continue
            if ent.label_ == "ORG":
                orgs_here[name] += 1
            elif ent.label_ == "PERSON":
                people_here[name] += 1

        # Accumulate global counts
        for name, count in orgs_here.items():
            org_counts[name]["count"] += count
            org_counts[name]["slugs"].add(slug)

        for name, count in people_here.items():
            person_counts[name]["count"] += count
            person_counts[name]["slugs"].add(slug)

        per_article.append({
            "slug": slug,
            "date": article.get("date", ""),
            "orgs": sorted(orgs_here.items(), key=lambda x: -x[1])[:10],
            "people": sorted(people_here.items(), key=lambda x: -x[1])[:10],
        })

    # Format top entities (min 3 mentions, top 50)
    top_orgs = sorted(
        [
            {
                "name": k,
                "count": v["count"],
                "article_count": len(v["slugs"]),
                "articles": sorted(v["slugs"])[:5],
            }
            for k, v in org_counts.items()
            if v["count"] >= 3
        ],
        key=lambda x: -x["count"],
    )[:50]

    top_people = sorted(
        [
            {
                "name": k,
                "count": v["count"],
                "article_count": len(v["slugs"]),
                "articles": sorted(v["slugs"])[:5],
            }
            for k, v in person_counts.items()
            if v["count"] >= 2
        ],
        key=lambda x: -x["count"],
    )[:50]

    result = {
        "total_articles_analyzed": len(articles),
        "top_organizations": top_orgs,
        "top_people": top_people,
        "per_article": per_article,
    }

    path = save_analysis("entities.json", result)
    print(f"Entity analysis saved to {path}")
    print(f"  Top orgs: {len(top_orgs)}  Top people: {len(top_people)}")
    return result
