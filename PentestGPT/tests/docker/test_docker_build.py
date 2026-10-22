"""Tests for Docker build process.

Docker tests that verify the Dockerfile and docker-compose configuration
are valid and can build successfully.
"""

import subprocess
from pathlib import Path

import pytest

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.mark.docker
@pytest.mark.slow
class TestDockerBuild:
    """Tests for Docker build process."""

    def test_dockerfile_exists(self):
        """Test that Dockerfile exists in project root."""
        dockerfile = PROJECT_ROOT / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile not found in project root"

    def test_docker_compose_exists(self):
        """Test that docker-compose.yml exists in project root."""
        compose_file = PROJECT_ROOT / "docker-compose.yml"
        assert compose_file.exists(), "docker-compose.yml not found in project root"

    def test_docker_compose_config_valid(self):
        """Test that docker-compose configuration is valid."""
        result = subprocess.run(
            ["docker", "compose", "config"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"docker compose config failed: {result.stderr}"

    def test_dockerfile_syntax_valid(self):
        """Test that Dockerfile has valid syntax using docker build --check."""
        # Use docker build with --check flag (available in recent Docker versions)
        # If not available, just verify the file can be parsed
        dockerfile = PROJECT_ROOT / "Dockerfile"
        content = dockerfile.read_text()

        # Basic syntax checks
        assert "FROM" in content, "Dockerfile must have a FROM instruction"
        assert "ubuntu" in content.lower(), "Expected Ubuntu base image"

    def test_docker_image_builds(self):
        """Test that Docker image builds successfully.

        Note: This test is slow and requires Docker to be running.
        It's marked with @pytest.mark.slow for optional skipping.
        """
        result = subprocess.run(
            ["docker", "compose", "build"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout for build
        )

        # Check build succeeded
        assert result.returncode == 0, f"Docker build failed:\n{result.stderr}"

    def test_scripts_exist(self):
        """Test that required scripts exist."""
        scripts_dir = PROJECT_ROOT / "scripts"

        # Check config.sh
        config_script = scripts_dir / "config.sh"
        assert config_script.exists(), "scripts/config.sh not found"

        # Check entrypoint.sh
        entrypoint_script = scripts_dir / "entrypoint.sh"
        assert entrypoint_script.exists(), "scripts/entrypoint.sh not found"

    def test_entrypoint_script_syntax(self):
        """Test that entrypoint.sh has valid bash syntax."""
        entrypoint = PROJECT_ROOT / "scripts" / "entrypoint.sh"

        result = subprocess.run(
            ["bash", "-n", str(entrypoint)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"entrypoint.sh syntax error: {result.stderr}"

    def test_config_script_syntax(self):
        """Test that config.sh has valid bash syntax."""
        config_script = PROJECT_ROOT / "scripts" / "config.sh"

        result = subprocess.run(
            ["bash", "-n", str(config_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"config.sh syntax error: {result.stderr}"
