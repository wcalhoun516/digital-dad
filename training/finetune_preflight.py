"""Pre-flight checks for the QLoRA fine-tune (plan 0008, de-risks step 26c).

Before anyone burns M4 compute on the actual training run, this validates 26a's
leakage-free split (`data/training/{train,heldout}.jsonl`) against the run's
`QLoRAConfig` and reports anything that would silently waste the run:

  - **chat-shape integrity** — every record is a system/user/assistant turn with
    non-empty content (mlx-lm needs well-formed chat records);
  - **split disjointness** — no training example leaks into the held-out/valid
    set (matched by assistant-content hash), which would inflate validation;
  - **sequence-length budget** — how many records' rendered prompts exceed the
    config's ``max_seq_len`` and would be dropped/truncated by mlx-lm.

It is **report-only** (exit 0) by default so it never turns `make verify` red;
``--strict`` exits non-zero on any failing check for a future CI/pre-run gate.
"""
