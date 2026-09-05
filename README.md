# EVM Bytecode Decompiler

AI-assisted semantic decompiler for EVM runtime bytecode, powered by a pinned
Gigahorse toolchain.

The pipeline keeps deterministic bytecode facts separate from inferred names
and semantics. Every generated Solidity-like file is **reconstructed,
unverified pseudocode**, not recovered source code. AI can annotate names and
explanations; it cannot add or rewrite deterministic operations.

## Quick start

```bash
uv sync
uv run evm-bytecode-decompiler version
uv run evm-bytecode-decompiler decompile tests/fixtures/erc20/runtime.hex --no-ai
```

The command prints the run directory. A typical run contains:

```text
run/
├── input/             # exact runtime and analysis bytecode
├── gigahorse/         # invocation, results, and normalized facts
├── ir/                # versioned canonical evidence IR
├── semantics/         # optional AI annotations and validated candidates
├── output/            # pseudocode, ABI, storage, evidence map, report
├── logs/
└── run.json
```

## Inputs

Raw bytecode and `.hex` files are accepted directly:

```bash
uv run evm-bytecode-decompiler decompile 0x6000 --no-ai
uv run evm-bytecode-decompiler decompile ./contract.hex --no-ai
```

An address requires an RPC endpoint. Historical analysis passes the requested
block tag to `eth_getCode` and never silently substitutes `latest`. The CLI
accepts the address as `TARGET`:

```bash
uv run evm-bytecode-decompiler decompile \
  0x1234567890123456789012345678901234567890 \
  --chain ethereum --rpc-url "$ETH_RPC_URL" --block 20123456 --no-ai
```

## AI semantics

AI is optional. Configure the OpenAI-compatible provider with environment
variables or `evm-bytecode-decompiler.toml`:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=...
uv run evm-bytecode-decompiler decompile ./contract.hex
```

Use `--no-ai` for deterministic-only output. AI annotations are optional
proposals for names and explanations; the deterministic IR always owns the
rendered operations. Provider failures fall back to deterministic pseudocode;
they do not mutate canonical IR. Requests larger than the configured
`max_prompt_bytes` limit are skipped without truncation.
Cache keys include the canonical request, provider endpoint, model, generation
settings, prompt hash, and response schema hash.

Use `--backend builtin` for a deliberately limited offline lifter, or require
`local`/`docker` when a full pinned toolchain is part of the run contract.

## Gigahorse

The repository pins Gigahorse at:

```text
9e9c08d78079638342ca54101b347f1d6781b425
```

Initialize the toolchain and its pinned recursive dependency with:

```bash
git submodule update --init --recursive
uv run evm-bytecode-decompiler doctor
```

Local Gigahorse execution additionally needs Soufflé and the compiled native
functors under `vendor/gigahorse-toolchain/souffle-addon/`. The default
`backend = "auto"` selects a configured local or digest-pinned Docker runner
and otherwise records a partial built-in lifter result. Set `backend =
"local"`, `"docker"`, or `"builtin"` to require a specific backend.

For a reproducible container, build `docker/gigahorse.Dockerfile` with an
immutable `BASE_IMAGE` digest and the full Gigahorse commit:

```bash
docker build \
  --build-arg BASE_IMAGE=<image@sha256:digest> \
  --build-arg GIGAHORSE_COMMIT=9e9c08d78079638342ca54101b347f1d6781b425 \
  -f docker/gigahorse.Dockerfile .
```

The Docker runner rejects mutable image tags and disables network access for
the analysis container. Runtime metadata is retained as a candidate trailer;
the full runtime bytes are sent to the analysis backend.

## Inspecting a run

```bash
uv run evm-bytecode-decompiler explain RUN_DIR --selector 0xa9059cbb
uv run evm-bytecode-decompiler render RUN_DIR --annotated
uv run evm-bytecode-decompiler validate RUN_DIR
uv run evm-bytecode-decompiler decompile ./contract.hex --resume --no-ai
```

Useful environment checks:

```bash
uv run evm-bytecode-decompiler doctor
uv run evm-bytecode-decompiler cache stats
uv run evm-bytecode-decompiler cache clear
```

Runs are published only after all structured artifacts pass validation. The
manifest records the input, backend/toolchain identity, AI configuration
fingerprint, and hashes for every artifact; `--resume` reuses a run only when
that identity and every hash still match.

## Benchmark

`benchmarks/manifest.json` contains 20 source fixtures covering storage,
tokens, access control, mappings, arrays, structs, errors, events, loops,
internal functions, proxies, CREATE2, assembly, and multiple Solidity eras.
The benchmark compiles source first and passes only runtime bytecode to the
decompiler:

```bash
uv run evm-bytecode-decompiler benchmark run \
  --solc /path/to/version-managed-solc \
  --output-dir runs/benchmark
uv run evm-bytecode-decompiler benchmark report --output-dir runs/benchmark
```

Use a compiler matching each fixture pragma; `--strict` fails on compilation
errors or deterministic fixture regressions against the expected facts in the
manifest.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv build
```

The project intentionally does not claim exact source recovery, exploit
generation, transaction tracing, symbolic execution of every path, storage
value fetching, vulnerability classification, or a web service.
