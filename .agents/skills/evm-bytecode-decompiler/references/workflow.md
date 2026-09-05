# Workflow

The repository-local workflow has two immutable layers:

1. `decompile` or `analyze` creates a deterministic run.
2. `context` exposes bounded canonical evidence for semantic reasoning.
3. The agent writes a run-bound proposal.
4. `agent validate` rejects unknown IDs, mismatched selectors, bad evidence,
   unsupported labels, and schema or fingerprint errors.
5. `agent apply` writes only `RUN_DIR/agent/`.
6. `agent render` produces annotated pseudocode and a semantic report.

Use contract context first. For large contracts, select functions one at a time
with `context RUN_DIR --selector SELECTOR`; omitted functions or blocks are
reported instead of silently discarded.

`backend=local` or `backend=docker` must produce complete relation workspaces.
`backend=builtin` is a limited deterministic lifter and reports `partial`.
If `auto` falls back to it, keep conclusions generic and state the limitation.

If validation fails, remove or revise only the unsupported claim. Never edit
`ir/contract.json`, `run.json`, or deterministic files to make a proposal pass.
For a historical address analysis, verify the requested block in the run input
metadata and report it in the final result.
