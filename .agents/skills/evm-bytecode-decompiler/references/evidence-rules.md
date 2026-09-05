# Evidence Rules

Canonical bytecode-derived evidence includes:

- functions, selectors, blocks, edges, statements, constants, and unknown ops;
- storage reads and writes with their canonical locations;
- call types and call facts;
- events, reverts, calldata usage, return values, and evidence references;
- deterministic ABI/storage inference and proxy detection.

Agent annotations are advisory. A name, type, role, pattern, storage label, or
summary may explain evidence but cannot add or remove a canonical fact. Every
semantic claim should cite IDs from the relevant function or contract context.
If a claim cannot be tied to evidence, omit it or place it in `uncertainties`.

Do not treat a selector signature candidate as proof of the original source.
Do not turn an unknown operation into a guessed operation. Do not infer storage
values, transaction history, source-level modifiers, or vulnerability status
unless the user separately supplies evidence and the output clearly marks it.
