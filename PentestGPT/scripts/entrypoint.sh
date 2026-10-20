#!/usr/bin/env bash
# PentestGPT Container Entrypoint
# Sets up authentication based on PENTESTGPT_AUTH_MODE environment variable

set -e

AUTH_MODE="${PENTESTGPT_AUTH_MODE:-manual}"
CCR_CONFIG_DIR="/home/pentester/.claude-code-router"
CCR_CONFIG_FILE="${CCR_CONFIG_DIR}/config.json"
BASHRC_FILE="/home/pentester/.bashrc"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Router configurations for different modes
OPENROUTER_ROUTER='{"default":"openrouter,openai/gpt-5.1","background":"openrouter,openai/gpt-5.1","think":"openrouter,openai/gpt-5.1","longContext":"openrouter,openai/gpt-5.1","longContextThreshold":60000,"webSearch":"openrouter,google/gemini-3-pro-preview"}'
LOCAL_ROUTER='{"default":"localLLM,openai/gpt-oss-20b","background":"localLLM,openai/gpt-oss-20b","think":"localLLM,qwen/qwen3-coder-30b","longContext":"localLLM,qwen/qwen3-coder-30b","longContextThreshold":60000,"webSearch":"localLLM,openai/gpt-oss-20b"}'

setup_ccr() {
    local mode="$1"
    local api_key="$2"
    local template_file="/app/scripts/ccr-config-template.json"

    # Create CCR config directory if needed
    mkdir -p "$CCR_CONFIG_DIR"

    # Check if template exists
    if [ ! -f "$template_file" ]; then
        echo -e "${YELLOW}Error: CCR config template not found at $template_file${NC}"
        exit 1
    fi

    # Copy template and substitute placeholders
    cp "$template_file" "$CCR_CONFIG_FILE"

    # Substitute API key (for openrouter mode)
    if [ -n "$api_key" ]; then
        sed -i "s/__OPENROUTER_API_KEY__/${api_key}/g" "$CCR_CONFIG_FILE"
    fi

    # Substitute Router config based on mode (use | as delimiter to avoid conflicts with /)
    if [ "$mode" = "openrouter" ]; then
        sed -i "s|\"__ROUTER_CONFIG__\"|${OPENROUTER_ROUTER}|g" "$CCR_CONFIG_FILE"
        local display_model="openai/gpt-5.1"
    else
        sed -i "s|\"__ROUTER_CONFIG__\"|${LOCAL_ROUTER}|g" "$CCR_CONFIG_FILE"
        local display_model="localLLM (qwen/qwen3-coder-30b, openai/gpt-oss-20b)"
    fi

    echo -e "${BLUE}Starting Claude Code Router...${NC}"

    # Start CCR daemon (nohup to keep it running)
    nohup ccr start > /tmp/ccr.log 2>&1 &

    # Wait for CCR to be ready
    sleep 2

    # Check if CCR is running by testing the port
    if nc -z 127.0.0.1 3456 2>/dev/null; then
        echo -e "${GREEN}CCR daemon running on port 3456${NC}"
    else
        echo -e "${YELLOW}Warning: CCR may not have started properly. Check /tmp/ccr.log${NC}"
    fi

    # Add CCR activation to .bashrc so it persists in interactive shells
    # Remove any existing ccr activation lines first
    sed -i '/# CCR activation/d' "$BASHRC_FILE" 2>/dev/null || true
    sed -i '/eval "$(ccr activate)"/d' "$BASHRC_FILE" 2>/dev/null || true

    # Add ccr activation to bashrc
    echo "# CCR activation for ${mode}" >> "$BASHRC_FILE"
    echo 'eval "$(ccr activate 2>/dev/null)" || true' >> "$BASHRC_FILE"

    # Also export for the current session (will be inherited by exec'd shell)
    eval "$(ccr activate 2>/dev/null)" || true

    echo -e "${GREEN}CCR activated with ${mode} backend${NC}"
    echo -e "${BLUE}Default model: ${display_model}${NC}"
}

# Load a persisted Claude OAuth token (created once via `make docker-login`,
# stored in the claude-config volume) so `claude` authenticates non-interactively.
if [ -s "$HOME/.claude/oauth_token" ]; then
    export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/oauth_token")"
fi

echo ""
echo -e "${BLUE}=== PentestGPT Authentication ===${NC}"

case "$AUTH_MODE" in
    openrouter)
        if [ -z "$OPENROUTER_API_KEY" ]; then
            echo -e "${YELLOW}Error: OPENROUTER_API_KEY not set${NC}"
            echo "Please run 'make config' and select OpenRouter option"
            exit 1
        fi
        setup_ccr "openrouter" "$OPENROUTER_API_KEY"
        ;;
    local)
        echo -e "${GREEN}Local LLM mode${NC}"
        echo -e "Ensure your local LLM server is running on host.docker.internal:1234"
        setup_ccr "local" ""
        ;;
    anthropic)
        if [ -z "$ANTHROPIC_API_KEY" ]; then
            echo -e "${YELLOW}Warning: ANTHROPIC_API_KEY not set${NC}"
            echo "Please run 'make config' and select Anthropic option"
        else
            echo -e "${GREEN}Using Anthropic API key${NC}"
        fi
        ;;
    manual)
        echo -e "${GREEN}Subscription / persisted-login mode${NC}"
        # Non-blocking preflight: report whether the persisted Claude + Codex
        # sessions are present (set up once via `make docker-login` on the host).
        if [ -x /home/pentester/docker-auth-status.sh ] && ! /home/pentester/docker-auth-status.sh; then
            echo -e "${YELLOW}One or both CLIs are not logged in.${NC}"
            echo -e "Run ${GREEN}make docker-login${NC} on the host once to persist both sessions."
        fi
        ;;
    *)
        echo -e "${YELLOW}Unknown auth mode: $AUTH_MODE${NC}"
        echo "Defaulting to manual login mode"
        echo -e "Run ${GREEN}claude login${NC} to authenticate"
        ;;
esac

echo -e "${BLUE}=================================${NC}"
echo ""

# Execute the passed command or start bash
# Use bash -l to ensure .bashrc is sourced (for ccr activation)
if [ "$1" = "/bin/bash" ]; then
    exec /bin/bash --login
else
    exec "$@"
fi
