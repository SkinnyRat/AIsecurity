#!/usr/bin/env bash
# Runs INSIDE the container. Reports whether Claude Code and Codex are logged in.
# Exit 0 only if BOTH are authenticated. Lightweight (no token spend) by default;
# pass --roundtrip to additionally do a 1-token live check on each.
set -uo pipefail

roundtrip=false
[ "${1:-}" = "--roundtrip" ] && roundtrip=true

claude_ok=false
codex_ok=false

# Use a persisted Claude OAuth token (from `make docker-login`) if present. This is
# needed when this script runs via `--entrypoint bash` (which bypasses entrypoint.sh).
if [ -s "$HOME/.claude/oauth_token" ] && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/oauth_token")"
fi

# Claude is authed if it has a persisted OAuth token (setup-token), a subscription
# credentials file, or an API key in the environment.
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] || [ -s "$HOME/.claude/.credentials.json" ] || [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  claude_ok=true
fi

# Codex: file-based session in ~/.codex/auth.json; `codex login status` confirms validity.
if codex login status >/dev/null 2>&1; then
  codex_ok=true
elif [ -s "$HOME/.codex/auth.json" ]; then
  codex_ok=true
fi

if $roundtrip; then
  $claude_ok && { claude -p "reply with exactly OK" --model sonnet 2>/dev/null | grep -qi OK || claude_ok=false; }
  $codex_ok && { codex exec -m gpt-5.4-mini -c model_reasoning_effort="low" --skip-git-repo-check \
                   "reply with exactly OK" 2>/dev/null | grep -qi OK || codex_ok=false; }
fi

printf "  claude: %s\n" "$($claude_ok && echo 'logged in' || echo 'NOT logged in')"
printf "  codex:  %s\n" "$($codex_ok && echo 'logged in' || echo 'NOT logged in')"

$claude_ok && $codex_ok && exit 0
exit 1
