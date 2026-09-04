# Benchmark fixtures

The manifest contains 20 source fixtures. `benchmark run` compiles each source
with the selected `solc` executable, then passes only the resulting runtime
bytecode to the decompiler. Source is evaluation-only and is never included in
the decompilation input.

```bash
uv run evm-bytecode-decompiler benchmark run --output-dir runs/benchmark
uv run evm-bytecode-decompiler benchmark report --output-dir runs/benchmark
```

Fixtures with historical Solidity pragmas require a compiler matching that
pragma. Use `--solc` to point at a version-managed compiler wrapper.
