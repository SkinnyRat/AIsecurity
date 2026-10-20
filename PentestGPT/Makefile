# PentestGPT Makefile
# Usage: make [target]

.PHONY: help install test test-all test-cov test-verbose test-fast test-backend
.PHONY: lint lint-fix format format-check typecheck clean build watch
.PHONY: check check-agent test-agent check-agent-new test-agent-new run
.PHONY: ci ci-quick
.PHONY: docker-build docker-login docker-auth-status docker-shell docker-run docker-down docker-nuke

# Default target
help:
	@echo "PentestGPT Agent Commands"
	@echo "==================="
	@echo ""
	@echo "Setup:"
	@echo "  make install     Install root + agent dependencies (AGENT_EXTRA=all)"
	@echo ""
	@echo "Development:"
	@echo "  make test         Run root non-Docker tests + maintained-agent tests"
	@echo "  make test-all     Also run Docker contract tests"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make format       Format code (ruff)"
	@echo "  make typecheck    Run type checker (mypy)"
	@echo "  make check        Run lint, format, typecheck, and agent tests"
	@echo "  make ci           Run full CI simulation (lint, format, typecheck, test, build)"
	@echo "  make ci-quick     Run quick CI (skip build step)"
	@echo "  make clean        Clean build artifacts"
	@echo ""
	@echo "Docker (the tool, with persistent Claude + Codex login):"
	@echo "  make docker-build        Build the tool image"
	@echo "  make docker-login        ONE-TIME: log in to Claude + Codex (persists to volumes)"
	@echo "  make docker-auth-status  Check both CLIs are logged in (ROUNDTRIP=1 for live check)"
	@echo "  make docker-run        Pending: framework is not baked into the image yet"
	@echo "  make docker-shell        Interactive shell in the tool container"
	@echo "  make docker-nuke         Remove login volumes (forces re-login)"

# ============================================================================
# Setup
# ============================================================================

AGENT_EXTRA ?= all

install:
	uv sync
	cd pentestgpt_agent && uv sync --extra $(AGENT_EXTRA)

# ============================================================================
# Testing
# ============================================================================

test: test-agent
	uv run python -m pytest tests/ -v --ignore=tests/docker/

test-all: test-agent
	uv run python -m pytest tests/ -v

test-cov:
	uv run python -m pytest tests/ -v --cov=unified_agent --cov-report=term-missing --cov-report=html

test-verbose:
	uv run python -m pytest tests/ -vvs

# Test by category
test-fast:
	uv run python -m pytest tests/ -v -m "not slow"

test-backend:
	uv run python -m pytest tests/test_claude_backend.py tests/test_codex_backend.py -v

# The maintained framework lives in the nested pentestgpt_agent project (its
# own uv env + git-sourced unified-agent). Run its gate from here so the
# top-level `make check`/`make ci` actually cover it.
test-agent:
	cd pentestgpt_agent && uv run python -m pytest -q

check-agent:
	cd pentestgpt_agent && uv run ruff check src tests
	cd pentestgpt_agent && uv run ruff format --check src tests
	cd pentestgpt_agent && uv run mypy src
	cd pentestgpt_agent && uv run python -m pytest -q

# Compatibility aliases for scripts written before the package rename.
test-agent-new: test-agent
check-agent-new: check-agent

# ============================================================================
# Code Quality
# ============================================================================

lint:
	uv run ruff check unified_agent/ pentestgpt_legacy/ tests/

lint-fix:
	uv run ruff check --fix unified_agent/ pentestgpt_legacy/ tests/

format:
	uv run ruff format unified_agent/ pentestgpt_legacy/ tests/

format-check:
	uv run ruff format --check unified_agent/ pentestgpt_legacy/ tests/

typecheck:
	cd pentestgpt_agent && uv run mypy src

# Parent-package lint/format + the full nested framework gate (ruff, format, mypy, tests).
check: lint format-check check-agent
	@echo "All checks passed!"

# ============================================================================
# CI Simulation (End-to-End)
# ============================================================================

# Full CI simulation. Docker has its own CI job and is intentionally excluded here.
ci: check
	uv run python -m pytest tests/ -q --ignore=tests/docker/
	uv build
	cd pentestgpt_agent && uv build
	@echo "CI simulation completed successfully!"

# Quick CI skips package builds.
ci-quick: check
	uv run python -m pytest tests/ -q --ignore=tests/docker/
	@echo "Quick CI simulation completed successfully!"

# ============================================================================
# Build
# ============================================================================

build:
	uv build

clean:
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# ============================================================================
# Local Development
# ============================================================================

# Run the maintained framework locally against an authorized target.
run:
	@test -n "$(TARGET)" || (echo "Set TARGET=... (e.g. http://127.0.0.1:8000)"; exit 1)
	cd pentestgpt_agent && uv run pentestgpt-agent --goal "$(or $(GOAL),Assess the target for exploitable vulnerabilities and capture any CTF flag.)" --target "$(TARGET)" --backend "$(BACKEND)" $(if $(MODEL),--model "$(MODEL)",)

# Watch for changes and run tests
watch:
	uv run ptw tests/ -- -v

# ============================================================================
# Docker (the tool, with persistent Claude + Codex login)
# ============================================================================

DOCKER_IMAGE  ?= pentestgpt:latest
CLAUDE_VOL    ?= pentestgpt-claude
CODEX_VOL     ?= pentestgpt-codex
# Mount the persisted login volumes + a host workspace into a run.
DOCKER_AUTH_MOUNTS = -v $(CLAUDE_VOL):/home/pentester/.claude -v $(CODEX_VOL):/home/pentester/.codex
DOCKER_RUN_MOUNTS  = $(DOCKER_AUTH_MOUNTS) -v $(PWD)/workspace:/workspace
# Run knobs (override on the CLI): TARGET, BACKEND, MODEL, GOAL
BACKEND ?= claude
MODEL   ?=
GOAL    ?= Capture the CTF flag for this authorized benchmark target.

# Build the tool image
docker-build:
	docker build -t $(DOCKER_IMAGE) .

# ONE-TIME: log in to Claude + Codex; persists into named volumes (no re-login after)
docker-login:
	./scripts/docker-login.sh

# Report whether both CLIs are logged in (add ROUNDTRIP=1 for a live 1-token check)
docker-auth-status:
	docker run --rm $(DOCKER_AUTH_MOUNTS) --entrypoint bash $(DOCKER_IMAGE) \
		-lc '/home/pentester/docker-auth-status.sh $(if $(ROUNDTRIP),--roundtrip,)'

# Interactive shell in the tool container (login volumes attached)
docker-shell:
	docker run -it --rm $(DOCKER_RUN_MOUNTS) -e PENTESTGPT_AUTH_MODE=manual $(DOCKER_IMAGE)

# The image currently omits the nested framework. Keep this target as an explicit
# diagnostic instead of failing later with an opaque "command not found".
docker-run:
	@echo "pentestgpt_agent is not baked into $(DOCKER_IMAGE) yet."
	@echo "Use 'make run TARGET=...' locally until a supported framework image is implemented."
	@exit 2

# Stop/remove the compose container but KEEP the login volumes (stay logged in)
docker-down:
	docker compose down

# Remove the persisted login volumes (forces a fresh `make docker-login`)
docker-nuke:
	-docker volume rm $(CLAUDE_VOL) $(CODEX_VOL)
