"""Psychoanalytic author profile — map-reduce LLM analysis.

All LLM calls route through the local-llm-conductor at
http://127.0.0.1:8080/v1 using its OpenAI-compatible API.

Routing modes:
  conductor_local   → Tier 2 (local Ollama reasoning model) — free
  conductor_remote  → Tier 3 (remote model via OpenRouter) — costs money

The conductor classifies and picks the actual model; this module just asks
for ``function="text"`` and the requested tier.
"""

import json
import time
from datetime import datetime, timezone

from .utils import load_articles, clean_text, log, save_analysis, ANALYSIS_DIR, DATA_DIR

CONDUCTOR_URL = "http://127.0.0.1:8080/v1"
RUNS_LOG = DATA_DIR / "analysis" / "runs.jsonl"

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


# ---------------------------------------------------------------------------
# Client setup
# ---------------------------------------------------------------------------

def _get_conductor_client():
    """Initialize OpenAI-compatible conductor client."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install -e '.[analyze]'")
    return OpenAI(base_url=CONDUCTOR_URL, api_key="local")


def _call_conductor(client, prompt: str, max_tokens: int, tier: int) -> tuple[str, int, int, str]:
    """Call via conductor OpenAI-compatible endpoint.

    Returns (text, input_tokens, output_tokens, model_used). The conductor
    picks the actual model based on tier + function="text"; we capture which
    one it ended up choosing for the run record.
    """
    response = client.chat.completions.create(
        model="auto",  # ignored — conductor classifies on (tier, function)
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"tier": tier, "function": "text"},
    )
    text = response.choices[0].message.content or ""
    usage = response.usage
    # The conductor injects {"conductor": {"model_used": "..."}} into the response.
    # The OpenAI SDK exposes unknown fields via model_extra (pydantic v2).
    extra = getattr(response, "model_extra", None) or {}
    conductor_meta = extra.get("conductor") or {}
    model_used = conductor_meta.get("model_used") or response.model or "unknown"
    return text, usage.prompt_tokens, usage.completion_tokens, model_used


# ---------------------------------------------------------------------------
# Run logging
# ---------------------------------------------------------------------------

def _log_run(entry: dict) -> None:
    """Append a run record to runs.jsonl."""
    RUNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _batch_articles(articles: list[dict], batch_size: int = 5) -> list[list[dict]]:
    """Group articles into batches for API calls."""
    return [articles[i : i + batch_size] for i in range(0, len(articles), batch_size)]


def _format_batch(batch: list[dict]) -> str:
    """Format a batch of articles for the map prompt."""
    parts = []
    for article in batch:
        text = clean_text(article.get("body", ""))
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
    total_input_chars = sum(
        len(MAP_PROMPT) + len(_format_batch(b)) for b in batches
    )
    input_tokens = total_input_chars / 4
    output_tokens = len(batches) * 2000
    reduce_input = output_tokens + len(REDUCE_PROMPT)
    reduce_output = 4000
    total_input = input_tokens + reduce_input
    total_output = output_tokens + reduce_output
    cost = (total_input * 3 + total_output * 15) / 1_000_000
    return {
        "num_batches": len(batches),
        "est_input_tokens": int(total_input),
        "est_output_tokens": int(total_output),
        "est_cost_usd": round(cost, 2),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    articles: list[dict] | None = None,
    dry_run: bool = False,
    router: str = "conductor_local",  # "conductor_local" | "conductor_remote"
    corpus_fingerprint: str = "",
) -> dict:
    """Run the psychoanalytic profile analysis.

    Args:
        articles: Pre-loaded article list, or None to load from disk.
        dry_run: Estimate cost only, no API calls.
        router: "conductor_local" (Tier 2, free) or "conductor_remote" (Tier 3).
    """
    if router not in ("conductor_local", "conductor_remote"):
        raise ValueError(
            f"router must be 'conductor_local' or 'conductor_remote', got {router!r}"
        )

    if articles is None:
        articles = load_articles()

    if not articles:
        raise ValueError("No articles to analyze. Run `make scrape` first.")

    cost = estimate_cost(articles)
    log.info(
        "Psychoprofile analysis: %d articles in %d batches",
        len(articles), cost["num_batches"],
    )

    if router == "conductor_local":
        log.info("Routing: conductor Tier 2 (local LLM) — cost: ~$0.00")
    else:
        log.info(
            "Routing: conductor Tier 3 (remote) — est. ~$%.2f (depends on T3 chain pick)",
            cost["est_cost_usd"],
        )

    if dry_run:
        log.info("Dry run — no API calls made.")
        return {"dry_run": True, **cost}

    tier = 2 if router == "conductor_local" else 3
    client = _get_conductor_client()
    models_used: set[str] = set()

    def call(prompt: str, max_tokens: int) -> tuple[str, int, int]:
        text, in_tok, out_tok, model_used = _call_conductor(
            client, prompt, max_tokens, tier
        )
        models_used.add(model_used)
        return text, in_tok, out_tok

    run_start = time.time()
    batches = _batch_articles(articles)
    total_input_tokens = 0
    total_output_tokens = 0
    all_analyses = []

    # Map phase
    for i, batch in enumerate(batches, 1):
        log.debug("  Map phase: batch %d/%d (%d articles)...", i, len(batches), len(batch))
        formatted = _format_batch(batch)
        prompt = MAP_PROMPT.format(articles=formatted)

        response_text, in_tok, out_tok = call(prompt, 4096)
        total_input_tokens += in_tok
        total_output_tokens += out_tok

        batch_cost = (in_tok * 3 + out_tok * 15) / 1_000_000
        running_cost = (total_input_tokens * 3 + total_output_tokens * 15) / 1_000_000
        log.debug(
            "    tokens: %s in / %s out  batch: $%.4f  running: $%.4f",
            f"{in_tok:,}", f"{out_tok:,}", batch_cost, running_cost,
        )

        try:
            start = response_text.index("[")
            end = response_text.rindex("]") + 1
            batch_analyses = json.loads(response_text[start:end])
            all_analyses.extend(batch_analyses)
        except (ValueError, json.JSONDecodeError):
            all_analyses.append({"raw": response_text, "batch": i})
            log.warning("    batch %d response not valid JSON, stored as raw text", i)

    log.info(
        "  Map phase complete: %s in / %s out tokens",
        f"{total_input_tokens:,}", f"{total_output_tokens:,}",
    )

    # Reduce phase
    log.info("  Reduce phase: synthesizing profile...")
    dates = [a.get("date", "") for a in articles if a.get("date")]
    date_range = f"{min(dates)[:10]} to {max(dates)[:10]}" if dates else "unknown"

    analyses_text = json.dumps(all_analyses, indent=2)
    if len(analyses_text) > 150_000:
        analyses_text = analyses_text[:150_000] + "\n... (truncated)"

    reduce_prompt = REDUCE_PROMPT.format(
        count=len(articles),
        date_range=date_range,
        analyses=analyses_text,
    )

    profile_text, in_tok, out_tok = call(reduce_prompt, 8192)
    total_input_tokens += in_tok
    total_output_tokens += out_tok
    total_cost = (total_input_tokens * 3 + total_output_tokens * 15) / 1_000_000
    run_duration = round(time.time() - run_start, 1)

    log.debug("  Reduce phase: %s in / %s out", f"{in_tok:,}", f"{out_tok:,}")
    log.info(
        "  === TOTAL: $%.4f (%s in / %s out) in %ss ===",
        total_cost, f"{total_input_tokens:,}", f"{total_output_tokens:,}", run_duration,
    )

    # Extract dimension scores
    dimensions = {}
    import re
    for dim in ["curiosity", "contrarianism", "technical depth", "polemicism",
                "empathy", "rigor", "wit", "urgency"]:
        pattern = rf"{dim}[:\s]*(\d+)"
        match = re.search(pattern, profile_text, re.IGNORECASE)
        if match:
            dimensions[dim.replace(" ", "_")] = int(match.group(1))

    model_used_str = ", ".join(sorted(models_used)) if models_used else "unknown"

    result = {
        "model": model_used_str,
        "router": router,
        "num_articles": len(articles),
        "date_range": date_range,
        "profile_narrative": profile_text,
        "dimensions": dimensions,
        "per_article_analyses": all_analyses,
        "cost_estimate": cost,
        "actual_cost_usd": round(total_cost, 4),
    }

    # Log run
    _log_run({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "module": "psychoprofile",
        "router": router,
        "model": model_used_str,
        "num_articles": len(articles),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": round(total_cost, 4),
        "duration_s": run_duration,
        "corpus_fingerprint": corpus_fingerprint,
    })

    # Save JSON
    path = save_analysis("psychoprofile.json", result)
    log.info("Psychoprofile JSON saved to %s", path)

    # Save readable markdown
    md_path = ANALYSIS_DIR / "psychoprofile.md"
    md_content = f"# Psychoanalytic Author Profile: Dr. George Calhoun\n\n"
    md_content += f"*Based on analysis of {len(articles)} Forbes articles ({date_range})*\n\n"
    md_content += f"*Model: {model_used_str} via {router}*\n\n---\n\n"
    md_content += profile_text
    if dimensions:
        md_content += "\n\n---\n\n## Personality Dimensions\n\n"
        for dim, score in dimensions.items():
            bar = "█" * score + "░" * (10 - score)
            md_content += f"- **{dim.replace('_', ' ').title()}**: {bar} {score}/10\n"
    md_path.write_text(md_content)
    log.info("Psychoprofile narrative saved to %s", md_path)

    return result
