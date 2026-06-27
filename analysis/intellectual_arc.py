"""Intellectual arc — year-over-year theme evolution (roadmap #13).

Pure, offline post-processing of ``data/analysis/themes.json``: bin the clustered
articles by year, find each year's dominant theme, compute the year-over-year rises /
fades / emergent / vanished themes, and render a deterministic narrative of how Dr.
Calhoun's focus shifted. No conductor, no network, no LLM calls — safe to run unattended.

CLI:
  python -m analysis.intellectual_arc            # write data/analysis/intellectual_arc.json
  python -m analysis.intellectual_arc --dry-run  # print the narrative, write nothing
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import date

from .utils import DATA_DIR

ANALYSIS_DIR = DATA_DIR / "analysis"
THEMES_PATH = ANALYSIS_DIR / "themes.json"
REPORT_PATH = ANALYSIS_DIR / "intellectual_arc.json"

# How many entries to surface in each rising/fading list per year transition.
_TOP_N = 3
# A year is "partial" (e.g. the in-progress current year) when its article count is
# below this fraction of the median year — too thin to anchor the arc's conclusion.
_PARTIAL_FRACTION = 0.5


def _label_map(themes: dict) -> dict[int, str]:
    """Build cluster_id -> human label from themes['clusters']."""
    out: dict[int, str] = {}
    for c in themes.get("clusters", []):
        cid = c.get("id")
        label = (c.get("label") or "").strip()
        if cid is not None and label:
            out[int(cid)] = label
    return out


def _resolve_label(cid: int, themes_label_map: dict[int, str], fallback: str) -> str:
    label = themes_label_map.get(cid) or (fallback or "").strip()
    return label or f"Cluster {cid}"


def arc_by_year(themes: dict) -> list[dict]:
    """Bin articles by calendar year with per-cluster counts and a dominant theme.

    Articles without a usable 4-digit year are dropped. Each year's ``themes`` list is
    sorted by count descending, ties broken by lower cluster_id (deterministic).
    """
    label_map = _label_map(themes)
    # year -> cluster_id -> count, and remember a label seen on each cluster
    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    seen_label: dict[int, str] = {}

    for art in themes.get("articles", []):
        date_str = art.get("date") or ""
        if len(date_str) < 4 or not date_str[:4].isdigit():
            continue
        cid = int(art.get("cluster_id", -1))
        if cid < 0:
            continue
        year = date_str[:4]
        counts[year][cid] += 1
        seen_label.setdefault(cid, art.get("cluster_label", ""))

    by_year: list[dict] = []
    for year in sorted(counts):
        total = sum(counts[year].values())
        themes_list = []
        for cid, n in sorted(counts[year].items(), key=lambda kv: (-kv[1], kv[0])):
            themes_list.append({
                "cluster_id": cid,
                "label": _resolve_label(cid, label_map, seen_label.get(cid, "")),
                "count": n,
                "share": round(n / total, 3) if total else 0.0,
            })
        by_year.append({
            "year": year,
            "total": total,
            "themes": themes_list,
            "dominant": themes_list[0] if themes_list else None,
        })

    # Flag thin years (e.g. the in-progress current year) so they don't anchor the arc.
    totals = [y["total"] for y in by_year]
    if totals:
        threshold = _PARTIAL_FRACTION * statistics.median(totals)
        for y in by_year:
            y["partial"] = y["total"] < threshold
    return by_year


def _shares(year_entry: dict) -> dict[int, float]:
    return {t["cluster_id"]: t["share"] for t in year_entry["themes"]}


def _labels_from_year(year_entry: dict) -> dict[int, str]:
    return {t["cluster_id"]: t["label"] for t in year_entry["themes"]}


def year_over_year_shifts(by_year: list[dict]) -> list[dict]:
    """For each consecutive year pair, classify the theme deltas."""
    shifts: list[dict] = []
    for prev, cur in zip(by_year, by_year[1:]):
        prev_shares = _shares(prev)
        cur_shares = _shares(cur)
        labels = {**_labels_from_year(prev), **_labels_from_year(cur)}
        all_ids = set(prev_shares) | set(cur_shares)

        deltas = []
        emergent, vanished = [], []
        for cid in all_ids:
            ps = prev_shares.get(cid, 0.0)
            cs = cur_shares.get(cid, 0.0)
            entry = {
                "cluster_id": cid,
                "label": labels.get(cid, f"Cluster {cid}"),
                "from_share": ps,
                "to_share": cs,
                "delta_share": round(cs - ps, 3),
            }
            deltas.append(entry)
            if ps == 0 and cs > 0:
                emergent.append(entry)
            elif ps > 0 and cs == 0:
                vanished.append(entry)

        rising = sorted([d for d in deltas if d["delta_share"] > 0],
                        key=lambda d: (-d["delta_share"], d["cluster_id"]))[:_TOP_N]
        fading = sorted([d for d in deltas if d["delta_share"] < 0],
                        key=lambda d: (d["delta_share"], d["cluster_id"]))[:_TOP_N]

        dominant_change = None
        if prev.get("dominant") and cur.get("dominant") and \
                prev["dominant"]["cluster_id"] != cur["dominant"]["cluster_id"]:
            dominant_change = {
                "from": {"cluster_id": prev["dominant"]["cluster_id"],
                         "label": prev["dominant"]["label"]},
                "to": {"cluster_id": cur["dominant"]["cluster_id"],
                       "label": cur["dominant"]["label"]},
            }

        shifts.append({
            "from_year": prev["year"],
            "to_year": cur["year"],
            "rising": rising,
            "fading": fading,
            "emergent": sorted(emergent, key=lambda d: (-d["to_share"], d["cluster_id"])),
            "vanished": sorted(vanished, key=lambda d: (-d["from_share"], d["cluster_id"])),
            "dominant_change": dominant_change,
        })
    return shifts


def overall_arc(by_year: list[dict]) -> dict | None:
    """Summarize the arc across the *full* years; report any partial final year aside.

    The most-grown / most-declined comparison and the first→last endpoints use only the
    years with enough volume to be representative, so an in-progress current year can't
    distort the conclusion. Every year (including partial ones) still contributes to
    ``n_years`` / ``n_articles`` and remains in ``by_year``.
    """
    if not by_year:
        return None

    full = [y for y in by_year if not y.get("partial")] or by_year
    first = full[0]
    last_full = full[-1] if len(full) >= 2 else first

    first_shares = _shares(first)
    last_shares = _shares(last_full)
    labels = {**_labels_from_year(first), **_labels_from_year(last_full)}

    movers = []
    for cid in set(first_shares) | set(last_shares):
        fs = first_shares.get(cid, 0.0)
        ls = last_shares.get(cid, 0.0)
        movers.append({
            "cluster_id": cid,
            "label": labels.get(cid, f"Cluster {cid}"),
            "first_share": fs,
            "last_share": ls,
            "delta_share": round(ls - fs, 3),
        })

    most_grown = max(movers, key=lambda m: (m["delta_share"], -m["cluster_id"]))
    most_declined = min(movers, key=lambda m: (m["delta_share"], m["cluster_id"]))

    final = by_year[-1]
    partial_final = bool(final.get("partial")) and final is not last_full
    final_year = None
    if partial_final:
        final_year = {
            "year": final["year"],
            "total": final["total"],
            "dominant": final.get("dominant"),
        }

    return {
        "span": f"{first['year']}–{last_full['year']}",
        "n_years": len(by_year),
        "n_articles": sum(y["total"] for y in by_year),
        "first_year": first["year"],
        "last_year": last_full["year"],
        "first_dominant": first.get("dominant"),
        "last_dominant": last_full.get("dominant"),
        "most_grown": most_grown,
        "most_declined": most_declined,
        "partial_final_year": partial_final,
        "final_year": final_year,
    }


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def render_narrative(by_year: list[dict], shifts: list[dict], overall: dict | None) -> str:
    """Assemble plain-prose narrative from the computed numbers (deterministic)."""
    if not overall or not by_year:
        return ("There isn't yet enough dated, theme-clustered writing to trace an "
                "intellectual arc. Run `make analyze` to build the theme clusters first.")

    parts: list[str] = []
    span = overall["span"]
    n_articles = overall["n_articles"]
    n_years = overall["n_years"]
    fd = overall["first_dominant"]
    ld = overall["last_dominant"]
    full_years = {y["year"] for y in by_year if not y.get("partial")}

    def _append_final_note() -> None:
        fn = overall.get("final_year")
        if fn and fn.get("dominant"):
            piece = "piece" if fn["total"] == 1 else "pieces"
            parts.append(
                f"So far in {fn['year']} ({fn['total']} {piece}), "
                f"{fn['dominant']['label']} leads ({_pct(fn['dominant']['share'])})."
            )

    if overall["first_year"] == overall["last_year"]:
        first_total = next(
            (y["total"] for y in by_year if y["year"] == overall["first_year"]), 0
        )
        parts.append(
            f"In {overall['first_year']}, across {first_total} dated pieces, Dr. "
            f"Calhoun's writing centered on {fd['label']} "
            f"({_pct(fd['share'])} of his output)."
        )
        _append_final_note()
        return " ".join(parts)

    opener = (f"Across {n_years} years and {n_articles} dated pieces ({span}), "
              f"Dr. Calhoun's focus")
    if fd["cluster_id"] != ld["cluster_id"]:
        parts.append(
            f"{opener} shifted from {fd['label']} ({_pct(fd['share'])} of his "
            f"{overall['first_year']} writing) to {ld['label']} "
            f"({_pct(ld['share'])} by {overall['last_year']})."
        )
    else:
        parts.append(
            f"{opener} stayed anchored on {fd['label']}, which led both his "
            f"{overall['first_year']} writing ({_pct(fd['share'])}) and his "
            f"{overall['last_year']} writing ({_pct(ld['share'])})."
        )

    grown = overall["most_grown"]
    declined = overall["most_declined"]
    if grown["delta_share"] > 0:
        parts.append(
            f"The biggest gainer over the span was {grown['label']} "
            f"({_pct(grown['first_share'])} → {_pct(grown['last_share'])})."
        )
    if declined["delta_share"] < 0:
        parts.append(
            f"{declined['label']} receded the most "
            f"({_pct(declined['first_share'])} → {_pct(declined['last_share'])})."
        )

    # Highlight the single sharpest year-to-year emergence into a *full* year.
    sharpest = None
    for s in shifts:
        if s["to_year"] not in full_years:
            continue
        for e in s["emergent"]:
            if sharpest is None or e["to_share"] > sharpest[1]["to_share"]:
                sharpest = (s, e)
    if sharpest:
        s, e = sharpest
        parts.append(
            f"{e['label']} broke through in {s['to_year']}, arriving from nothing "
            f"to {_pct(e['to_share'])} of that year's writing."
        )

    _append_final_note()
    return " ".join(parts)


def build_arc(themes: dict) -> dict:
    """Assemble the full intellectual-arc document from a themes.json-shaped dict."""
    by_year = arc_by_year(themes)
    shifts = year_over_year_shifts(by_year)
    overall = overall_arc(by_year)
    return {
        "generated": date.today().isoformat(),
        "overall": overall,
        "by_year": by_year,
        "shifts": shifts,
        "narrative": render_narrative(by_year, shifts, overall),
    }


def run(dry_run: bool = False) -> dict:
    """Read themes.json, build the arc, write intellectual_arc.json (unless dry-run)."""
    if not THEMES_PATH.exists():
        raise FileNotFoundError(
            f"No theme analysis at {THEMES_PATH}. Run `make analyze` first."
        )
    themes = json.loads(THEMES_PATH.read_text())
    doc = build_arc(themes)

    print(doc["narrative"])
    if dry_run:
        print("\nDry run — nothing written.")
        return doc

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    print(f"\nIntellectual arc saved to {REPORT_PATH}")
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trace Dr. Calhoun's year-over-year theme evolution (intellectual arc)."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the narrative without writing the JSON report.")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
