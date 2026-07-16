"""Linguistic fingerprint analysis — pure Python computation, no API costs."""

import math
import re
from collections import Counter, defaultdict

from .utils import load_articles, clean_text, log, save_analysis

# Common English words for TF-IDF comparison (top ~200)
COMMON_ENGLISH = set("""
the be to of and a in that have i it for not on with he as you do at this but his
by from they we say her she or an will my one all would there their what so up out
if about who get which go me when make can like time no just him know take people
into year your good some could them see other than then now look only come its over
think also back after use two how our work first well way even new want because any
these give day most us is was are been has had did got said does than more very when
where how much many between through being before those same she been each other
while more about would like than them been their there where could people after than
through between long great even those still much before any same about under never
might think also where most during both between own those should since while another
""".split())


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    return [s.strip() for s in sentences if len(s.strip()) > 10]


def _syllable_count(word: str) -> int:
    """Estimate syllable count for a word."""
    word = word.lower().strip(".,!?;:'\"")
    if not word:
        return 0
    count = len(re.findall(r'[aeiouy]+', word))
    if word.endswith('e') and not word.endswith('le'):
        count -= 1
    return max(1, count)


def _flesch_kincaid(sentences: list[str], words: list[str]) -> dict:
    """Calculate Flesch-Kincaid readability scores."""
    total_sentences = len(sentences)
    total_words = len(words)
    total_syllables = sum(_syllable_count(w) for w in words)

    if total_sentences == 0 or total_words == 0:
        return {"reading_ease": 0, "grade_level": 0}

    asl = total_words / total_sentences  # avg sentence length
    asw = total_syllables / total_words   # avg syllables per word

    reading_ease = 206.835 - 1.015 * asl - 84.6 * asw
    grade_level = 0.39 * asl + 11.8 * asw - 15.59

    return {
        "reading_ease": round(reading_ease, 1),
        "grade_level": round(grade_level, 1),
    }


def _gunning_fog(sentences: list[str], words: list[str]) -> float:
    """Calculate Gunning fog index."""
    if not sentences or not words:
        return 0.0
    complex_words = sum(1 for w in words if _syllable_count(w) >= 3)
    return round(0.4 * (len(words) / len(sentences) + 100 * complex_words / len(words)), 1)


def _vader_sentiment(text: str) -> dict:
    """Compute VADER sentiment scores. Returns empty dict if nltk unavailable."""
    try:
        from nltk.sentiment import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()
        scores = sia.polarity_scores(text)
        return {k: round(v, 4) for k, v in scores.items()}
    except Exception:
        return {}


def analyze_article(article: dict) -> dict:
    """Compute linguistic metrics for a single article."""
    text = clean_text(article.get("body", ""))
    sentences = _split_sentences(text)
    words = [w.lower() for w in re.findall(r'\b[a-zA-Z]+\b', text)]

    if not words:
        return {}

    unique_words = set(words)
    word_freq = Counter(words)
    hapax = [w for w, c in word_freq.items() if c == 1]

    sentence_lengths = [len(re.findall(r'\b\w+\b', s)) for s in sentences]

    return {
        "slug": article.get("slug", ""),
        "date": article.get("date", ""),
        "word_count": len(words),
        "sentence_count": len(sentences),
        "avg_sentence_length": round(sum(sentence_lengths) / max(len(sentence_lengths), 1), 1),
        "sentence_length_std": round(
            (sum((x - sum(sentence_lengths) / max(len(sentence_lengths), 1)) ** 2
                 for x in sentence_lengths) / max(len(sentence_lengths), 1)) ** 0.5, 1
        ) if sentence_lengths else 0,
        "vocabulary_size": len(unique_words),
        "type_token_ratio": round(len(unique_words) / len(words), 4),
        "hapax_ratio": round(len(hapax) / len(unique_words), 4) if unique_words else 0,
        "flesch_kincaid": _flesch_kincaid(sentences, words),
        "gunning_fog": _gunning_fog(sentences, words),
        "sentiment": _vader_sentiment(text),
        "sentence_lengths": sentence_lengths,
    }


def find_distinctive_words(articles: list[dict], top_n: int = 50) -> list[dict]:
    """Find words that are distinctively frequent in the corpus vs general English."""
    corpus_freq: Counter = Counter()
    total_words = 0

    for article in articles:
        text = clean_text(article.get("body", ""))
        words = [w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', text)]
        corpus_freq.update(words)
        total_words += len(words)

    if total_words == 0:
        return []

    # Score: corpus frequency relative to expected (common English gets penalized)
    distinctive = []
    for word, count in corpus_freq.most_common(500):
        if word in COMMON_ENGLISH:
            continue
        if count < 5:
            continue
        freq = count / total_words
        distinctive.append({
            "word": word,
            "count": count,
            "frequency": round(freq * 10000, 2),  # per 10k words
        })

    return distinctive[:top_n]


def run(articles: list[dict] | None = None) -> dict:
    """Run the full linguistic analysis and save results."""
    if articles is None:
        articles = load_articles()

    if not articles:
        raise ValueError("No articles to analyze. Run `make scrape` first.")

    log.info("Analyzing %d articles...", len(articles))

    per_article = []
    all_sentence_lengths: list[int] = []

    for article in articles:
        metrics = analyze_article(article)
        if metrics:
            all_sentence_lengths.extend(metrics.pop("sentence_lengths", []))
            per_article.append(metrics)

    # Aggregate metrics
    if per_article:
        avg = lambda key: round(sum(a[key] for a in per_article) / len(per_article), 2)

        # Sentiment by year
        by_year: dict = defaultdict(list)
        for a in per_article:
            if a.get("date") and a.get("sentiment", {}).get("compound") is not None:
                by_year[a["date"][:4]].append(a["sentiment"]["compound"])
        sentiment_by_year = {
            y: round(sum(v) / len(v), 4) for y, v in sorted(by_year.items())
        }

        aggregate = {
            "total_articles": len(per_article),
            "total_words": sum(a["word_count"] for a in per_article),
            "avg_word_count": avg("word_count"),
            "avg_sentence_length": avg("avg_sentence_length"),
            "avg_type_token_ratio": avg("type_token_ratio"),
            "avg_flesch_reading_ease": round(
                sum(a["flesch_kincaid"]["reading_ease"] for a in per_article) / len(per_article), 1
            ),
            "avg_flesch_grade_level": round(
                sum(a["flesch_kincaid"]["grade_level"] for a in per_article) / len(per_article), 1
            ),
            "avg_gunning_fog": avg("gunning_fog"),
            "sentiment_by_year": sentiment_by_year,
        }
    else:
        aggregate = {}

    # Sentence length histogram (bins of 5)
    if all_sentence_lengths:
        max_len = min(max(all_sentence_lengths), 100)
        bins = list(range(0, max_len + 5, 5))
        histogram = []
        for i in range(len(bins) - 1):
            count = sum(1 for s in all_sentence_lengths if bins[i] <= s < bins[i + 1])
            histogram.append({"bin_start": bins[i], "bin_end": bins[i + 1], "count": count})
    else:
        histogram = []

    distinctive = find_distinctive_words(articles)

    result = {
        "aggregate": aggregate,
        "per_article": per_article,
        "sentence_length_histogram": histogram,
        "distinctive_words": distinctive,
    }

    path = save_analysis("linguistics.json", result)
    log.info("Linguistic analysis saved to %s", path)
    return result
