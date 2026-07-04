"""Anthology — a printable "best of" keepsake from the archive.

Roadmap #24 (family): assemble a clean, printable "best of" anthology of Dr. George
Calhoun's writing — his vindicated calls and a signature piece per dominant theme —
rendered as a print-optimized HTML document the family can print or "Save as PDF".

Deterministic and offline: reads the analysis outputs already on disk
(`predictions.json`, `themes.json`), makes no conductor/network/LLM calls, and so is
safe to run unattended. Binary PDF generation is deferred to a later slice (browser
"Print to PDF" is the interim path); this module produces the print-ready HTML.
"""
