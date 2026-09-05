#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

command -v uv >/dev/null
uv run evm-bytecode-decompiler doctor
git submodule status --recursive -- vendor/gigahorse-toolchain
