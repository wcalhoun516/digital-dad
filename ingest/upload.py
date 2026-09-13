"""Validation for operator-console file uploads (plan 0011 step 2).

Nothing here touches HTTP. The console route is a thin caller; this module is the single
place that decides whether a client-supplied file is allowed to become a path on disk.
"""
