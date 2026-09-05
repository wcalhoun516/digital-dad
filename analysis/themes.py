"""Theme analysis — TF-IDF clustering + keyword extraction + topic-over-time."""

from collections import defaultdict

from .utils import clean_text, load_articles, log, save_analysis


def run(articles: list[dict] | None = None, min_k: int = 4, max_k: int = 10) -> dict:
    """Cluster articles by theme using TF-IDF + KMeans."""
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import silhouette_score

    if articles is None:
        articles = load_articles()

    if not articles:
        raise ValueError("No articles to analyze. Run `make scrape` first.")

    log.info("Clustering %d articles into themes...", len(articles))

    # Prepare documents
    docs = []
    valid_articles = []
    for article in articles:
        text = clean_text(article.get("body", ""))
        if len(text) > 100:
            docs.append(text)
            valid_articles.append(article)

    if len(docs) < min_k:
        log.warning("Only %d articles — too few for clustering. Using 2 clusters.", len(docs))
        min_k = max_k = 2

    # TF-IDF vectorization
    vectorizer = TfidfVectorizer(
        max_features=5000,
        stop_words="english",
        min_df=2,
        max_df=0.85,
        ngram_range=(1, 2),
    )
    tfidf_matrix = vectorizer.fit_transform(docs)
    feature_names = vectorizer.get_feature_names_out()

    # Find optimal k via silhouette score
    best_k = min_k
    best_score = -1

    if min_k < max_k:
        for k in range(min_k, min(max_k + 1, len(docs))):
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = km.fit_predict(tfidf_matrix)
            if len(set(labels)) > 1:
                score = silhouette_score(tfidf_matrix, labels, sample_size=min(1000, len(docs)))
                log.debug("k=%d: silhouette=%.3f", k, score)
                if score > best_score:
                    best_score = score
                    best_k = k

    log.info("Selected k=%d (silhouette=%.3f)", best_k, best_score)

    # Final clustering
    km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    labels = km.fit_predict(tfidf_matrix)

    # Extract top keywords per cluster
    clusters = []
    for cluster_id in range(best_k):
        cluster_indices = [i for i, label in enumerate(labels) if label == cluster_id]
        if not cluster_indices:
            continue

        # Get top TF-IDF terms for this cluster
        centroid = km.cluster_centers_[cluster_id]
        top_indices = centroid.argsort()[-15:][::-1]
        keywords = [str(feature_names[i]) for i in top_indices]

        # Representative articles (closest to centroid)
        from sklearn.metrics.pairwise import cosine_similarity
        cluster_docs = tfidf_matrix[cluster_indices]
        similarities = cosine_similarity(cluster_docs, centroid.reshape(1, -1)).flatten()
        top_article_indices = similarities.argsort()[-5:][::-1]

        representative = []
        for idx in top_article_indices:
            article = valid_articles[cluster_indices[idx]]
            representative.append({
                "slug": article.get("slug", ""),
                "title": article.get("title", ""),
                "date": article.get("date", ""),
                "similarity": round(float(similarities[idx]), 3),
            })

        clusters.append({
            "id": cluster_id,
            "size": len(cluster_indices),
            "keywords": keywords,
            "representative_articles": representative,
            # Auto-label from top keywords
            "label": " / ".join(keywords[:3]).title(),
        })

    # Assign cluster labels to articles
    article_clusters = []
    for i, article in enumerate(valid_articles):
        article_clusters.append({
            "slug": article.get("slug", ""),
            "title": article.get("title", ""),
            "date": article.get("date", ""),
            "url": article.get("url", ""),
            "word_count": article.get("word_count", 0),
            "cluster_id": int(labels[i]),
            "cluster_label": clusters[int(labels[i])]["label"] if int(labels[i]) < len(clusters) else "",
        })

    # Topic over time — bin by quarter
    topic_timeline = _build_timeline(article_clusters, best_k)

    result = {
        "num_clusters": best_k,
        "silhouette_score": round(best_score, 3),
        "clusters": clusters,
        "articles": article_clusters,
        "topic_timeline": topic_timeline,
    }

    path = save_analysis("themes.json", result)
    log.info("Theme analysis saved to %s", path)
    return result


def _build_timeline(article_clusters: list[dict], num_clusters: int) -> list[dict]:
    """Build a topic-over-time timeline binned by quarter."""
    quarters: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for article in article_clusters:
        date = article.get("date", "")
        if not date or len(date) < 7:
            continue
        year = date[:4]
        month = int(date[5:7])
        quarter = f"{year}-Q{(month - 1) // 3 + 1}"
        quarters[quarter][article["cluster_id"]] += 1

    timeline = []
    for quarter in sorted(quarters.keys()):
        entry = {"quarter": quarter, "counts": {}}
        for cluster_id in range(num_clusters):
            entry["counts"][str(cluster_id)] = quarters[quarter].get(cluster_id, 0)
        entry["total"] = sum(entry["counts"].values())
        timeline.append(entry)

    return timeline
