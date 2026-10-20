# Docker runtime status

Status: 2026-07-12

This document describes the repository as it exists now. It replaces the original implementation
plan, whose phase matrix and in-repo benchmark paths are obsolete.

## Current image responsibility

`pentestgpt:latest` is a disposable pentest-tool and provider-CLI environment. It contains:

- Ubuntu 24.04, Python 3.12, Node 20, `uv`, Claude Code, and Codex;
- common network/pentest tools such as nmap, gobuster, dirb, netcat, curl, DNS utilities, jq, and
  ripgrep;
- the root `pentestgpt_legacy` package;
- the old root `unified_agent` compatibility copy;
- persistent Claude and Codex authentication helpers.

It deliberately excludes benchmark fixtures/results, credentials, workspaces, and run artifacts.

The maintained `pentestgpt_agent` nested project is **not baked into this image**. Consequently,
`make docker-run` deliberately fails fast with a wiring diagnostic instead of invoking an absent
CLI. There is no product-owned benchmark workaround; framework-image wiring remains an independent
deployment task.

## Repository ownership

```text
PentestGPT/          image, auth helpers, framework source, legacy client
UnifedAgentWrapper/  canonical provider-wrapper package
xbow-benchmark/      reference-only benchmark harness and historical results
```

The product does not support or invoke the sibling benchmark harness. Keep result JSONL, target
orchestration, and benchmark-specific adapters out of this repository.

## Persistent provider login

Authentication state lives in named volumes and is never copied into image layers:

```text
pentestgpt-claude -> /home/pentester/.claude
pentestgpt-codex  -> /home/pentester/.codex
```

The providers require different setup paths:

- Claude uses a long-lived `setup-token`, stored as `.claude/oauth_token` and exported as
  `CLAUDE_CODE_OAUTH_TOKEN` by the entrypoint.
- Codex performs its own in-container OAuth login. Its callback is forwarded through a `socat` hop;
  host `auth.json` must not be copied because ChatGPT refresh tokens rotate.

Useful commands:

```bash
make docker-build
make docker-login
make docker-auth-status
ROUNDTRIP=1 make docker-auth-status   # spends a minimal provider call
make docker-shell
make docker-down                      # keeps auth volumes
make docker-nuke                      # deliberately removes auth volumes
```

The auth-status check is advisory by default. Named volumes are credentials and must be protected
like a logged-in workstation.

## Isolation contract

Both PentestGPT roles use provider `FULL_ACCESS`. The container or dedicated attack box is therefore
the blast radius and security boundary. A deployment must:

- contain only authorized target routes;
- avoid mounting unrelated source, home directories, tokens, or host sockets;
- mount run state only when persistence is required;
- treat traces and SQLite state as sensitive;
- tear down the environment after the assessment.

The tool image runs as `pentester`, which has passwordless sudo. It is isolation from the developer
host only when mounts, capabilities, devices, and networking are deliberately constrained.

## Framework-image decision still open

There are two reasonable future shapes:

1. Build framework and `unified-agent` wheels outside Docker, then copy them into a dedicated runtime
   image. This matches the proven qualification runner and preserves exact package hashes.
2. Publish both packages and install pinned releases during the Docker build.

Do not copy the root `unified_agent/` directory into the maintained framework. It is version 0.1-era
compatibility code; the agent requires the pinned external 0.3 package.

Whichever shape is selected must make these checks true in a fresh container:

```bash
pentestgpt-agent --help
python -c "import pentestgpt_agent, unified_agent; print(unified_agent.__version__)"
```

Only after that should `make docker-run` be advertised as supported.

## Build cleanup opportunities

These are independent of framework design:

- remove `apt-get upgrade` for faster, more reproducible builds;
- install `socat` in the main apt layer;
- combine global npm installs;
- use BuildKit cache mounts for apt, npm, and uv;
- install from lockfiles/wheels before copying frequently changing source;
- remove the root `unified_agent` copy and its SDK dependencies when the public-package cleanup is
  performed.

## External benchmark reference

The sibling `xbow-benchmark` repository is retained only for historical reference. The product
Makefile, CLI, CI, and Docker runtime do not invoke it. If a future evaluation reuses that corpus,
design the adapter in an external evaluation repository rather than restoring a benchmark runner
inside PentestGPT.
