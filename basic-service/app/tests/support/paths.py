"""Stable resource roots shared by test suites, independent of the caller cwd."""
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = TEST_ROOT.parent
REPO_ROOT = APP_ROOT.parents[1]
SERVICE_ROOT = APP_ROOT / "src" / "service"
FIXTURE_ROOT = TEST_ROOT / "fixtures"
