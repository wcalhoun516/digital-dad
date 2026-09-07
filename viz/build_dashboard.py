"""Build the dashboard by injecting analysis data into the HTML template."""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# `make dashboard` runs this as a script, so the repo root isn't on sys.path yet.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from analysis.utils import dedupe_manifest_entries  # noqa: E402

TEMPLATE_PATH = BASE_DIR / "dashboard" / "template.html"
OUTPUT_PATH = BASE_DIR / "dashboard" / "index.html"

MANIFEST_PLACEHOLDER = "/*__MANIFEST_DATA__*/"

PLACEHOLDERS = {
    "/*__THEME_DATA__*/": DATA_DIR / "analysis" / "themes.json",
    "/*__PSYCHOPROFILE_DATA__*/": DATA_DIR / "analysis" / "psychoprofile.json",
    "/*__LINGUISTIC_DATA__*/": DATA_DIR / "analysis" / "linguistics.json",
    MANIFEST_PLACEHOLDER: DATA_DIR / "manifest.json",
    "/*__ENTITY_DATA__*/": DATA_DIR / "analysis" / "entities.json",
    "/*__EMBEDDINGS_DATA__*/": DATA_DIR / "analysis" / "embeddings.json",
    "/*__PREDICTIONS_DATA__*/": DATA_DIR / "analysis" / "predictions.json",
    "/*__GEO_LLM_DATA__*/": DATA_DIR / "analysis" / "geo_llm.json",
    "/*__READING_ROOM_DATA__*/": DATA_DIR / "analysis" / "reading_room.json",
    "/*__ENTITY_GRAPH_DATA__*/": DATA_DIR / "analysis" / "entity_graph.json",
    "/*__INTELLECTUAL_ARC_DATA__*/": DATA_DIR / "analysis" / "intellectual_arc.json",
    "/*__CALHOUN_ISMS_DATA__*/": DATA_DIR / "analysis" / "calhoun_isms.json",
    "/*__CONTRADICTIONS_DATA__*/": DATA_DIR / "analysis" / "contradictions.json",
    "/*__ENTITY_STANCE_DATA__*/": DATA_DIR / "analysis" / "entity_stance.json",
}

# When an embeddings export is missing, inline an empty stub so the dashboard
# still builds before the first semantic_search run.
_EMPTY_DEFAULTS = {
    "/*__EMBEDDINGS_DATA__*/": '{"model":null,"dim":0,"slugs":[],"titles":[],"dates":[],"urls":[],"vectors":[],"snippets":[]}',
    "/*__PREDICTIONS_DATA__*/": '{"predictions":[],"aggregate":{"by_topic":{},"by_confidence":{},"by_year":{},"llm_verdicts":{}}}',
    "/*__GEO_LLM_DATA__*/": '{"dataset":null,"sample_pair":null,"qlora":null,"pipeline":[],"rag_baseline":null,"voice_eval":null,"verdict":null,"finetune":null}',
    # Reading Room embeds full bodies, so it is git-ignored; CI / fresh clones inline an
    # empty room and the tab shows a "run make reading-room" prompt instead of article text.
    "/*__READING_ROOM_DATA__*/": '{"entries":[],"count":0,"themes":[]}',
    # Entity co-occurrence graph (#14). Committed + text-free, but CI / fresh clones that
    # haven't run `make entity-graph` inline an empty graph and the tab shows a build prompt.
    "/*__ENTITY_GRAPH_DATA__*/": '{"meta":{},"nodes":[],"edges":[],"top_pairs":[]}',
    # Intellectual arc (#13). Committed + text-free (theme labels/shares + a deterministic
    # narrative), but CI / fresh clones that haven't run `make intellectual-arc` inline an
    # empty arc and the tab shows a build prompt.
    "/*__INTELLECTUAL_ARC_DATA__*/": (
        '{"generated":null,"overall":null,"by_year":[],"shifts":[],"narrative":""}'
    ),
    # Calhoun-isms (#16). Git-ignored (the artifact embeds body excerpts), so CI / fresh clones
    # that haven't run `make calhoun-isms` inline an empty board and the tab shows a build prompt.
    "/*__CALHOUN_ISMS_DATA__*/": '{"meta":{},"themes":[],"overall_top":[]}',
    # Contradictions / mind-changes (#15). Git-ignored (the artifact embeds body excerpts), so
    # CI / fresh clones that haven't run `make contradictions` inline an empty board and the tab
    # shows a build prompt.
    "/*__CONTRADICTIONS_DATA__*/": '{"meta":{},"contradictions":[]}',
    # entity_stance.json is text-free (names/years/scores) but may not exist before the first
    # `make entity-stance` — inline an empty graph so the tab shows a build prompt, not a blank.
    "/*__ENTITY_STANCE_DATA__*/": '{"meta":{},"entities":[],"warming":[],"cooling":[]}',
}


def dedupe_manifest_payload(payload: dict) -> dict:
    """Return *payload* with one article entry per raw file and a matching count.

    The manifest carries http/https twins of the same article (23 in the current corpus),
    both naming one raw file. `analysis.utils.load_articles` already collapses them for the
    analysis pipeline; the dashboard reads the manifest on its own path, so without this it
    would render each twin as a separate row and report the inflated `total_articles`.
    """
    if "articles" not in payload:
        return dict(payload)
    unique = dedupe_manifest_entries(payload["articles"])
    return {**payload, "articles": unique, "total_articles": len(unique)}


def build():
    if not TEMPLATE_PATH.exists():
        print(f"Error: Template not found at {TEMPLATE_PATH}")
        sys.exit(1)

    # Regenerate the Geo-LLM tab snapshot so a plain `make dashboard` is always fresh.
    try:
        from analysis.geo_llm_status import write_status

        write_status()
    except Exception as exc:  # never let status-gen break the dashboard build
        print(f"  (geo_llm status skipped: {exc})")

    html = TEMPLATE_PATH.read_text()

    for placeholder, data_path in PLACEHOLDERS.items():
        if data_path.exists():
            data = data_path.read_text()
            # Validate JSON
            try:
                parsed = json.loads(data)
                if placeholder == MANIFEST_PLACEHOLDER and isinstance(parsed, dict):
                    data = json.dumps(dedupe_manifest_payload(parsed))
            except json.JSONDecodeError as e:
                print(f"Warning: Invalid JSON in {data_path}: {e}")
                data = _EMPTY_DEFAULTS.get(placeholder, "null")
        else:
            data = _EMPTY_DEFAULTS.get(placeholder, "null")
            if placeholder not in _EMPTY_DEFAULTS:
                print(f"Warning: {data_path} not found — using null")
            else:
                print(f"Note: {data_path} not found — inlining empty stub")

        html = html.replace(placeholder, data)

    OUTPUT_PATH.write_text(html)
    print(f"Dashboard built: {OUTPUT_PATH}")
    print(f"Open in browser or run: python -m http.server 8000 -d {OUTPUT_PATH.parent}")


if __name__ == "__main__":
    build()
