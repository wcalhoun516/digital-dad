"""The operator console's server-side half (plan 0011).

Separate from `ingest/` on purpose. The console turns the whole flywheel — ingest, then
fine-tune prep, preflight, training and the evals — so its job runner does not belong to any
one of the packages it runs. `bin/serve_dashboard.py` imports this lazily, for the same
reason it imports `ingest` lazily: the family dashboard is read-only and must keep serving
even when this tree cannot be imported.
"""
