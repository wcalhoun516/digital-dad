"""Tests for analysis/hub_offline.py — never block an unattended run on the HF hub.

Roadmap #63: a 35-minute stall was a hung HuggingFace hub socket during model load. The
weights were already on disk; ``mlx_lm.load`` asked the hub anyway, because nothing told it
not to. The rule under test: go offline exactly when every model is *provably* cached, leave
an owner's explicit setting alone, and otherwise stay online with explicit timeouts.
"""

from types import SimpleNamespace

from analysis import hub_offline as ho

REPO = "mlx-community/gemma-4-e4b-it-4bit"


def cache_repo(cache, repo=REPO, *, ref=True, config=True, sha="475b9088"):
    """Lay out a repo the way huggingface_hub does: refs/main → snapshots/<sha>/."""
    root = cache / ("models--" + repo.replace("/", "--"))
    snap = root / "snapshots" / sha
    snap.mkdir(parents=True)
    if config:
        (snap / "config.json").write_text("{}")
    if ref:
        (root / "refs").mkdir()
        (root / "refs" / "main").write_text(sha)
    return root


# --- where the cache is -----------------------------------------------------------

def test_cache_dir_honours_hf_hub_cache_first(tmp_path):
    env = {"HF_HUB_CACHE": str(tmp_path / "a"), "HF_HOME": str(tmp_path / "b")}
    assert ho.hub_cache_dir(env) == tmp_path / "a"


def test_cache_dir_falls_back_to_hf_home_hub(tmp_path):
    assert ho.hub_cache_dir({"HF_HOME": str(tmp_path)}) == tmp_path / "hub"


def test_cache_dir_defaults_under_the_home_directory():
    assert ho.hub_cache_dir({}).parts[-3:] == (".cache", "huggingface", "hub")


# --- is it cached? ----------------------------------------------------------------

def test_a_fully_cached_repo_is_cached(tmp_path):
    cache_repo(tmp_path)
    assert ho.is_cached(REPO, tmp_path)


def test_a_repo_never_downloaded_is_not_cached(tmp_path):
    assert not ho.is_cached(REPO, tmp_path)


def test_a_snapshot_without_refs_main_is_not_cached(tmp_path):
    # Offline snapshot_download resolves revision "main" through refs/main; without it the
    # load would fail, so this must not count as cached.
    cache_repo(tmp_path, ref=False)
    assert not ho.is_cached(REPO, tmp_path)


def test_an_interrupted_download_is_not_cached(tmp_path):
    # refs/main written, but the snapshot never got its config.json — going offline would
    # turn a resumable download into a hard failure.
    cache_repo(tmp_path, config=False)
    assert not ho.is_cached(REPO, tmp_path)


def test_refs_main_pointing_at_a_missing_snapshot_is_not_cached(tmp_path):
    root = cache_repo(tmp_path)
    (root / "refs" / "main").write_text("deadbeef")
    assert not ho.is_cached(REPO, tmp_path)


def test_a_local_model_directory_needs_no_hub(tmp_path):
    local = tmp_path / "my-model"
    local.mkdir()
    assert ho.is_cached(str(local), tmp_path / "empty-cache")


# --- the env overrides ------------------------------------------------------------

def test_goes_offline_when_every_model_is_cached(tmp_path):
    cache_repo(tmp_path)
    env = ho.hub_env([REPO], {"HF_HUB_CACHE": str(tmp_path)})
    assert env["HF_HUB_OFFLINE"] == "1"


def test_stays_online_when_any_model_is_missing(tmp_path):
    cache_repo(tmp_path)
    env = ho.hub_env([REPO, "mlx-community/not-here"], {"HF_HUB_CACHE": str(tmp_path)})
    assert "HF_HUB_OFFLINE" not in env


def test_online_runs_get_explicit_hub_timeouts(tmp_path):
    env = ho.hub_env([REPO], {"HF_HUB_CACHE": str(tmp_path)})
    assert int(env["HF_HUB_ETAG_TIMEOUT"]) > 0
    assert int(env["HF_HUB_DOWNLOAD_TIMEOUT"]) > 0


def test_existing_timeouts_are_not_overridden(tmp_path):
    env = ho.hub_env([REPO], {"HF_HUB_CACHE": str(tmp_path), "HF_HUB_ETAG_TIMEOUT": "3"})
    assert "HF_HUB_ETAG_TIMEOUT" not in env


def test_no_models_vouches_for_nothing(tmp_path):
    # A caller that could not name its model (e.g. an unparseable config) must not be
    # pushed offline on the strength of an empty list.
    assert "HF_HUB_OFFLINE" not in ho.hub_env([], {"HF_HUB_CACHE": str(tmp_path)})
    assert "HF_HUB_OFFLINE" not in ho.hub_env([None], {"HF_HUB_CACHE": str(tmp_path)})


def test_an_explicit_owner_setting_wins(tmp_path):
    cache_repo(tmp_path)
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        env = ho.hub_env([REPO], {"HF_HUB_CACHE": str(tmp_path), key: "0"})
        assert "HF_HUB_OFFLINE" not in env, key


# --- in-process -------------------------------------------------------------------

def test_apply_in_process_sets_the_environment(tmp_path):
    cache_repo(tmp_path)
    environ = {"HF_HUB_CACHE": str(tmp_path)}
    applied = ho.apply_in_process([REPO], environ=environ, modules={})
    assert environ["HF_HUB_OFFLINE"] == "1" and applied["HF_HUB_OFFLINE"] == "1"


def test_apply_in_process_patches_an_already_imported_hub(tmp_path):
    # huggingface_hub reads HF_HUB_OFFLINE once, at import. If something imported it
    # first, setting the env var alone is a silent no-op.
    cache_repo(tmp_path)
    constants = SimpleNamespace(HF_HUB_OFFLINE=False)
    ho.apply_in_process([REPO], environ={"HF_HUB_CACHE": str(tmp_path)},
                        modules={"huggingface_hub.constants": constants})
    assert constants.HF_HUB_OFFLINE is True


def test_apply_in_process_leaves_the_hub_alone_when_staying_online(tmp_path):
    constants = SimpleNamespace(HF_HUB_OFFLINE=False)
    ho.apply_in_process([REPO], environ={"HF_HUB_CACHE": str(tmp_path)},
                        modules={"huggingface_hub.constants": constants})
    assert constants.HF_HUB_OFFLINE is False
