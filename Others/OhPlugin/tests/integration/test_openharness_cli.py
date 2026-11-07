"""CLI integration check against the checked-out OpenHarness project."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _openharness_repo() -> Path:
    configured = os.environ.get("OPENHARNESS_REPO")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "OpenHarness"


def test_openharness_cli_dry_run_starts_from_checkout(capsys: pytest.CaptureFixture[str]):
    """Exercise the actual `oh` console entry point without invoking a model."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required; install it or run this test in the OpenHarness dev environment")

    repo = _openharness_repo()
    if not (repo / "pyproject.toml").is_file():
        pytest.skip("OpenHarness checkout not found; set OPENHARNESS_REPO to its path")

    completed = subprocess.run(
        [uv, "run", "oh", "--dry-run"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, f"`uv run oh --dry-run` failed:\n{output}"
    assert "dry-run" in output.lower(), f"Expected dry-run report in CLI output:\n{output}"
    with capsys.disabled():
        print("\033[32m✓ OpenHarness dry-run integration passed\033[0m")
