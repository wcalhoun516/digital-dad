# scraper/

Three-tier discovery + extraction of Dr. George Calhoun's Forbes articles
(Playwright → sitemap → Wayback). See `docs/architecture.md` for the full flow.

- `python -m scraper` — discover + extract; writes `data/raw/*.json` and updates
  `data/manifest.json`.

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
