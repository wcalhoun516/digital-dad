"""The dashboard must render the corpus, not the manifest's duplicate-URL twins.

The scraper historically upserted manifest entries on **URL**, so an article rediscovered
under a variant URL appended a second entry naming the *same* raw file. PR #77 fixed this
for the analysis pipeline by wiring ``analysis.utils.dedupe_manifest_entries()`` into
``load_articles()``, but ``viz/build_dashboard.py`` injects ``data/manifest.json`` on its
own path — verbatim — so the page the family opens still counted the twins: the header read
"199 articles analyzed" for a 176-article corpus and the Raw Corpus tab drew 23 duplicate
rows.

These tests pin the injection boundary: whatever reaches ``__MANIFEST_DATA__`` carries one
entry per raw file, and ``total_articles`` agrees with it.
"""

import json
from pathlib import Path

from viz import build_dashboard

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PLACEHOLDER = "/*__MANIFEST_DATA__*/"

# The http/https twin pair that the real corpus carries 23 of.
TWINS = {
    "total_articles": 3,
    "articles": [
        {
            "slug": "europes-hamiltonian-moment",
            "url": "http://www.forbes.com/sites/georgecalhoun/2020/05/26/europes-hamiltonian-moment/",
            "file": "raw/europes-hamiltonian-moment.json",
            "date": "2020-05-26",
        },
        {
            "slug": "europes-hamiltonian-moment",
            "url": "https://www.forbes.com/sites/georgecalhoun/2020/05/26/europes-hamiltonian-moment/",
            "file": "raw/europes-hamiltonian-moment.json",
            "date": "2020-05-26",
        },
        {
            "slug": "the-fed-blinked",
            "url": "https://www.forbes.com/sites/georgecalhoun/2021/03/01/the-fed-blinked/",
            "file": "raw/the-fed-blinked.json",
            "date": "2021-03-01",
        },
    ],
}


# --- the pure transform ----------------------------------------------------------


def test_twin_entries_collapse_to_one_article_per_raw_file():
    payload = build_dashboard.dedupe_manifest_payload(TWINS)

    files = [a["file"] for a in payload["articles"]]
    assert files == [
        "raw/europes-hamiltonian-moment.json",
        "raw/the-fed-blinked.json",
    ]


def test_total_articles_matches_the_deduped_list():
    payload = build_dashboard.dedupe_manifest_payload(TWINS)

    assert payload["total_articles"] == 2
    assert payload["total_articles"] == len(payload["articles"])


def test_first_seen_entry_wins_so_the_kept_url_is_stable():
    payload = build_dashboard.dedupe_manifest_payload(TWINS)

    assert payload["articles"][0]["url"].startswith("http://")


def test_deduping_leaves_the_input_payload_untouched():
    original = json.loads(json.dumps(TWINS))

    build_dashboard.dedupe_manifest_payload(TWINS)

    assert TWINS == original


def test_other_manifest_keys_are_preserved():
    payload = build_dashboard.dedupe_manifest_payload(
        {"scraped_at": "2026-08-17T00:00:00Z", "total_articles": 1, "articles": []}
    )

    assert payload["scraped_at"] == "2026-08-17T00:00:00Z"


def test_a_payload_without_articles_is_passed_through():
    payload = build_dashboard.dedupe_manifest_payload({"total_articles": 0})

    assert payload == {"total_articles": 0}


# --- the injection boundary ------------------------------------------------------


def test_injected_manifest_is_deduped(tmp_path, monkeypatch):
    template = tmp_path / "template.html"
    template.write_text(f"const MANIFEST_DATA = {MANIFEST_PLACEHOLDER};")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(TWINS))
    output = tmp_path / "index.html"

    monkeypatch.setattr(build_dashboard, "TEMPLATE_PATH", template)
    monkeypatch.setattr(build_dashboard, "OUTPUT_PATH", output)
    monkeypatch.setattr(
        build_dashboard, "PLACEHOLDERS", {MANIFEST_PLACEHOLDER: manifest}
    )
    build_dashboard.build()

    inlined = json.loads(
        output.read_text().removeprefix("const MANIFEST_DATA = ").removesuffix(";")
    )
    assert inlined["total_articles"] == 2
    assert len(inlined["articles"]) == 2


def test_a_manifest_that_is_not_an_object_still_builds(tmp_path, monkeypatch):
    """A hand-edited/truncated manifest must not take the whole dashboard build down."""
    template = tmp_path / "template.html"
    template.write_text(f"const MANIFEST_DATA = {MANIFEST_PLACEHOLDER};")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("null")
    output = tmp_path / "index.html"

    monkeypatch.setattr(build_dashboard, "TEMPLATE_PATH", template)
    monkeypatch.setattr(build_dashboard, "OUTPUT_PATH", output)
    monkeypatch.setattr(
        build_dashboard, "PLACEHOLDERS", {MANIFEST_PLACEHOLDER: manifest}
    )
    build_dashboard.build()

    assert output.read_text() == "const MANIFEST_DATA = null;"


# --- regression guards -----------------------------------------------------------
# A past merge silently dropped the calhoun-isms const + placeholder and shipped a
# broken tab to `main`. These pin the manifest wiring against that class of drop.


def test_manifest_placeholder_is_registered_to_the_manifest():
    assert build_dashboard.PLACEHOLDERS[MANIFEST_PLACEHOLDER].name == "manifest.json"


def test_template_still_binds_the_manifest_placeholder():
    html = (ROOT / "dashboard" / "template.html").read_text()

    assert f"const MANIFEST_DATA = {MANIFEST_PLACEHOLDER};" in html


def test_the_real_committed_manifest_inlines_without_duplicate_slugs():
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text())

    payload = build_dashboard.dedupe_manifest_payload(manifest)

    slugs = [a["slug"] for a in payload["articles"]]
    assert len(slugs) == len(set(slugs))
    assert payload["total_articles"] == len(slugs)
