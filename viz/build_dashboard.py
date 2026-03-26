"""Build the dashboard by injecting analysis data into the HTML template."""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TEMPLATE_PATH = BASE_DIR / "dashboard" / "template.html"
OUTPUT_PATH = BASE_DIR / "dashboard" / "index.html"

PLACEHOLDERS = {
    "/*__THEME_DATA__*/": DATA_DIR / "analysis" / "themes.json",
    "/*__PSYCHOPROFILE_DATA__*/": DATA_DIR / "analysis" / "psychoprofile.json",
    "/*__LINGUISTIC_DATA__*/": DATA_DIR / "analysis" / "linguistics.json",
    "/*__MANIFEST_DATA__*/": DATA_DIR / "manifest.json",
}


def build():
    if not TEMPLATE_PATH.exists():
        print(f"Error: Template not found at {TEMPLATE_PATH}")
        sys.exit(1)

    html = TEMPLATE_PATH.read_text()

    for placeholder, data_path in PLACEHOLDERS.items():
        if data_path.exists():
            data = data_path.read_text()
            # Validate JSON
            try:
                json.loads(data)
            except json.JSONDecodeError as e:
                print(f"Warning: Invalid JSON in {data_path}: {e}")
                data = "null"
        else:
            print(f"Warning: {data_path} not found — using null")
            data = "null"

        html = html.replace(placeholder, data)

    OUTPUT_PATH.write_text(html)
    print(f"Dashboard built: {OUTPUT_PATH}")
    print(f"Open in browser or run: python -m http.server 8000 -d {OUTPUT_PATH.parent}")


if __name__ == "__main__":
    build()
