# Repository instructions

- Read `plan.md` before changing the implementation and execute its phases in order.
- Keep deterministic bytecode evidence separate from inferred semantics.
- Preserve unknown operations and label generated Solidity-like output as reconstructed and unverified.
- Do not use `shell=True` for Gigahorse or Docker invocation.
- Do not replace an explicit historical block with `latest`.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy src` before delivery.
- Keep changes phase-scoped and preserve unrelated worktree files such as `plan.md`.
