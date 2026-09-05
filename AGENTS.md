# Repository instructions

- Read `plan.md` before changing the implementation and execute its phases in order.
- Keep deterministic bytecode evidence separate from inferred semantics.
- Preserve unknown operations and label generated Solidity-like output as reconstructed and unverified.
- Do not use `shell=True` for Gigahorse or Docker invocation.
- Do not replace an explicit historical block with `latest`.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy src` before delivery.
- Keep changes phase-scoped and preserve unrelated worktree files such as `plan.md`.
- The deterministic core must never call an LLM or require model credentials.
- Agent semantic output is an overlay and must never modify canonical IR or deterministic artifacts.
- New semantic claims require evidence references where supported; preserve unknown operations and uncertainty.
- Keep `.agents/skills/evm-bytecode-decompiler/SKILL.md` concise; put deep guidance in its references.
- Keep the built-in lifter explicitly labeled as a partial fallback, not Gigahorse.
- Changes to run fingerprinting require regression tests; annotation schema changes require schema/version tests.
- Update `how-it-works.md` when architecture or artifact boundaries change.
