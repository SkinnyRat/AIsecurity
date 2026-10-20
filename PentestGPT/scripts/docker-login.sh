#!/usr/bin/env bash
# Idempotent login for the PentestGPT Docker tool.
#
# It FIRST checks (with a live round-trip) whether Claude Code and Codex are already
# logged in via their persisted named volumes, and ONLY runs the login flow for the
# one(s) that are not. Re-running it is safe — already-valid sessions are skipped.
#
#   Codex  -> the container gets its OWN `codex login` (ChatGPT refresh tokens are
#             single-use, so a copied/shared login breaks on first refresh). The
#             localhost:1455 OAuth callback is forwarded into the container via socat.
#   Claude -> `claude setup-token` (works on macOS, where host creds live in the
#             Keychain); the long-lived token is stored in the volume.
set -euo pipefail

IMAGE="${PENTESTGPT_IMAGE:-pentestgpt:latest}"
CLAUDE_VOL="${PENTESTGPT_CLAUDE_VOL:-pentestgpt-claude}"
CODEX_VOL="${PENTESTGPT_CODEX_VOL:-pentestgpt-codex}"

bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }

docker volume create "$CLAUDE_VOL" >/dev/null
docker volume create "$CODEX_VOL" >/dev/null

# --- live, truthful "is it actually working?" checks (a present-but-stale token fails) ---
codex_live_ok() {
  docker run --rm -v "$CODEX_VOL":/home/pentester/.codex --entrypoint bash "$IMAGE" -lc '
    codex exec -m gpt-5.4-mini -c model_reasoning_effort="low" --skip-git-repo-check \
      "reply with exactly OK" 2>/dev/null | grep -qiw ok' >/dev/null 2>&1
}
claude_live_ok() {
  docker run --rm -v "$CLAUDE_VOL":/home/pentester/.claude --entrypoint bash "$IMAGE" -lc '
    [ -s "$HOME/.claude/oauth_token" ] || exit 1
    export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/oauth_token")"
    claude -p "reply with exactly OK" --model sonnet 2>/dev/null | grep -qiw ok' >/dev/null 2>&1
}

# --- login flows (only invoked when the live check fails) ---
do_codex_login() {
  echo "Codex needs login. A URL will be printed: open it in your browser and approve."
  echo "(It's a separate session from your host; the localhost:1455 callback is forwarded in via socat.)"
  echo
  docker run -it --rm -p 1455:8455 \
    -v "$CODEX_VOL":/home/pentester/.codex \
    --entrypoint bash "$IMAGE" -lc '
      socat TCP-LISTEN:8455,fork,reuseaddr TCP:127.0.0.1:1455 >/dev/null 2>&1 &
      codex login'
}
do_claude_login() {
  echo "Claude needs login. Running 'claude setup-token' — approve in your browser, then COPY"
  echo "the printed token (starts 'sk-ant-oat01-'). Do NOT share it; paste it at the hidden prompt."
  echo
  docker run -it --rm \
    -v "$CLAUDE_VOL":/home/pentester/.claude \
    --entrypoint bash "$IMAGE" -lc 'claude setup-token'
  echo
  printf "Paste the Claude token here (input hidden): "
  read -rs CLAUDE_TOKEN; echo
  if [ -z "${CLAUDE_TOKEN:-}" ]; then
    echo "No token entered." >&2; return 1
  fi
  # Persist via stdin (never printed or passed as an argument/env).
  printf '%s' "$CLAUDE_TOKEN" | docker run -i --rm \
    -v "$CLAUDE_VOL":/home/pentester/.claude \
    --entrypoint bash "$IMAGE" -c 'umask 077; cat > /home/pentester/.claude/oauth_token && echo "  stored Claude token in the volume"'
  unset CLAUDE_TOKEN
}

bold "==> Checking existing logins (live)…"
codex_was_ok=false; claude_was_ok=false
if codex_live_ok;  then codex_was_ok=true;  echo "  codex:  already logged in ✓"; else echo "  codex:  not logged in"; fi
if claude_live_ok; then claude_was_ok=true; echo "  claude: already logged in ✓"; else echo "  claude: not logged in"; fi

if $codex_was_ok && $claude_was_ok; then
  bold "Both Claude and Codex are already logged in and persisted — nothing to do."
  exit 0
fi

# --- log in only the missing one(s) ---
if ! $codex_was_ok; then bold "==> Codex login"; do_codex_login; fi
if ! $claude_was_ok; then bold "==> Claude Code login"; do_claude_login; fi

bold "==> Verifying (live round-trip)…"
fail=0
codex_live_ok  && echo "  codex:  logged in ✓"  || { echo "  codex:  NOT logged in"; fail=1; }
claude_live_ok && echo "  claude: logged in ✓"  || { echo "  claude: NOT logged in"; fail=1; }
if [ "$fail" -eq 0 ]; then
  bold "Done — Claude and Codex are logged in and persisted. You won't need to log in again."
else
  echo; echo "One or both logins did not verify. Re-run 'make docker-login'." >&2
  exit 1
fi
