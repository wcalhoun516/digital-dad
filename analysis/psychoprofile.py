"""Psychoanalytic author profile — Anthropic API map-reduce analysis."""

import json
import os

from .utils import load_articles, clean_text, chunk_text, save_analysis, ANALYSIS_DIR

MODEL = "claude-sonnet-4-20250514"

MAP_PROMPT = """You are analyzing the writing of Dr. George Calhoun, a prolific Forbes contributor who writes about telecommunications, technology policy, ESG/sustainability, nuclear energy, and economic forces.

Read the following batch of articles and analyze each one. For each article, extract:

1. **Core intellectual concerns**: What is this article fundamentally about? What problem or question drives it?
2. **Argumentative style**: How does he build his case? (data-driven, historical analogy, contrarian takedown, policy critique, etc.)
3. **Rhetorical devices**: Notable patterns in how he writes (rhetorical questions, use of irony, appeals to authority, marshaling of evidence)
4. **Values expressed**: What does this article reveal about what he thinks matters?
5. **Emotional register**: What's the emotional tone? (passionate advocacy, cool analysis, frustrated critique, celebratory, concerned warning, etc.)

Respond as a JSON array with one object per article. Each object should have keys: "title", "concerns", "argumentative_style", "rhetorical_devices", "values", "emotional_register".

---
ARTICLES:
{articles}"""

REDUCE_PROMPT = """You are synthesizing a comprehensive intellectual and psychological profile of Dr. George Calhoun, based on detailed analyses of {count} Forbes articles he wrote between {date_range}.

Below are per-article analyses. Synthesize them into a rich, nuanced profile covering:

1. **Dominant intellectual preoccupations**: What are the 4-6 big questions or themes he returns to obsessively? Not just topics, but the underlying *questions* that seem to drive him.

2. **Rhetorical fingerprint**: How does he characteristically argue? What's his signature style? Does he have verbal tics or recurring structural patterns?

3. **Relationship to evidence and authority**: How does he use data, studies, and expert opinion? Is he deferential to consensus or a contrarian? Does he build bottom-up from data or top-down from principles?

4. **Emotional register**: What emotions drive his writing? Where does he get passionate? Where detached? What makes him angry? What gives him hope?

5. **Core values and worldview**: What does he fundamentally believe about how the world works? About technology? About institutions? About truth?

6. **Psychological fixations**: What does he return to again and again in ways that feel almost compulsive? What arguments does he seem to *need* to make?

7. **Intellectual evolution**: How has his thinking changed over time? Are there shifts in emphasis or new concerns that emerge?

8. **Blind spots and tensions**: What does he seem to avoid or miss? Are there internal contradictions in his worldview?

Write this as a compelling narrative — imagine you're writing a profile for The New Yorker about the mind behind these articles. Be specific: cite particular articles and patterns. Be psychologically insightful without being reductive.

Also provide a structured assessment with numerical scores (1-10) for these dimensions:
- Curiosity (breadth of intellectual interests)
- Contrarianism (willingness to challenge consensus)
- Technical depth (comfort with quantitative/technical material)
- Polemicism (tendency toward strong advocacy positions)
- Empathy (engagement with human impact)
- Rigor (evidentiary standards)
- Wit (humor, irony, rhetorical flair)
- Urgency (sense of stakes and timeliness)

---
PER-ARTICLE ANALYSES:
{analyses}"""


def _get_client():
    """Initialize and return the Anthropic client."""
    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError("anthropic package not installed. Run: pip install -e '.[analyze]'")

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key."
        )
    return Anthropic(api_key=api_key)


def _batch_articles(articles: list[dict], batch_size: int = 5) -> list[list[dict]]:
    """Group articles into batches for API calls."""
    batches = []
    for i in range(0, len(articles), batch_size):
        batches.append(articles[i : i + batch_size])
    return batches


def _format_batch(batch: list[dict]) -> str:
    """Format a batch of articles for the map prompt."""
    parts = []
    for article in batch:
        text = clean_text(article.get("body", ""))
        # Truncate very long articles to ~3000 words
        words = text.split()
        if len(words) > 3000:
            text = " ".join(words[:3000]) + "..."
        parts.append(
            f"### {article.get('title', 'Untitled')} ({article.get('date', 'unknown date')})\n\n{text}"
        )
    return "\n\n---\n\n".join(parts)


def estimate_cost(articles: list[dict]) -> dict:
    """Estimate API cost without making calls."""
    batches = _batch_articles(articles)
    total_input_chars = 0
    for batch in batches:
        formatted = _format_batch(batch)
        total_input_chars += len(MAP_PROMPT) + len(formatted)

    # Rough estimate: 4 chars per token, Sonnet pricing
    input_tokens = total_input_chars / 4
    output_tokens = len(batches) * 2000  # ~2000 tokens per batch response
    reduce_input = output_tokens + len(REDUCE_PROMPT)
    reduce_output = 4000

    total_input = input_tokens + reduce_input
    total_output = output_tokens + reduce_output

    # Sonnet pricing: $3/M input, $15/M output
    cost = (total_input * 3 + total_output * 15) / 1_000_000

    return {
        "num_batches": len(batches),
        "est_input_tokens": int(total_input),
        "est_output_tokens": int(total_output),
        "est_cost_usd": round(cost, 2),
    }


def run(articles: list[dict] | None = None, dry_run: bool = False) -> dict:
    """Run the psychoanalytic profile analysis."""
    if articles is None:
        articles = load_articles()

    if not articles:
        raise ValueError("No articles to analyze. Run `make scrape` first.")

    cost = estimate_cost(articles)
    print(f"Psychoprofile analysis: {len(articles)} articles in {cost['num_batches']} batches")
    print(f"Estimated cost: ~${cost['est_cost_usd']:.2f}")

    if dry_run:
        print("Dry run — no API calls made.")
        return {"dry_run": True, **cost}

    client = _get_client()
    batches = _batch_articles(articles)

    # Map phase: analyze each batch
    all_analyses = []
    for i, batch in enumerate(batches, 1):
        print(f"  Map phase: batch {i}/{len(batches)} ({len(batch)} articles)...")
        formatted = _format_batch(batch)
        prompt = MAP_PROMPT.format(articles=formatted)

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text

        # Try to parse as JSON
        try:
            # Find JSON array in response
            start = response_text.index("[")
            end = response_text.rindex("]") + 1
            batch_analyses = json.loads(response_text[start:end])
            all_analyses.extend(batch_analyses)
        except (ValueError, json.JSONDecodeError):
            # Store as raw text if not parseable
            all_analyses.append({"raw": response_text, "batch": i})
            print(f"    Warning: batch {i} response not valid JSON, stored as raw text")

    # Reduce phase: synthesize profile
    print("  Reduce phase: synthesizing profile...")

    # Date range
    dates = [a.get("date", "") for a in articles if a.get("date")]
    date_range = f"{min(dates)[:10]} to {max(dates)[:10]}" if dates else "unknown"

    analyses_text = json.dumps(all_analyses, indent=2)
    # Truncate if too long (keep within context window)
    if len(analyses_text) > 150_000:
        analyses_text = analyses_text[:150_000] + "\n... (truncated)"

    reduce_prompt = REDUCE_PROMPT.format(
        count=len(articles),
        date_range=date_range,
        analyses=analyses_text,
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": reduce_prompt}],
    )

    profile_text = response.content[0].text

    # Try to extract structured scores from the response
    dimensions = {}
    for dim in ["curiosity", "contrarianism", "technical depth", "polemicism",
                 "empathy", "rigor", "wit", "urgency"]:
        import re
        pattern = rf"{dim}[:\s]*(\d+)"
        match = re.search(pattern, profile_text, re.IGNORECASE)
        if match:
            dimensions[dim.replace(" ", "_")] = int(match.group(1))

    result = {
        "model": MODEL,
        "num_articles": len(articles),
        "date_range": date_range,
        "profile_narrative": profile_text,
        "dimensions": dimensions,
        "per_article_analyses": all_analyses,
        "cost_estimate": cost,
    }

    # Save JSON
    path = save_analysis("psychoprofile.json", result)
    print(f"Psychoprofile JSON saved to {path}")

    # Save readable markdown
    md_path = ANALYSIS_DIR / "psychoprofile.md"
    md_content = f"# Psychoanalytic Author Profile: Dr. George Calhoun\n\n"
    md_content += f"*Based on analysis of {len(articles)} Forbes articles ({date_range})*\n\n"
    md_content += f"*Model: {MODEL}*\n\n---\n\n"
    md_content += profile_text
    if dimensions:
        md_content += "\n\n---\n\n## Personality Dimensions\n\n"
        for dim, score in dimensions.items():
            bar = "█" * score + "░" * (10 - score)
            md_content += f"- **{dim.replace('_', ' ').title()}**: {bar} {score}/10\n"
    md_path.write_text(md_content)
    print(f"Psychoprofile narrative saved to {md_path}")

    return result
