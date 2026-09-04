# EVM Bytecode Decompiler

AI-assisted semantic decompiler for EVM bytecode, powered by Gigahorse.

The implementation provides deterministic input normalization, a pinned
Gigahorse adapter, canonical IR, selector/storage inference, optional
structured AI semantics/synthesis, validation, caching, and benchmark tooling.
Output is reconstructed from bytecode and is **not verified source code**.

## Quick start

```bash
uv sync
uv run evm-bytecode-decompiler version
uv run evm-bytecode-decompiler decompile tests/fixtures/erc20/runtime.hex --no-ai
```

Use `--rpc-url` and `--block` for an address. A block number is always passed
through explicitly to `eth_getCode`.

Set `OPENAI_API_KEY` and `OPENAI_MODEL` to enable the optional OpenAI-compatible
semantic passes. `--no-ai` always stays deterministic, and provider failures
fall back to deterministic pseudocode.

Saved runs can be inspected or regenerated with `explain`, `render`, and
`validate`. Run the 20-source benchmark with `benchmark run`; use a compiler
matching each fixture's pragma.

Gigahorse is optional for the deterministic checkpoint: when no executable is
configured, the built-in bytecode lifter produces a limited, clearly labeled
fallback workspace. Configure a pinned Gigahorse Docker image or local binary
for full relation extraction.

The reproducible Docker build requires both an immutable `BASE_IMAGE` digest
and a full Gigahorse commit; see `docker/gigahorse.Dockerfile`.

## Project status

The plan's Phase 13 fixture set is included. Full Gigahorse execution requires
the pinned submodule's Soufflé and native functors to be built, or a digest-
pinned Docker image to be configured. In environments without those tools,
the CLI reports and uses its limited deterministic fallback explicitly.
