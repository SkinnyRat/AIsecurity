# PentestGPT tool image
# Disposable pentest environment and provider CLIs; the nested framework is installed separately.

FROM ubuntu:24.04

LABEL description="PentestGPT disposable pentest tool and provider-CLI environment"
LABEL version="1.0.0"

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# Update and install system dependencies
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
    # Build essentials
    build-essential \
    software-properties-common \
    ca-certificates \
    gnupg \
    # Python
    python3.12 \
    python3-pip \
    python3-venv \
    python3-dev \
    # Essential pentesting tools
    nmap \
    gobuster \
    dirb \
    netcat-openbsd \
    curl \
    wget \
    git \
    sudo \
    # Network utilities
    net-tools \
    dnsutils \
    whois \
    # VPN (for HackTheBox/TryHackMe connectivity)
    openvpn \
    # Text processing
    jq \
    ripgrep \
    # Terminal
    tmux \
    && apt-get autoremove -y \
    && apt-get autoclean \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js v20 (required for Claude Code Router)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Remove EXTERNALLY-MANAGED marker to allow pip installs in Docker
# Also remove system Python packages that conflict with dependencies
RUN rm -f /usr/lib/python3.*/EXTERNALLY-MANAGED && \
    apt-get remove -y python3-cryptography && \
    apt-get autoremove -y

# Install Claude Code Router globally (for OpenRouter/local LLM support)
RUN npm install -g @musistudio/claude-code-router

# Install the OpenAI Codex CLI globally (used by the shared backend substrate)
RUN npm install -g @openai/codex

# Create non-root user
RUN useradd -m -s /bin/bash pentester && \
    usermod -aG sudo pentester && \
    echo "pentester ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Set up working directories (claude + codex auth dirs are owned by pentester so the
# named volumes mounted there at runtime inherit the right ownership on first use)
RUN mkdir -p /workspace /app /home/pentester/.claude /home/pentester/.codex /home/pentester/.claude-code-router && \
    chown -R pentester:pentester /workspace /app /home/pentester/.claude /home/pentester/.codex /home/pentester/.claude-code-router

# Switch to pentester user
USER pentester
WORKDIR /app

# Install Claude Code CLI (native installer — no npm needed)
RUN curl -fsSL https://claude.ai/install.sh | bash

# Install uv for Python dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/home/pentester/.local/bin:$PATH"

# Copy root compatibility substrate + legacy CLI, declared in the root wheel.
# NOTE: the benchmark harness is deliberately NOT in the image; it stays outside
# and drives this container against targets.
# NOTE: the maintained framework now lives in the nested pentestgpt_agent
# project (its own uv env + git-sourced unified-agent) and is not yet baked into
# this image; in-container benchmarking of it is a pending rewire (deprioritized).
COPY --chown=pentester:pentester pyproject.toml README.md /app/
COPY --chown=pentester:pentester unified_agent/ /app/unified_agent/
COPY --chown=pentester:pentester pentestgpt_legacy/ /app/pentestgpt_legacy/
COPY --chown=pentester:pentester scripts/entrypoint.sh /home/pentester/entrypoint.sh
COPY --chown=pentester:pentester scripts/docker-auth-status.sh /home/pentester/docker-auth-status.sh
COPY --chown=pentester:pentester scripts/ccr-config-template.json /app/scripts/ccr-config-template.json

# Install Python dependencies as root to system Python
ENV PIP_BREAK_SYSTEM_PACKAGES=1
USER root
RUN /home/pentester/.local/bin/uv pip install --system /app && \
    chmod +x /home/pentester/entrypoint.sh /home/pentester/docker-auth-status.sh

# socat forwards the Codex OAuth localhost:1455 callback into the container during `make docker-login`
# (kept as a late layer so it doesn't invalidate the apt/pip cache above).
RUN apt-get update && apt-get install -y --no-install-recommends socat && rm -rf /var/lib/apt/lists/*

# Switch back to pentester user for runtime
USER pentester

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default working directory for penetration tests
WORKDIR /workspace

# Use entrypoint script for auth setup
ENTRYPOINT ["/home/pentester/entrypoint.sh"]

# Default command - interactive bash
# (The maintained pentestgpt_agent framework is not baked into this image
# yet; see the COPY note above. The container ships the tools + substrate.)
CMD ["/bin/bash"]
