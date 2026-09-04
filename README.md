# EVM Bytecode Decompiler

AI-assisted semantic decompiler for EVM bytecode, powered by Gigahorse.

The current checkpoint implements deterministic input normalization, a
Gigahorse adapter, canonical IR, selector/storage inference, and readable
`--no-ai` pseudocode. Output is reconstructed from bytecode and is **not
verified source code**.

## Quick start

```bash
uv sync
uv run evm-bytecode-decompiler version
uv run evm-bytecode-decompiler decompile tests/fixtures/erc20/runtime.hex --no-ai
```

Use `--rpc-url` and `--block` for an address. A block number is always passed
through explicitly to `eth_getCode`.

Gigahorse is optional for the deterministic checkpoint: when no executable is
configured, the built-in bytecode lifter produces a limited, clearly labeled
fallback workspace. Configure a pinned Gigahorse Docker image or local binary
for full relation extraction.

The reproducible Docker build requires both an immutable `BASE_IMAGE` digest
and a full Gigahorse commit; see `docker/gigahorse.Dockerfile`.

## Project status

Phases 0–6 of `plan.md` are the implemented checkpoint. AI semantic passes,
structured synthesis, and benchmark orchestration remain future phases.
