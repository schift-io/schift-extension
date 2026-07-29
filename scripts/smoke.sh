#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PYTHONPATH="$ROOT/src" python3 "$ROOT/src/apm_bridge/cli.py" install \
  --host both --hooks --root "$TMP"

mkdir -p "$TMP/source"
cat > "$TMP/source/SKILL.md" <<'EOF'
# Fixture Skill

Use Schift memory only for the stated user task.
EOF

PYTHONPATH="$ROOT/src" python3 "$ROOT/src/apm_bridge/cli.py" import \
  --source "$TMP/source" \
  --name fixture-pack \
  --purpose "fixture skill을 검증 가능한 APM으로 전환한다." \
  --connector schift-memory \
  --connector local-model \
  --output "$TMP/workspace"

test -f "$TMP/.codex/config.toml"
test -f "$TMP/.claude/settings.json"
test -f "$TMP/workspace/fixture-pack.agent/dist/fixture-pack-0.1.0.apm"
PYTHONPATH="$ROOT/src" python3 "$ROOT/src/apm_bridge/cli.py" uninstall --host both --root "$TMP"
! rg -q 'BEGIN SCHIFT EXTENSION' "$TMP/.codex/config.toml"
echo "smoke passed"
