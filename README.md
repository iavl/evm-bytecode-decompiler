# EVM Bytecode Decompiler

Deterministic EVM runtime analysis with optional evidence-grounded semantic
reconstruction through a Codex Agent Skill. The Python package never calls a
model service. Generated Solidity-like output is always **reconstructed,
unverified pseudocode**, not recovered source code.

See [How It Works](docs/how-it-works.md) for the architecture and trust model.

## Quick start

```bash
uv sync
uv run evm-bytecode-decompiler version
uv run evm-bytecode-decompiler decompile tests/fixtures/erc20/runtime.hex \
  --backend builtin
```

The command prints a run directory. The built-in backend is a limited offline
EVM lifter; it is a partial fallback, not full Gigahorse. The default
`backend = "auto"` prefers a configured digest-pinned Docker or ready local
Gigahorse runner and otherwise records that fallback explicitly.

`--no-ai` remains accepted as a deprecated compatibility flag. It is no longer
needed: normal CLI analysis is deterministic and does not inspect or require
model credentials.

## Install the Agent Skill

The repository-local Skill is already available at
`.agents/skills/evm-bytecode-decompiler/`. To install independent copies for
both Codex and Claude Code:

```bash
./install.sh
```

The default destinations are:

```text
${CODEX_HOME:-$HOME/.codex}/skills/evm-bytecode-decompiler
${CLAUDE_HOME:-$HOME/.claude}/skills/evm-bytecode-decompiler
```

Install only one target when needed:

```bash
./install.sh --target codex
./install.sh --target claude
```

The installer copies the Skill files but does not install Python dependencies,
Gigahorse, or a global CLI. Keep this checkout available and use `uv run` for
the deterministic CLI. When a globally installed wrapper is invoked outside
the checkout, set the repository explicitly:

```bash
EVM_BYTECODE_DECOMPILER_REPO=/path/to/evm-bytecode-decompiler \
  ~/.codex/skills/evm-bytecode-decompiler/scripts/preflight.sh
```

The installer refuses to overwrite any existing destination, including a
symbolic link. To update an installation, remove the exact target directory
after checking it and run the installer again. Use `CODEX_HOME` and
`CLAUDE_HOME` to select non-default home directories:

```bash
CODEX_HOME=/custom/codex CLAUDE_HOME=/custom/claude ./install.sh
```

Verify an installation with:

```bash
test -f "$HOME/.codex/skills/evm-bytecode-decompiler/SKILL.md"
test -f "$HOME/.claude/skills/evm-bytecode-decompiler/SKILL.md"
```

## Inputs

Raw runtime bytecode and `.hex` files are accepted directly:

```bash
uv run evm-bytecode-decompiler decompile 0x6000 --backend builtin
uv run evm-bytecode-decompiler decompile ./contract.hex --backend builtin
```

An address requires an RPC endpoint. A requested historical block is passed
unchanged to `eth_getCode`; it is never silently replaced with `latest`:

```bash
uv run evm-bytecode-decompiler decompile \
  0x1234567890123456789012345678901234567890 \
  --chain ethereum --rpc-url "$ETH_RPC_URL" --block 20123456
```

## Codex and Claude Code Agent Skill

The repository-local Skill is at
`.agents/skills/evm-bytecode-decompiler/`. Ask Codex or Claude Code explicitly
when needed:

> Use `evm-bytecode-decompiler` to analyze this bytecode and explain the
> recovered evidence.

The same Skill can be invoked by Claude Code after installation. It runs the
deterministic CLI, reads bounded context, reasons about names/roles/storage
labels/summaries, writes a strict proposal, and asks the CLI to validate and
render it. It does not synthesize or replace function bodies. No
`OPENAI_API_KEY`, `OPENAI_MODEL`, or external provider setup is required for
this workflow.

The same workflow is available manually:

```bash
uv run evm-bytecode-decompiler context RUN_DIR
uv run evm-bytecode-decompiler context RUN_DIR --selector 0xa9059cbb
uv run evm-bytecode-decompiler agent validate RUN_DIR proposal.json
uv run evm-bytecode-decompiler agent apply RUN_DIR proposal.json
uv run evm-bytecode-decompiler agent render RUN_DIR
```

Invalid function IDs, selectors, evidence references, storage references,
confidence values, extra fields, or fingerprints are rejected. Applying an
overlay does not modify canonical IR or deterministic output hashes.

## Gigahorse

The full toolchain is pinned through:

```text
vendor/gigahorse-toolchain @ 9e9c08d78079638342ca54101b347f1d6781b425
```

Initialize the recursive submodules and inspect readiness with:

```bash
git submodule update --init --recursive
uv run evm-bytecode-decompiler doctor
```

Local Gigahorse additionally needs Soufflé and the compiled native functors in
`vendor/gigahorse-toolchain/souffle-addon/`. For a reproducible container, use
an immutable base image digest:

```bash
docker build \
  --build-arg BASE_IMAGE=<image@sha256:digest> \
  --build-arg GIGAHORSE_COMMIT=9e9c08d78079638342ca54101b347f1d6781b425 \
  -f docker/gigahorse.Dockerfile .
```

The Docker runner disables network access and rejects mutable image tags.

## Run artifacts and inspection

Each deterministic run separates canonical evidence from optional semantics:

```text
RUN_DIR/
├── input/                 # normalized runtime bytes and input metadata
├── gigahorse/             # invocation, results, and normalized relations
├── ir/                    # canonical ContractIR
├── output/                # deterministic ABI, storage, pseudocode, report
├── logs/
├── run.json               # deterministic fingerprint and artifact hashes
└── agent/                 # optional validated semantic overlay
    ├── proposal.json
    ├── annotations.json
    ├── manifest.json
    ├── decompiled.annotated.sol
    └── report.md
```

Useful commands:

```bash
uv run evm-bytecode-decompiler explain RUN_DIR --selector 0xa9059cbb
uv run evm-bytecode-decompiler render RUN_DIR
uv run evm-bytecode-decompiler validate RUN_DIR
uv run evm-bytecode-decompiler decompile ./contract.hex --resume
```

`run.json` contains only deterministic identity and artifact hashes. Agent
manifests bind their validated annotation hash to that fingerprint and are not
added to the canonical artifact index.

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

Use a compiler matching each fixture pragma. `--strict` fails on compilation
errors or deterministic regressions; a missing compiler version is reported as
unavailable rather than as a decompiler result.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv build
```

The project does not claim exact source recovery, exploit generation,
transaction tracing, symbolic execution of every path, storage-value fetching,
vulnerability classification, or a web service.
