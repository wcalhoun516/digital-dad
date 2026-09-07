"""On This Day — weekly email from the archive.

Pulls top headlines from news RSS feeds, embeds each headline, matches
against the article corpus by cosine similarity, and generates a short
intro in Dr. Calhoun's voice explaining why the matched article is
relevant to this week's news.

Output: a formatted email (subject + HTML body) saved to
``data/cron/emails/`` and optionally created as a Gmail draft.

Designed to be called from ``bin/weekly_run.sh`` as the final step in the
Sunday cron job.
"""

import html
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import numpy as np

from .semantic_search import (
    CONDUCTOR_BASE_URL,
    _embed_one,
    build_embeddings,
)
from .utils import DATA_DIR, clean_text, load_articles

EMAIL_DIR = DATA_DIR / "cron" / "emails"

# Roundup tuning (precision-first): a headline only earns an "in his words" blurb when its
# best article match clears this cosine threshold; the roundup is capped to keep it tight.
ROUNDUP_THRESHOLD = 0.55
ROUNDUP_CAP = 6

# RSS feeds to pull headlines from (business/econ/tech focused).
# NOTE: Reuters retired its public feeds.reuters.com RSS (DNS now fails), so these are
# current, reliable sources — a healthy pool matters for the roundup's precision bar.
RSS_FEEDS = [
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
]

INTRO_PROMPT = """You are Dr. George Calhoun — Forbes columnist, telecom economist, contrarian thinker. You write with precision, data-driven authority, and a taste for em-dashes.

In 2–3 sentences, explain why your {year} article "{article_title}" is suddenly relevant given this week's headline: "{headline}".

Speak naturally in first person as yourself. End with: "See the full piece below."

Style notes: sentences average 22 words. You favor em-dashes, and use words like "Notably" and "Crucially" as paragraph hinges. You are data-driven but not dry."""

EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #2a2a2a; line-height: 1.7;">
  <div style="border-bottom: 2px solid #c9a84c; padding-bottom: 12px; margin-bottom: 24px;">
    <h1 style="font-size: 1.4em; font-weight: 400; margin: 0;">From the Archive</h1>
    <p style="font-size: 0.85em; color: #888; margin: 4px 0 0;">Week of {week_date}</p>
  </div>

  {roundup_section}

  <p style="font-size: 0.9em; color: #666; margin-bottom: 8px;">
    <em>This week, in depth &mdash; matched to:</em><br>
    <strong>{headline}</strong>
  </p>

  <div style="border-left: 3px solid #c9a84c; padding: 12px 20px; margin: 20px 0; font-style: italic; font-size: 1.05em; color: #333;">
    {intro}
  </div>

  <h2 style="font-size: 1.2em; font-weight: 400; margin: 24px 0 8px;">
    <a href="{article_url}" style="color: #c9a84c; text-decoration: none;">{article_title}</a>
  </h2>
  <p style="font-size: 0.85em; color: #888; margin: 0 0 16px;">
    Published {article_date} &middot; {article_words} words
  </p>

  <div style="font-size: 0.95em; white-space: pre-wrap;">{article_excerpt}</div>

  <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 0.8em; color: #aaa; text-align: center;">
    Digital Dad &middot; The Intellectual Archive of Dr. George Calhoun
  </div>
</body>
</html>
"""


ROUNDUP_ITEM_TEMPLATE = """\
  <div style="margin-bottom: 18px;">
    <p style="font-size: 0.95em; font-weight: bold; margin: 0 0 4px;">{headline}</p>
    <p style="font-size: 0.92em; font-style: italic; color: #444; margin: 0 0 4px;">{blurb}</p>
    <p style="font-size: 0.8em; color: #888; margin: 0;">&mdash; <a href="{url}" style="color: #c9a84c; text-decoration: none;">{title}</a> ({year})</p>
  </div>"""

ROUNDUP_SECTION_TEMPLATE = """\
  <div style="margin-bottom: 28px;">
    <h2 style="font-size: 1.2em; font-weight: 400; margin: 0 0 14px;">This Week &mdash; In His Words</h2>
    <p style="font-size: 0.85em; color: #888; margin: 0 0 16px;">Where this week's headlines echo something he already wrote.</p>
{items}
  </div>
  <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
"""


def _render_roundup(items: list[dict]) -> str:
    """Render the 'in his words' roundup block (empty string when no items).

    Each item is ``{headline, blurb, title, url, year}``; user-facing text is
    HTML-escaped (RSS titles and LLM blurbs can contain ``&``/``<``).
    """
    if not items:
        return ""
    rendered = "\n".join(
        ROUNDUP_ITEM_TEMPLATE.format(
            headline=html.escape(it.get("headline", ""), quote=False),
            blurb=html.escape(it.get("blurb", ""), quote=False),
            title=html.escape(it.get("title", ""), quote=False),
            url=html.escape(it.get("url", "#"), quote=True),
            year=html.escape(it.get("year", ""), quote=False),
        )
        for it in items
    )
    return ROUNDUP_SECTION_TEMPLATE.format(items=rendered)


def _fetch_headlines(max_per_feed: int = 5) -> list[dict]:
    """Fetch recent headlines from RSS feeds."""
    headlines = []
    for url in RSS_FEEDS:
        try:
            req = Request(url, headers={"User-Agent": "DigitalDad/1.0"})
            with urlopen(req, timeout=10) as resp:
                tree = ET.parse(resp)
            root = tree.getroot()
            # Handle both RSS and Atom feeds
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)
            for item in items[:max_per_feed]:
                title = (
                    item.findtext("title")
                    or item.findtext("atom:title", namespaces=ns)
                    or ""
                ).strip()
                if title:
                    headlines.append({"title": title, "source": url})
        except Exception as e:
            print(f"  Warning: could not fetch {url}: {e}", file=sys.stderr)
    return headlines


def _get_conductor_client():
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed.")
    return OpenAI(base_url=CONDUCTOR_BASE_URL, api_key="local")


def _generate_intro(client, article: dict, headline: str) -> str:
    """Generate a 2-3 sentence intro in Dr. Calhoun's voice."""
    year = (article.get("date") or "")[:4]
    prompt = INTRO_PROMPT.format(
        year=year,
        article_title=article.get("title", ""),
        headline=headline,
    )
    response = client.chat.completions.create(
        model="auto",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"tier": 2, "function": "text"},
    )
    return (response.choices[0].message.content or "").strip()


def select_matches(matches: list[dict], *, threshold: float = ROUNDUP_THRESHOLD,
                   cap: int = ROUNDUP_CAP) -> dict:
    """Pick the deep-dive (global best) plus a precision-first roundup.

    ``matches`` is one record per headline — its single best article —
    ``{"headline": str, "article_idx": int, "score": float}``. Returns
    ``{"deep_dive": <match|None>, "roundup": [<match>, ...]}`` where the roundup is the
    *other* headlines whose score is >= ``threshold``, sorted strongest-first, deduped by
    article (stronger headline wins), excluding the deep-dive's article, capped at ``cap``.
    Pure: no embedding, no network.
    """
    if not matches:
        return {"deep_dive": None, "roundup": []}
    deep_dive = max(matches, key=lambda m: m["score"])
    roundup: list[dict] = []
    seen_articles = {deep_dive["article_idx"]}
    for m in sorted(matches, key=lambda m: m["score"], reverse=True):
        if m is deep_dive or m["score"] < threshold or m["article_idx"] in seen_articles:
            continue
        roundup.append(m)
        seen_articles.add(m["article_idx"])
        if len(roundup) >= cap:
            break
    return {"deep_dive": deep_dive, "roundup": roundup}


BLURB_PROMPT = """You are Dr. George Calhoun — Forbes columnist, telecom economist, contrarian thinker.

In ONE sentence, first person, note why your {year} article "{article_title}" speaks to this week's headline: "{headline}". Be specific and pointed. Output only the sentence — no preamble, no quotation marks."""


def _generate_blurb(client, article: dict, headline: str) -> str:
    """One-sentence in-voice connection for a roundup item (free local tier-2)."""
    prompt = BLURB_PROMPT.format(
        year=(article.get("date") or "")[:4],
        article_title=article.get("title", ""),
        headline=headline,
    )
    try:
        response = client.chat.completions.create(
            model="auto",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"tier": 2, "function": "text"},
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"  Warning: blurb generation failed: {e}", file=sys.stderr)
        return ""


def run(
    articles: list[dict] | None = None,
    recipient_label: str = "the family",
    dry_run: bool = False,
) -> dict | None:
    """Generate the weekly 'On This Day' email.

    Returns a dict with subject, html_body, matched_article, and matched_headline.
    Saves the email HTML to data/cron/emails/.
    """
    if articles is None:
        articles = load_articles()

    if not articles:
        print("No articles found. Skipping On This Day.")
        return None

    # Step 1: Fetch headlines
    print("On This Day: fetching news headlines...")
    headlines = _fetch_headlines()
    if not headlines:
        print("  No headlines fetched. Skipping.")
        return None
    print(f"  {len(headlines)} headlines from {len(RSS_FEEDS)} feeds")

    # Step 2: Build/load embeddings
    print("  Loading corpus embeddings...")
    embeddings, meta_articles = build_embeddings(articles)

    # Step 3: Embed each headline, record its best corpus match, then select.
    print("  Matching headlines to corpus...")
    norms = np.linalg.norm(embeddings, axis=1)
    per_headline: list[dict] = []
    for h in headlines:
        try:
            query_vec = np.array(_embed_one(h["title"]), dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            similarities = (embeddings @ query_vec) / (norms * query_norm + 1e-10)
            top_idx = int(np.argmax(similarities))
            per_headline.append({
                "headline": h["title"],
                "article_idx": top_idx,
                "score": float(similarities[top_idx]),
            })
        except Exception as e:
            print(f"  Warning: embedding failed for headline: {e}", file=sys.stderr)
            continue

    if not per_headline:
        print("  No headlines could be embedded. Skipping.")
        return None

    selection = select_matches(per_headline)
    deep = selection["deep_dive"]
    best_headline = deep["headline"]
    best_article_idx = deep["article_idx"]
    best_score = deep["score"]
    print(f"  Deep-dive match (score {best_score:.3f}); roundup candidates: "
          f"{len(selection['roundup'])}")

    matched_meta = meta_articles[best_article_idx]
    # Find the full article for excerpt
    matched_article = None
    for a in articles:
        if a.get("slug") == matched_meta.get("slug"):
            matched_article = a
            break

    if not matched_article:
        matched_article = {"title": matched_meta.get("title"), "date": matched_meta.get("date"),
                           "url": matched_meta.get("url"), "body": "", "word_count": 0}

    print(f"  Best match: \"{matched_meta['title'][:60]}...\" (score: {best_score:.3f})")
    print(f"  Headline: \"{best_headline[:80]}\"")

    if dry_run:
        print("  Dry run — skipping LLM intro and email generation.")
        return {"dry_run": True, "headline": best_headline,
                "article": matched_meta["title"], "score": best_score,
                "roundup_candidates": len(selection["roundup"])}

    # Step 4: Generate intro in Dad's voice
    print("  Generating intro in Dr. Calhoun's voice...")
    client = _get_conductor_client()
    intro = _generate_intro(client, matched_article, best_headline)
    print(f"  Intro: {intro[:100]}...")

    # Step 4b: Roundup — a one-sentence in-voice blurb per other qualifying headline.
    roundup_items = []
    for r in selection["roundup"]:
        meta = meta_articles[r["article_idx"]]
        art = next((a for a in articles if a.get("slug") == meta.get("slug")), None) or meta
        blurb = _generate_blurb(client, art, r["headline"])
        if not blurb:
            continue  # drop rather than ship a blank
        roundup_items.append({
            "headline": r["headline"],
            "blurb": blurb,
            "title": art.get("title", ""),
            "url": art.get("url", "#"),
            "year": (art.get("date") or "")[:4],
        })
    roundup_section = _render_roundup(roundup_items)
    print(f"  Roundup: {len(roundup_items)} item(s) with a real reference")

    # Step 5: Build email
    now = datetime.now(timezone.utc)
    week_date = now.strftime("%B %d, %Y")
    body_text = clean_text(matched_article.get("body", ""))
    excerpt = " ".join(body_text.split()[:500]) + ("..." if len(body_text.split()) > 500 else "")

    subject = f"From the archive — week of {week_date}"
    html_body = EMAIL_TEMPLATE.format(
        week_date=week_date,
        roundup_section=roundup_section,
        headline=best_headline,
        intro=intro,
        article_url=matched_article.get("url", "#"),
        article_title=matched_article.get("title", ""),
        article_date=(matched_article.get("date") or "")[:10],
        article_words=matched_article.get("word_count", 0),
        article_excerpt=excerpt,
    )

    # Save email to disk
    EMAIL_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"on_this_day_{now.strftime('%Y-%m-%d')}.html"
    email_path = EMAIL_DIR / filename
    email_path.write_text(html_body)
    print(f"  Email saved: {email_path}")

    # Save metadata for the cron log
    result = {
        "timestamp": now.isoformat(),
        "subject": subject,
        "headline": best_headline,
        "matched_article": matched_meta["title"],
        "matched_slug": matched_meta.get("slug"),
        "similarity_score": round(best_score, 4),
        "roundup_count": len(roundup_items),
        "email_file": str(email_path),
    }

    # Append to on_this_day log
    log_path = DATA_DIR / "cron" / "on_this_day.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(result) + "\n")

    print(f"  Subject: {subject}")
    return {**result, "html_body": html_body}
