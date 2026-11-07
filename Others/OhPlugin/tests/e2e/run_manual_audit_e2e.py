"""Manual, model-backed CLI E2E; run explicitly with `python`.

This test uses the OpenHarness model configuration and may make a live model
request. It prompts for the OhPlugin directory to audit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


EXPECTED_MESSAGE = (
    "No supported manifest found. Expected requirements.txt and/or package.json in that folder."
)


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required and was not found on PATH.")

    configured = os.environ.get("OPENHARNESS_REPO")
    repo = (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[3] / "OpenHarness"
    )
    if not (repo / "pyproject.toml").is_file():
        raise SystemExit("OpenHarness checkout not found; set OPENHARNESS_REPO to its path.")

    plugin_path = input("Path to the OhPlugin folder to audit: ").strip().strip('"')
    if not plugin_path:
        raise SystemExit("A path to the OhPlugin folder is required.")
    target = Path(plugin_path).expanduser().resolve()
    if not target.is_dir():
        raise SystemExit(f"OhPlugin folder does not exist: {target}")

    prompt = f'/audit "{target}"'
    completed = subprocess.run(
        [uv, "run", "oh", "-p", prompt],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = completed.stdout + completed.stderr
    print(output, end="" if output.endswith("\n") else "\n")
    if completed.returncode != 0:
        print(f"OpenHarness exited with status {completed.returncode}.")
        return 1
    if EXPECTED_MESSAGE not in output:
        print(f"Expected response not found: {EXPECTED_MESSAGE}")
        return 1

    print("\033[32m✓ E2E passed: the audit reported that no supported manifest was found.\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
