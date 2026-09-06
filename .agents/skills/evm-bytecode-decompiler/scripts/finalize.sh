#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: finalize.sh RUN_DIR PROPOSAL.json" >&2
    exit 2
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

has_repo_layout() {
    [ -f "$1/pyproject.toml" ] && [ -d "$1/src/evm_bytecode_decompiler" ]
}

if [ -n "${EVM_BYTECODE_DECOMPILER_REPO:-}" ]; then
    REPO_ROOT="$EVM_BYTECODE_DECOMPILER_REPO"
else
    CANDIDATE="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
    if [ -n "$CANDIDATE" ] && has_repo_layout "$CANDIDATE"; then
        REPO_ROOT="$CANDIDATE"
    else
        REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd)"
    fi
fi

if ! has_repo_layout "$REPO_ROOT"; then
    echo "error: evm-bytecode-decompiler checkout not found" >&2
    echo "       set EVM_BYTECODE_DECOMPILER_REPO to the repository path" >&2
    exit 1
fi

REPO_ROOT="$(CDPATH= cd -- "$REPO_ROOT" && pwd)"
cd "$REPO_ROOT"

RUN_DIR="$1"
PROPOSAL="$2"
uv run evm-bytecode-decompiler agent validate "$RUN_DIR" "$PROPOSAL"
uv run evm-bytecode-decompiler agent apply "$RUN_DIR" "$PROPOSAL"
uv run evm-bytecode-decompiler agent render "$RUN_DIR"
