#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-schift-extension"
PACK="$(mktemp -d)/verify-pack.agent"
trap 'rm -rf "$(dirname "$PACK")"' EXIT

python3 -m venv "$VENV"
PYTHONPATH="$ROOT/src" "$VENV/bin/python" - <<'PY' "$PACK"
import sys
from pathlib import Path

from apm_bridge.core import create_pack, validate_pack

target = Path(sys.argv[1]).parent
pack = create_pack(
    destination=target,
    name="verify-pack",
    purpose="가벼운 가상환경에서 APM 경계를 확인한다.",
    model="openai/gpt-5.4-mini",
    connectors=["schift-memory", "local-model"],
)
result = validate_pack(pack)
if not result.ok:
    raise SystemExit("\n".join(result.messages))
print(result.artifact)
PY

echo "venv verification passed: standard library only, no model runtime installed"
