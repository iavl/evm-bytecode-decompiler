# Annotation Schema

The proposal is JSON with this shape:

```json
{
  "schema_version": 1,
  "run_fingerprint": "<64 hex characters>",
  "contract": {
    "summary": "",
    "roles": {},
    "patterns": [],
    "uncertainties": [],
    "evidence_refs": []
  },
  "functions": {
    "<canonical function id>": {
      "selector": "0x...",
      "proposed_name": "",
      "name_confidence": 0.0,
      "summary": "",
      "argument_names": {},
      "argument_types": {},
      "storage_labels": {},
      "semantic_patterns": [],
      "uncertainties": [],
      "evidence_refs": []
    }
  },
  "storage_labels": {}
}
```

Unknown fields fail closed. Function keys must exist in canonical IR; selectors
must match; argument and storage keys must be recoverable IDs; labels must be
valid identifiers; confidence is between zero and one; and every cited
evidence ID must resolve in the selected function or contract.

The fingerprint must be copied from `run.json`. Keep semantic claims small:
the deterministic renderer owns the function body and side effects.
