---
name: evm-bytecode-decompiler
description: Analyze and semantically reconstruct EVM runtime bytecode or deployed contracts using this repository's deterministic decompiler and Gigahorse evidence. Use for EVM bytecode decompilation, understanding unverified contracts, recovering function or storage semantics, or producing evidence-grounded Solidity-like pseudocode.
---

# EVM Bytecode Decompiler

Use the repository's local CLI as the deterministic evidence boundary. The
active Codex agent performs semantic interpretation; the Python package never
calls a model service.

## Workflow

1. Locate the repository and run `scripts/preflight.sh` (or the equivalent
   `doctor` command).
2. Normalize the requested raw bytecode, `.hex` file, or address. For an
   address, pass the requested chain, RPC endpoint, and historical block.
3. Run `scripts/analyze.sh` or `uv run evm-bytecode-decompiler decompile ...`.
4. Inspect the reported backend and completeness. Prefer full Gigahorse; when
   the built-in fallback is used, continue with explicitly lower confidence.
5. Read contract context, then inspect important selectors incrementally with
   `context RUN_DIR --selector ...`.
6. Build a proposal containing only evidence-grounded names, labels, types,
   summaries, patterns, and uncertainties. Do not invent a function body.
7. Run `scripts/finalize.sh`, or validate, apply, and render separately.
   Revise rejected claims; never bypass validation.
8. Present the deterministic run and the separate `agent/` artifacts, including
   backend, completeness, confidence, proxy status, and limitations.

## Non-negotiable boundaries

- Canonical IR and deterministic operations win over semantic guesses.
- Preserve unknown operations, calls, storage accesses, constants, and control
  flow. Never make canonical pseudocode look nicer by changing evidence.
- Never claim exact Solidity source recovery.
- A partial built-in result is not Gigahorse; surface its lower confidence.
- Surface proxy detection instead of describing proxy runtime as implementation
  logic.
- Keep an explicitly requested historical block historical; never substitute a
  live/latest block.
- Do not request provider credentials or call an external model API.
- Do not launch a nested agent CLI from this workflow.

Read the focused references as needed:

- [workflow](references/workflow.md) for recovery and fallback behavior;
- [evidence rules](references/evidence-rules.md) before making claims;
- [annotation schema](references/annotation-schema.md) when writing JSON;
- [output contract](references/output-contract.md) before reporting results.
