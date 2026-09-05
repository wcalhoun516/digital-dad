"""Track Record — extract falsifiable predictions from the corpus.

Passes each article through the conductor to extract claims about the future,
then optionally runs a second LLM pass to produce speculative verdicts.

Results are stored in ``data/analysis/predictions.json`` with each prediction
carrying a status field: ``pending``, ``vindicated``, ``wrong``, ``mixed``,
or ``unfalsifiable``. The family can override any LLM verdict by editing the
JSON directly — the ``verdict_source`` field distinguishes ``"llm"`` from
``"manual"``.

Fits the existing fingerprint-skip pattern used by all analysis modules.
"""

import json
import time
from datetime import datetime, timezone

from .utils import DATA_DIR, clean_text, load_articles, save_analysis

CONDUCTOR_URL = "http://127.0.0.1:8080/v1"

EXTRACT_PROMPT = """You are analyzing Forbes articles by Dr. George Calhoun to extract every falsifiable prediction or forward-looking claim.

IMPORTANT: The article was published on **{date}**. Only extract claims that are about the future RELATIVE TO THAT DATE. A statement like "inflation will rise" written in April 2021 is a prediction about what happens after April 2021.

For each prediction found, output a JSON object with:
- "claim": the prediction in his exact words (quote directly from the text — preserve his phrasing)
- "context": 1-sentence summary of what the article was arguing
- "prediction_date": "{date}" (the date this prediction was published — copy this exactly)
- "target_date_or_horizon": when this prediction should resolve (e.g. "2025", "within 5 years", "by end of decade", "near-term", "unspecified"). Be as specific as the text allows.
- "confidence_language": one of "hedged", "confident", or "certain" — based on how he phrased it. Look for hedging words ("may", "could", "might", "if") vs. confident language ("will", "is going to", "inevitably") vs. certain ("there is no doubt", "certainly").
- "topic": short topic label (e.g. "5G spectrum", "nuclear energy", "ESG governance", "inflation", "China trade", "Fed policy", "Tesla valuation")

Be thorough. Look for:
- Explicit forecasts ("X will happen")
- Implied predictions ("this trend is unsustainable" = predicting reversal)
- Conditional predictions ("if X, then Y will follow")
- Market/economic calls ("this stock is overvalued" = predicting decline)
- Policy predictions ("this regulation will backfire")

If an article contains NO falsifiable predictions, return an empty array [].

Return ONLY a JSON array. No commentary, no markdown fences.

---
ARTICLE TITLE: {title}
ARTICLE DATE: {date}

{body}"""

VERDICT_PROMPT = """You are auditing predictions made by Dr. George Calhoun in Forbes articles. Your job is to determine whether each prediction turned out to be RIGHT, WRONG, or remains unresolved.

IMPORTANT INSTRUCTIONS:
- Use your knowledge of what actually happened in the world to verify each prediction.
- The "prediction_date" tells you WHEN he made the call. Judge based on what happened AFTER that date.
- Be rigorous: a prediction is "vindicated" only if the core claim came true, not just tangentially related events.
- A prediction is "wrong" if events clearly contradicted it.
- Use "mixed" if he was partially right — e.g., right direction but wrong magnitude, or right short-term but wrong long-term.
- Use "pending" ONLY if the prediction is about a future date that hasn't arrived yet (after {current_date}) or if you genuinely cannot determine the outcome.
- Use "unfalsifiable" for claims too vague to ever judge.

For each prediction, output a JSON object with:
- "claim": (echo back the claim exactly as given)
- "verdict": one of "pending", "vindicated", "wrong", "mixed", "unfalsifiable"
- "verdict_reasoning": 2-4 sentences explaining what actually happened and why the prediction was right/wrong. Cite specific real-world events, data, or outcomes.
- "verdict_confidence": "low", "medium", or "high" — how confident you are in this assessment

Current date: {current_date}

---
PREDICTIONS TO AUDIT:
{predictions}"""


def _get_client():
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install -e '.[analyze]'")
    return OpenAI(base_url=CONDUCTOR_URL, api_key="local")


def _call(client, prompt: str, max_tokens: int = 4096, tier: int = 2) -> str:
    extra = {"tier": tier, "function": "text"}
    if tier >= 3:
        extra["allow_remote"] = True
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="auto",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                extra_body=extra,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            if attempt < 2:
                print(f"    Retry {attempt + 1}/3 after error: {exc}", flush=True)
                time.sleep(5 * (attempt + 1))
            else:
                raise


def _extract_predictions(client, article: dict, tier: int = 2) -> list[dict]:
    """Extract predictions from a single article."""
    body = clean_text(article.get("body", ""))
    words = body.split()
    if len(words) > 3000:
        body = " ".join(words[:3000]) + "..."

    prompt = EXTRACT_PROMPT.format(
        title=article.get("title", "Untitled"),
        date=article.get("date", "unknown"),
        body=body,
    )

    text = _call(client, prompt, max_tokens=2048, tier=tier)

    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        predictions = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return []

    # Tag each prediction with source article metadata
    for p in predictions:
        p["article_slug"] = article.get("slug", "")
        p["article_title"] = article.get("title", "")
        p["article_date"] = article.get("date", "")
        p["article_url"] = article.get("url", "")
        # Ensure prediction_date is set (LLM should echo it, but fallback to article date)
        if not p.get("prediction_date"):
            p["prediction_date"] = article.get("date", "")
        p["status"] = "pending"
        p["verdict_source"] = None
        p["verdict_reasoning"] = None

    return predictions


def _run_verdicts(client, predictions: list[dict], tier: int = 2) -> list[dict]:
    """Run LLM verdict pass over extracted predictions."""
    if not predictions:
        return predictions

    # Process in batches of 15 (smaller for T3 to stay within context limits)
    batch_size = 15
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for start in range(0, len(predictions), batch_size):
        batch = predictions[start:start + batch_size]
        batch_num = start // batch_size + 1
        total_batches = (len(predictions) + batch_size - 1) // batch_size
        print(f"  Verdict batch {batch_num}/{total_batches}...", flush=True)

        claims_text = json.dumps(
            [{"claim": p["claim"],
              "prediction_date": p.get("prediction_date") or p["article_date"],
              "article_title": p.get("article_title", ""),
              "topic": p.get("topic", ""),
              "target_date_or_horizon": p.get("target_date_or_horizon", ""),
              "confidence_language": p.get("confidence_language", "")}
             for p in batch],
            indent=2,
        )

        prompt = VERDICT_PROMPT.format(
            current_date=current_date,
            predictions=claims_text,
        )

        text = _call(client, prompt, max_tokens=4096, tier=tier)

        try:
            arr_start = text.index("[")
            arr_end = text.rindex("]") + 1
            verdicts = json.loads(text[arr_start:arr_end])
        except (ValueError, json.JSONDecodeError):
            print(f"    Warning: verdict batch {batch_num} response not valid JSON", flush=True)
            continue

        # Match verdicts back to predictions by claim text
        verdict_map = {v.get("claim", ""): v for v in verdicts}
        for p in batch:
            v = verdict_map.get(p["claim"])
            if v and v.get("verdict") in ("pending", "vindicated", "wrong", "mixed", "unfalsifiable"):
                p["llm_verdict"] = v["verdict"]
                p["llm_verdict_reasoning"] = v.get("verdict_reasoning", "")
                p["llm_verdict_confidence"] = v.get("verdict_confidence", "low")
                # Keep status as pending — LLM verdict is advisory, not authoritative
                p["verdict_source"] = "llm"
                p["verdict_reasoning"] = v.get("verdict_reasoning", "")

    return predictions


def _save_partial(predictions, articles, include_verdicts, duration):
    """Save current progress so it survives crashes."""
    result = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "num_articles": len(articles),
        "num_predictions": len(predictions),
        "duration_s": round(duration, 1),
        "include_verdicts": include_verdicts,
        "partial": True,
        "aggregate": {},
        "predictions": predictions,
    }
    save_analysis("predictions.json", result)
    print(f"    [checkpoint: {len(predictions)} predictions saved]", flush=True)


def run(
    articles: list[dict] | None = None,
    include_verdicts: bool = True,
    router: str = "conductor_local",
) -> dict:
    """Extract predictions from the corpus and optionally run LLM verdicts.

    Args:
        articles: Pre-loaded article list, or None to load from disk.
        include_verdicts: If True, run a second LLM pass for advisory verdicts.
        router: "conductor_local" (Tier 2, free) or "conductor_remote" (Tier 3).
    """
    if articles is None:
        articles = load_articles()

    if not articles:
        raise ValueError("No articles to analyze. Run `make scrape` first.")

    tier = 2 if router == "conductor_local" else 3
    tier_label = "T2 local (free)" if tier == 2 else "T3 remote (OpenRouter — costs money)"
    print(f"Prediction extraction: {len(articles)} articles via {tier_label}")

    client = _get_client()
    run_start = time.time()

    # Resume from prior run if one exists (skip already-processed articles)
    pred_path = DATA_DIR / "analysis" / "predictions.json"
    all_predictions = []
    done_slugs = set()
    if pred_path.exists():
        try:
            prior = json.loads(pred_path.read_text())
            all_predictions = prior.get("predictions", [])
            done_slugs = {p.get("article_slug") for p in all_predictions}
            if done_slugs:
                print(f"  Resuming: {len(done_slugs)} articles already processed, {len(all_predictions)} predictions cached")
        except (json.JSONDecodeError, KeyError):
            pass

    for i, article in enumerate(articles, 1):
        slug = article.get("slug", "")
        if slug and slug in done_slugs:
            continue
        print(
            f"  [{i}/{len(articles)}] {article.get('title', 'Untitled')[:60]}...",
            flush=True,
        )
        try:
            preds = _extract_predictions(client, article, tier=tier)
        except Exception as exc:
            print(f"    ✗ Failed: {exc}", flush=True)
            continue
        if preds:
            print(f"    → {len(preds)} prediction(s) found")
        all_predictions.extend(preds)

        # Save incrementally every 10 articles so progress isn't lost
        if i % 10 == 0:
            _save_partial(all_predictions, articles, include_verdicts=False, duration=time.time() - run_start)

    print(f"\nExtracted {len(all_predictions)} predictions from {len(articles)} articles")

    if include_verdicts and all_predictions:
        print("\nRunning LLM verdict pass (advisory only — clearly labeled)...")
        all_predictions = _run_verdicts(client, all_predictions, tier=tier)

    duration = round(time.time() - run_start, 1)

    # Compute aggregate stats
    by_topic = {}
    by_confidence = {}
    by_year = {}
    for p in all_predictions:
        topic = p.get("topic", "other")
        by_topic[topic] = by_topic.get(topic, 0) + 1
        conf = p.get("confidence_language", "unknown")
        by_confidence[conf] = by_confidence.get(conf, 0) + 1
        year = (p.get("article_date") or "")[:4]
        if year:
            by_year[year] = by_year.get(year, 0) + 1

    llm_verdicts_summary = {}
    for p in all_predictions:
        v = p.get("llm_verdict", "pending")
        llm_verdicts_summary[v] = llm_verdicts_summary.get(v, 0) + 1

    result = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "num_articles": len(articles),
        "num_predictions": len(all_predictions),
        "duration_s": duration,
        "include_verdicts": include_verdicts,
        "aggregate": {
            "by_topic": dict(sorted(by_topic.items(), key=lambda x: -x[1])),
            "by_confidence": by_confidence,
            "by_year": dict(sorted(by_year.items())),
            "llm_verdicts": llm_verdicts_summary,
        },
        "predictions": all_predictions,
    }

    path = save_analysis("predictions.json", result)
    print(f"\nPredictions saved to {path} ({duration}s)")
    print(f"  {len(all_predictions)} predictions across {len(by_topic)} topics")
    if llm_verdicts_summary:
        print(f"  LLM verdicts: {llm_verdicts_summary}")

    return result
