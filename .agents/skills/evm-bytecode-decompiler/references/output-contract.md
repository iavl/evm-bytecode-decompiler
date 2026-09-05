# Output Contract

Deterministic artifacts live under `RUN_DIR/input`, `gigahorse`, `ir`, and
`output`. The canonical Solidity-like file is `output/decompiled.sol`; it is
always reconstructed, unverified pseudocode.

Validated semantic artifacts live under `RUN_DIR/agent`:

```text
proposal.json
annotations.json
manifest.json
decompiled.annotated.sol
report.md
```

`agent/manifest.json` binds the annotation hash to the deterministic run
fingerprint. Applying or rendering an overlay must leave canonical hashes
unchanged.

Final responses should identify the run directory, backend and completeness,
whether a proxy was detected, the deterministic artifacts, the optional agent
artifacts, and the main uncertainties. Say explicitly that pseudocode is not
recovered source and lower confidence for partial or ambiguous evidence.
