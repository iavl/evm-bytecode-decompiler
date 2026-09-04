Synthesize one Solidity-like pseudocode function from the supplied canonical
IR and validated semantic annotations. Preserve every material storage write,
external call type, event, revert, branch, return, and exact constant. Do not
invent facts. Keep unresolved constructs visible as unknown nodes. Return only
the requested structured AST; this is not verified source code.
