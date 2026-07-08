# scraper/

Three-tier discovery + extraction of Dr. George Calhoun's Forbes articles
(Playwright → sitemap → Wayback). See `docs/architecture.md` for the full flow.

- `python -m scraper` — discover + extract; writes `data/raw/*.json` and updates
  `data/manifest.json`.

## Per-article metadata (roadmap #10)

`extract_article` (Tier 2, `scraper/forbes_requests.py`) records the core fields
(`url`, `title`, `date`, `body`, `tags`, `word_count`) plus a set of **richer metadata**
fields pulled from the article page by the pure, offline-testable `extract_metadata(soup, url)`:

| Field | Source (in preference order) |
|-------|------------------------------|
| **canonical_url** | `<link rel="canonical">` → `<meta property="og:url">` → the page URL (relatives resolved against it). |
| **published_date** | `<meta property="article:published_time">` → `<time datetime>` → the `/YYYY/MM/DD/` URL path. |
| **updated_date** | `<meta property="article:modified_time">` → `<meta property="og:updated_time">` → `""` (empty when the page advertises no revision). |
| **section** | `<meta property="article:section">` → the last link in a `[class*="breadcrumb"]` nav → `""`. |
| **byline** / **byline_variants** | `<meta name="author">`, `<meta property="article:author">` (URL-valued ones skipped), and `[rel="author"]`/`[class*="author"]` elements — deduped in first-seen order; `byline` is the first variant. |

The helpers are pure (they take an already-parsed BeautifulSoup tree), so they're covered
by offline fixtures in `tests/test_forbes_metadata.py`. Existing raw JSON only back-fills
these fields on the **next** `make scrape` — this is an extraction change, not a re-scrape.

## Manifest integrity check (`make manifest-check`)

`scraper/manifest_check.py` audits `data/manifest.json` against `data/raw/*.json` and reports
drift. The auditing logic (`audit_manifest`) is pure and offline-testable; `run` wires it to
the real paths.

```bash
make manifest-check               # human-readable report (always exits 0)
make manifest-check ARGS=--strict # exit non-zero if any issue is found (for CI/pre-commit)
make manifest-check ARGS=--json   # machine-readable report
```

What it checks:

| Finding | Meaning |
|---------|---------|
| **duplicate slugs** | Two+ manifest entries share a `slug` (point at the same `raw/<slug>.json`). |
| **duplicate urls** | Two+ entries share a `url` (shouldn't happen given URL-keyed dedup). |
| **duplicate content_hash** | Two+ entries have identical body hashes — same article under different slugs/urls. |
| **missing content_hash** | Entry has no `content_hash` (entries scraped before that field existed). |
| **entries missing file field** | Entry has no `file` pointer. |
| **referenced files absent on disk** | An entry's `file` doesn't exist under `data/raw/`. |
| **orphaned raw files** | A `data/raw/*.json` file no manifest entry references. |
| **count drift** | `total_articles` disagrees with the actual number of entries. |

### Why duplicate slugs happen

`scraper/__main__.py` de-duplicates manifest entries **by `url`**, not by `slug`
(`existing_idx = next(i for i, a in enumerate(...) if a["url"] == url)`). When the same article
is rediscovered under a *different* URL (e.g. an `http://` vs `https://` form, or a Wayback
variant), it slugifies to the same filename — so the raw file is overwritten, but a **second
manifest entry is appended**. The current corpus carries 23 such duplicate-slug entries (~12%).

This checker only *reports* the drift; it does not mutate the manifest. De-duplicating the
manifest (and switching the scraper's dedup key to `slug`, or normalizing URLs before the
existence check) is a separate, owner-reviewed change.

## Coverage audit (`make coverage-audit`)

Where `manifest-check` looks *inward* (manifest vs the files on disk), `coverage-audit`
(`scraper/coverage_audit.py`, roadmap #9) looks *outward*: it compares the URLs we **have** in
the manifest against a **discovered** set — the author's full known Forbes footprint — and
reports what the archive is still missing, and *when*.

```bash
make coverage-audit                        # human-readable report (always exits 0)
make coverage-audit ARGS=--strict          # exit non-zero if any article is missing (CI)
make coverage-audit ARGS=--json            # machine-readable report
make coverage-audit ARGS="--urls-file urls.txt"  # audit against an offline URL list (no network)
```

**Discovery source.** By default `run()` queries the Wayback CDX index
(`wayback.discover_urls_from_wayback()`) for every archived
`forbes.com/sites/georgecalhoun/*` URL. Because that hits the network (and can be blocked or
empty in an unattended run), the source is an **injectable seam**: pass a `discover` callable
in code, or `--urls-file` on the CLI to audit against a saved URL dump. The pure comparison
(`audit_coverage`) takes the manifest articles + a URL list, so it is fully offline-testable.

**How URLs are matched.** Forbes author URLs encode the publish date and slug in the path
(`/sites/georgecalhoun/YYYY/MM/DD/slug/`). `parse_article_url()` reduces each URL — from either
side — to a canonical, scheme-/`www`-/query-insensitive key, so `http` vs `https`, `www` vs
bare, and tracking params all collapse to one article.

What it reports:

| Field | Meaning |
|-------|---------|
| **coverage_ratio** | Fraction of discovered articles present in the manifest. |
| **missing_urls** | Discovered articles absent from the manifest (date + slug + URL), the scrape backlog. |
| **gap_months** | Months (`YYYY-MM`) where at least one discovered article is missing — the missing date ranges. |
| **by_month** | Per-month `{have, discovered, missing}` counts. |
| **extra_urls** | Manifest articles *not* in the discovered set (usually discovery gaps, not corpus errors). |
| **unparsed_\*** | URLs on either side that didn't match the author-article pattern (skipped, surfaced for transparency). |

Report-only by design — it never mutates the manifest or triggers a scrape; feeding the
`missing_urls` back into `python -m scraper` is a separate, owner-driven step.
