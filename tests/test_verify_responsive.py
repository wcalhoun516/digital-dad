"""Unit tests for the pure pass/fail report logic of the responsive verifier.

The Playwright-driven rendering in `viz/verify_responsive.py` needs a browser and is
exercised by actually running `make verify-responsive`. The decision/report logic,
though, is pure and CI-safe — these tests pin it.
"""

from viz.verify_responsive import Finding, assess


def test_all_passing_findings_report_ok():
    findings = [
        Finding("desktop: no horizontal overflow", True, "scrollWidth 1280 <= 1280"),
        Finding("phone: corpus reflows to cards", True, "td display=block"),
    ]
    ok, report = assess(findings)
    assert ok is True
    assert "PASS" in report
    assert "FAIL" not in report


def test_any_failing_finding_reports_not_ok():
    findings = [
        Finding("desktop: no horizontal overflow", True, "scrollWidth 1280 <= 1280"),
        Finding("phone: no horizontal overflow", False, "scrollWidth 520 > 375"),
    ]
    ok, report = assess(findings)
    assert ok is False
    assert "FAIL" in report
    # The failing finding's detail must surface so a reviewer can see why.
    assert "520 > 375" in report


def test_empty_findings_is_not_ok():
    # No checks ran (e.g. page never loaded) must not be reported as success.
    ok, report = assess([])
    assert ok is False
