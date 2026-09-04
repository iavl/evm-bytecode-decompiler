# Gigahorse relation adapter

The Python pipeline consumes only the normalized relations below. Each
relation is emitted as a UTF-8 tab-separated file under `gigahorse/facts/`.
Rows are sorted before they are persisted, making the adapter output stable.

| Relation | Columns | Meaning |
| --- | --- | --- |
| `PublicFunction` | selector, function | Dispatcher-derived public selector and canonical function id. |
| `FunctionEntry` | function, block | Entry block for a function. |
| `FunctionBlock` | function, block | Function membership. |
| `Block` | block | Known basic block. |
| `BlockPC` | block, pc | First program counter for a block. |
| `BlockSuccessor` | from, to | CFG edge. |
| `ConditionalSuccessor` | from, true, false | Conditional CFG edge pair. |
| `Statement` | statement | Known statement id. |
| `StatementBlock` | statement, block | Statement membership. |
| `StatementPC` | statement, pc | Statement program counter. |
| `StatementOpcode` | statement, opcode | Normalized opcode name. |
| `StatementOperand` | statement, operand | Exact PUSH operand when present. |
| `Defines` / `Uses` | statement, variable | Def-use facts. |
| `DataFlow` | source, destination | Variable data-flow edge. |
| `StorageLoad` | statement, slot expression, result | Storage read. |
| `StorageStore` | statement, slot expression, value | Storage write. |
| `Call` | statement, call type, target, value, input, output, result | Low-level call/create fact. |
| `Event` | event, statement, topic count, data | LOG fact. |
| `EventTopic` | event, topic index, value | Deterministic/constant LOG topic when available. |
| `Revert` | revert, statement, kind | REVERT or INVALID fact. |
| `Constant` | statement, value | Exact numeric literal. |

`CALL`, `STATICCALL`, `DELEGATECALL`, `CALLCODE`, `CREATE`, `CREATE2`, and
`SELFDESTRUCT` remain distinct in `Call.callType`. The built-in fallback emits
the same file shape but is explicitly reported as a limited bytecode lifter,
not as Gigahorse output.
