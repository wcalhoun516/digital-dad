"""Keep model loads off the HuggingFace hub when the weights are already on disk (roadmap #63).

**Why this exists.** A nightly run stalled for 35 minutes on a hung hub socket
(``CLOSE_WAIT``) inside ``mlx_lm.load``. The weights were cached; the load asked the hub
anyway, because ``snapshot_download`` checks for a newer revision unless ``HF_HUB_OFFLINE``
is set — and nothing set it. An unattended run has no one to notice a dead connection.

The policy, in order:

1. An explicit ``HF_HUB_OFFLINE`` / ``TRANSFORMERS_OFFLINE`` in the environment is the
   owner's call and is left alone.
2. If every model is **provably** cached — ``refs/main`` points at a snapshot that holds a
   ``config.json`` — or is a local directory, go offline. A half-finished download does not
   count: offline would turn a resumable download into a hard failure.
3. Otherwise stay online, with the hub's timeouts set explicitly rather than inherited from
   whatever the installed ``huggingface_hub`` defaults to.

``huggingface_hub`` reads ``HF_HUB_OFFLINE`` once, at import, so in-process callers must
apply this *before* importing ``mlx_lm`` — and ``apply_in_process`` also patches the
constant if the hub was imported first. Subprocess callers pass ``hub_env`` as their env.
"""

import os
import sys
from collections.abc import Iterable, Mapping, MutableMapping
from pathlib import Path

ETAG_TIMEOUT_S = 10
DOWNLOAD_TIMEOUT_S = 10
_EXPLICIT_KEYS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")


def hub_cache_dir(environ: Mapping[str, str]) -> Path:
    """Where huggingface_hub keeps repos: ``HF_HUB_CACHE``, else ``$HF_HOME/hub``, else ~."""
    if environ.get("HF_HUB_CACHE"):
        return Path(environ["HF_HUB_CACHE"]).expanduser()
    if environ.get("HF_HOME"):
        return Path(environ["HF_HOME"]).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_cached(model: str, cache_dir: Path) -> bool:
    """True if loading *model* needs nothing from the hub."""
    if Path(model).expanduser().is_dir():          # a local checkout: mlx_lm never asks
        return True
    root = cache_dir / ("models--" + model.replace("/", "--"))
    try:
        sha = (root / "refs" / "main").read_text().strip()
    except OSError:
        return False
    return bool(sha) and (root / "snapshots" / sha / "config.json").is_file()


def hub_env(models: Iterable[str | None], environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """The environment overrides that keep loading *models* from blocking on the hub."""
    named = [m for m in models if m]
    overrides: dict[str, str] = {}
    if not any(environ.get(k) is not None for k in _EXPLICIT_KEYS):
        cache = hub_cache_dir(environ)
        if named and all(is_cached(m, cache) for m in named):
            overrides["HF_HUB_OFFLINE"] = "1"
    for key, seconds in (("HF_HUB_ETAG_TIMEOUT", ETAG_TIMEOUT_S),
                         ("HF_HUB_DOWNLOAD_TIMEOUT", DOWNLOAD_TIMEOUT_S)):
        if key not in environ:
            overrides[key] = str(seconds)
    return overrides


def apply_in_process(
    models: Iterable[str | None],
    *,
    environ: MutableMapping[str, str] = os.environ,
    modules: Mapping[str, object] = sys.modules,
) -> dict[str, str]:
    """Apply ``hub_env`` to this process, including an already-imported huggingface_hub."""
    overrides = hub_env(models, environ)
    environ.update(overrides)
    constants = modules.get("huggingface_hub.constants")
    if constants is not None and overrides.get("HF_HUB_OFFLINE") == "1":
        constants.HF_HUB_OFFLINE = True
    return overrides
