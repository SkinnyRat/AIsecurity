#!/usr/bin/env bash
set -euo pipefail

plugin_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
patch_file="$plugin_root/patches/openharness-bare-plugin-commands.patch"
plugin_source="$plugin_root/.openharness/plugins/dependency_audit"

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

[[ -f "$patch_file" ]] || fail "Patch not found: $patch_file"
[[ -d "$plugin_source" ]] || fail "Plugin folder not found: $plugin_source"
command -v git >/dev/null 2>&1 || fail "Git is required but was not found on PATH."
command -v python3 >/dev/null 2>&1 || fail "python3 is required to update settings safely."

while :; do
    read -r -p "Path to your OpenHarness checkout: " openharness_input
    [[ -n "${openharness_input//[[:space:]]/}" ]] && break
    printf 'Enter the path to the OpenHarness checkout.\n'
done

[[ -d "$openharness_input" ]] || fail "Directory not found: $openharness_input"
openharness_path="$(cd -- "$openharness_input" && pwd -P)"
[[ -e "$openharness_path/.git" ]] || fail "That path is not a Git checkout: $openharness_input"

if git -C "$openharness_path" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
    printf 'OpenHarness patch is already applied.\n'
else
    if ! git -C "$openharness_path" apply --check "$patch_file"; then
        fail "Patch does not apply cleanly. Confirm this checkout uses the supported upstream revision and has no conflicting edits."
    fi
    git -C "$openharness_path" apply "$patch_file" || fail "Failed to apply OpenHarness patch."
    printf 'Applied OpenHarness patch.\n'
fi

plugin_destination_root="$openharness_path/.openharness/plugins"
plugin_destination="$plugin_destination_root/dependency_audit"
mkdir -p -- "$plugin_destination_root"
if [[ -e "$plugin_destination" ]]; then
    read -r -p "Plugin already exists at '$plugin_destination'. Replace it? [y/N] " answer
    case "$answer" in
        y|Y|yes|YES|Yes) rm -rf -- "$plugin_destination" ;;
        *) fail "Setup cancelled before replacing the existing plugin." ;;
    esac
fi
cp -a -- "$plugin_source" "$plugin_destination"
find "$plugin_destination" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$plugin_destination" -type f -name '*.pyc' -delete

# Honor OpenHarness's config directory override, otherwise use ~/.openharness.
config_dir="${OPENHARNESS_CONFIG_DIR:-$HOME/.openharness}"
mkdir -p -- "$config_dir"
settings_path="$config_dir/settings.json"
python3 - "$settings_path" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

settings_path = Path(sys.argv[1])
try:
    if settings_path.exists():
        with settings_path.open(encoding="utf-8") as stream:
            settings = json.load(stream)
    else:
        settings = {}
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"Error: could not read settings JSON at {settings_path}: {exc}")

if not isinstance(settings, dict):
    raise SystemExit(f"Error: settings must contain a JSON object: {settings_path}")
enabled_plugins = settings.setdefault("enabled_plugins", {})
if not isinstance(enabled_plugins, dict):
    raise SystemExit("Error: 'enabled_plugins' in settings must be a JSON object.")
settings["allow_project_plugins"] = True
enabled_plugins["dependency_audit"] = True

fd, temporary_name = tempfile.mkstemp(prefix=f".{settings_path.name}.", dir=settings_path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(settings, stream, indent=2)
        stream.write("\n")
    os.replace(temporary_name, settings_path)
except Exception:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
    raise
PY

printf 'Enabled project plugins and dependency_audit in %s\n' "$settings_path"
printf 'Setup complete. Start OpenHarness from: %s\n' "$openharness_path"
