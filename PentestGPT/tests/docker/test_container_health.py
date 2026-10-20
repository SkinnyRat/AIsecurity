"""Tests for Docker container health.

Docker tests that verify the container starts correctly and has
the required tools installed.
"""

import subprocess
import time
from pathlib import Path

import pytest

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.mark.docker
@pytest.mark.slow
class TestContainerHealth:
    """Tests for container health and required tools."""

    @pytest.fixture(scope="class")
    def running_container(self):
        """Start the container for testing and clean up after.

        This fixture starts the container, yields the container name,
        and ensures cleanup after all tests in the class complete.
        """
        # Start the container in detached mode
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            pytest.skip(f"Could not start container: {result.stderr}")

        # Wait for container to be ready
        time.sleep(5)

        container_name = "pentestgpt"

        # Check if container is running
        check_result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={container_name}"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if not check_result.stdout.strip():
            pytest.skip("Container not running")

        yield container_name

        # Cleanup: stop and remove container
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            timeout=60,
        )

    def _exec_in_container(self, container: str, command: str) -> subprocess.CompletedProcess:
        """Execute a command in the container."""
        return subprocess.run(
            ["docker", "exec", container, "bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_container_starts(self, running_container: str):
        """Test that the container starts successfully."""
        result = subprocess.run(
            ["docker", "ps", "-f", f"name={running_container}", "--format", "{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Up" in result.stdout, "Container should be running"

    def test_workspace_exists(self, running_container: str):
        """Test that /workspace directory exists."""
        result = self._exec_in_container(running_container, "test -d /workspace && echo ok")
        assert "ok" in result.stdout, "/workspace directory should exist"

    def test_python_installed(self, running_container: str):
        """Test that Python 3.12+ is installed."""
        result = self._exec_in_container(running_container, "python3 --version")
        assert result.returncode == 0
        assert "Python 3.1" in result.stdout, "Python 3.12+ should be installed"

    def test_uv_installed(self, running_container: str):
        """Test that the uv package manager is installed."""
        result = self._exec_in_container(running_container, "uv --version")
        assert result.returncode == 0
        assert "uv" in result.stdout, "uv should be installed"

    def test_nmap_installed(self, running_container: str):
        """Test that nmap is installed."""
        result = self._exec_in_container(running_container, "which nmap")
        assert result.returncode == 0
        assert "nmap" in result.stdout, "nmap should be installed"

    def test_curl_installed(self, running_container: str):
        """Test that curl is installed."""
        result = self._exec_in_container(running_container, "which curl")
        assert result.returncode == 0
        assert "curl" in result.stdout, "curl should be installed"

    def test_git_installed(self, running_container: str):
        """Test that git is installed."""
        result = self._exec_in_container(running_container, "git --version")
        assert result.returncode == 0
        assert "git version" in result.stdout, "git should be installed"

    def test_netcat_installed(self, running_container: str):
        """Test that netcat is installed."""
        result = self._exec_in_container(
            running_container, "which nc || which netcat || which ncat"
        )
        assert result.returncode == 0, "netcat should be installed"

    def test_ripgrep_installed(self, running_container: str):
        """Test that ripgrep is installed."""
        result = self._exec_in_container(running_container, "rg --version")
        assert result.returncode == 0
        assert "ripgrep" in result.stdout, "ripgrep should be installed"

    def test_tmux_installed(self, running_container: str):
        """Test that tmux is installed."""
        result = self._exec_in_container(running_container, "tmux -V")
        assert result.returncode == 0
        assert "tmux" in result.stdout, "tmux should be installed"

    def test_pentester_user_exists(self, running_container: str):
        """Test that the pentester user exists."""
        result = self._exec_in_container(running_container, "id pentester")
        assert result.returncode == 0
        assert "pentester" in result.stdout, "pentester user should exist"

    def test_sudo_available(self, running_container: str):
        """Test that sudo is available."""
        result = self._exec_in_container(running_container, "which sudo")
        assert result.returncode == 0
        assert "sudo" in result.stdout, "sudo should be installed"

    def test_agent_packages_importable(self, running_container: str):
        """Test that the substrate packages baked into the image are importable.

        The maintained framework (pentestgpt_agent) is not baked into this
        image yet (see Dockerfile), so only the substrate + legacy CLI ship here.
        """
        result = self._exec_in_container(
            running_container,
            "python3 -c 'import unified_agent, pentestgpt_legacy; print(\"ok\")'",
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "ok" in result.stdout, "substrate packages should be importable"

    def test_claude_code_available(self, running_container: str):
        """Test that Claude Code CLI is available."""
        result = self._exec_in_container(running_container, "which claude || echo 'not found'")
        # Claude might not be installed in all environments, but check
        if "not found" in result.stdout:
            pytest.skip("Claude Code CLI not installed in container")
        assert "claude" in result.stdout
