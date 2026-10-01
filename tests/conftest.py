"""Keep every test run away from real workspace/user BeatBeam configuration.

Importing ``beatbeam_app`` already persists an upgraded configuration, so the
environment must point at a temporary location before the import happens. The
per-test fixture then gives each test its own unique paths, so a controller
that persists on ``disconnect()`` or ``update_config()`` cannot leak fixture
calibration into unrelated tests.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="beatbeam-tests-"))
os.environ["BEATBEAM_CONFIG_PATH"] = str(_SESSION_DIR / "beatbeam_config.json")
os.environ["BEATBEAM_TRANSPORT_CONFIG_PATH"] = str(_SESSION_DIR / "beatbeam_transport.json")
os.environ["BEATBEAM_REMOTE_ACCESS_PATH"] = str(_SESSION_DIR / "beatbeam_remote.json")
os.environ["BEATBEAM_TRIGGER_LOG_PATH"] = str(_SESSION_DIR / "beatbeam-trigger.log")
os.environ["BEATBEAM_TRACK_PREVIEW_CACHE_DIR"] = str(_SESSION_DIR / "track_preview_cache")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import beatbeam_app  # noqa: E402


ISOLATED_PATHS = (
    "CONFIG_PATH",
    "TRANSPORT_CONFIG_PATH",
    "REMOTE_ACCESS_PATH",
    "TRIGGER_LOG_PATH",
    "TRACK_PREVIEW_CACHE_DIR",
    "TRACK_PREVIEW_CACHE_FALLBACK_DIR",
)


@pytest.fixture(autouse=True)
def isolated_beatbeam_state(tmp_path, monkeypatch):
    for name in ISOLATED_PATHS:
        suffix = Path(getattr(beatbeam_app, name)).name
        monkeypatch.setattr(beatbeam_app, name, tmp_path / suffix)
    yield
