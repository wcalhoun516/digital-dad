"""Live both-breakpoint verification for the responsive dashboard (plan 0006, step 4).

Steps 1–3 added the responsive CSS, D3 resize-redraw, and corpus card reflow, but every
run flagged that the live phone-width browser pass was never run. This harness closes
that gap: it renders the *built* `dashboard/index.html` in a real headless Chromium at
desktop and phone widths and asserts the family-facing invariants —

  * no horizontal overflow (the whole point of the responsive work),
  * a clean JS console (no errors / uncaught exceptions),
  * the Raw Corpus table stays a table on desktop but reflows to cards on a phone
    (so we simultaneously prove the mobile reflow *and* that desktop didn't regress).

It is intentionally **not** part of `make verify`: CI has no browser. The script SKIPs
cleanly (exit 0) when Chromium can't launch, so wiring it into a pipeline is safe.

Run it via `make verify-responsive` (or `python -m viz.verify_responsive`).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "dashboard" / "index.html"
SCREENSHOT_DIR = ROOT / "build" / "preview"

# (label, width, height, corpus_is_table). On desktop a corpus <td> is a real
# `table-cell`; on a phone the card reflow takes it *off* table layout (the cells
# become flex rows: data-label left, value right). We assert that contrast rather than
# one exact `display` value so a future reflow tweak doesn't fail spuriously — what must
# hold is "table on desktop, reflowed on phone".
VIEWPORTS = (
    ("desktop", 1280, 900, True),
    ("phone", 375, 812, False),
)

OVERFLOW_TOLERANCE_PX = 2


@dataclass(frozen=True)
class Finding:
    name: str
    ok: bool
    detail: str = ""


def assess(findings: list[Finding]) -> tuple[bool, str]:
    """Reduce findings to an overall pass/fail and a human-readable report.

    Empty findings is a failure: it means no checks actually ran.
    """
    lines = [
        f"  [{'PASS' if f.ok else 'FAIL'}] {f.name}" + (f" — {f.detail}" if f.detail else "")
        for f in findings
    ]
    ok = bool(findings) and all(f.ok for f in findings)
    failed = sum(1 for f in findings if not f.ok)
    if not findings:
        summary = "no checks ran — nothing to verify (treated as failure)"
    elif ok:
        summary = f"all {len(findings)} checks passed"
    else:
        summary = f"{failed} of {len(findings)} checks FAILED"
    return ok, "\n".join([*lines, summary])


def _check_viewport(page, label: str, width: int, height: int, corpus_is_table: bool):
    """Drive one viewport and yield its Findings. Captures console errors live."""
    console_errors: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

    page.set_viewport_size({"width": width, "height": height})
    page.goto(INDEX.as_uri(), wait_until="networkidle")

    # Default (Theme Map) tab — give the D3 chart a beat to lay out.
    page.wait_for_timeout(400)
    sw = page.evaluate("document.documentElement.scrollWidth")
    iw = page.evaluate("window.innerWidth")
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DIR / f"{label}_themes.png"))
    yield Finding(
        f"{label}: no horizontal overflow (Theme Map)",
        sw <= iw + OVERFLOW_TOLERANCE_PX,
        f"scrollWidth {sw} vs innerWidth {iw}",
    )

    # Switch to the Raw Corpus tab — the wide table is the hard reflow case.
    page.click('nav button[data-tab="corpus"]')
    page.wait_for_selector(".corpus-table td", timeout=5000)
    page.wait_for_timeout(300)
    page.screenshot(path=str(SCREENSHOT_DIR / f"{label}_corpus.png"))

    sw = page.evaluate("document.documentElement.scrollWidth")
    iw = page.evaluate("window.innerWidth")
    yield Finding(
        f"{label}: no horizontal overflow (Raw Corpus)",
        sw <= iw + OVERFLOW_TOLERANCE_PX,
        f"scrollWidth {sw} vs innerWidth {iw}",
    )

    td_display = page.evaluate(
        "getComputedStyle(document.querySelector('.corpus-table td')).display"
    )
    is_table = td_display == "table-cell"
    yield Finding(
        f"{label}: corpus table {'stays a table' if corpus_is_table else 'reflows to cards'}",
        is_table == corpus_is_table,
        f"td display={td_display!r} "
        + ("(table layout)" if corpus_is_table else "(reflowed off table layout)"),
    )

    yield Finding(
        f"{label}: clean JS console",
        not console_errors,
        "no console errors" if not console_errors else "; ".join(console_errors[:5]),
    )


def run_checks() -> list[Finding]:
    from playwright.sync_api import sync_playwright

    findings: list[Finding] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for label, width, height, corpus_is_table in VIEWPORTS:
                page = browser.new_context().new_page()
                findings.extend(_check_viewport(page, label, width, height, corpus_is_table))
        finally:
            browser.close()
    return findings


def main() -> int:
    if not INDEX.exists():
        print(f"SKIP: {INDEX} not found — run `make dashboard` first.")
        return 0
    try:
        findings = run_checks()
    except Exception as exc:  # chromium not installed / can't launch
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            print(f"SKIP: headless Chromium unavailable ({msg.splitlines()[0]}).")
            return 0
        raise
    ok, report = assess(findings)
    print(report)
    print(f"\nScreenshots: {SCREENSHOT_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
