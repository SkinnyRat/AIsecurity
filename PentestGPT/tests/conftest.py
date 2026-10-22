"""Shared pytest configuration for PentestGPT tests."""

import pytest

# =============================================================================
# Pytest Markers
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests (may use mocks)")
    config.addinivalue_line("markers", "docker: Docker tests (requires Docker daemon)")
    config.addinivalue_line("markers", "slow: Slow tests (skip with -m 'not slow')")
