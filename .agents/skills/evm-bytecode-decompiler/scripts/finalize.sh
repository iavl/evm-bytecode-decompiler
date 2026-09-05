#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: finalize.sh RUN_DIR PROPOSAL.json" >&2
    exit 2
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

RUN_DIR="$1"
PROPOSAL="$2"
uv run evm-bytecode-decompiler agent validate "$RUN_DIR" "$PROPOSAL"
uv run evm-bytecode-decompiler agent apply "$RUN_DIR" "$PROPOSAL"
uv run evm-bytecode-decompiler agent render "$RUN_DIR"
