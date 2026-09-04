import json
from collections.abc import Iterable

from ..inference.abi import InferredABI, InferredFunction
from ..inference.storage import StorageLayoutEntry
from ..models.ir import (
    CallIR,
    ContractIR,
    DynamicArraySlot,
    ExpressionIR,
    FixedSlot,
    FunctionIR,
    MappingSlot,
    NestedMappingSlot,
    StatementIR,
    StorageAccessIR,
    SymbolicSlot,
)


def expression_text(expression: ExpressionIR | None) -> str:
    if expression is None:
        return "unknown"
    if expression.kind == "constant":
        return hex(expression.value) if isinstance(expression.value, int) else str(expression.value)
    if expression.kind == "value":
        return expression.name or str(expression.value or "unknown")
    if expression.kind == "unknown":
        return f"<unknown:{expression.value or expression.name or 'expression'}>"
    if expression.kind == "keccak256":
        return f"keccak256({expression.value or 'unknown'})"
    if expression.args:
        return f"{expression.kind}({', '.join(expression_text(arg) for arg in expression.args)})"
    return str(expression.value or expression.name or expression.kind)


def _location_text(access: StorageAccessIR) -> str:
    location = access.location
    if isinstance(location, FixedSlot):
        return f"storage_{location.slot}"
    if isinstance(location, MappingSlot):
        return f"mapping_{location.base_slot}[{expression_text(location.key)}]"
    if isinstance(location, NestedMappingSlot):
        keys = "][".join(expression_text(key) for key in location.keys)
        return f"mapping_{location.base_slot}[{keys}]"
    if isinstance(location, DynamicArraySlot):
        return f"array_{location.base_slot}[{expression_text(location.index)}]"
    if isinstance(location, SymbolicSlot):
        return f"storage[{expression_text(location.expression)}]"
    return "storage[unknown]"


def _statement_text(statement: StatementIR, function: FunctionIR) -> str:
    variable = statement.defines[0] if statement.defines else f"v_{statement.pc:04x}"
    if statement.opcode.startswith("PUSH"):
        literal = hex(statement.operand or 0)
        return f"uint256 {variable} = {literal};"
    if statement.opcode == "CALLDATALOAD":
        return f"uint256 {variable} = msg.data[<unknown offset>];"
    if statement.opcode == "SLOAD":
        access = next(
            (item for item in function.storage_reads if item.statement_id == statement.id),
            None,
        )
        return f"{variable} = {_location_text(access) if access else 'storage[unknown]'};"
    if statement.opcode == "SSTORE":
        access = next(
            (item for item in function.storage_writes if item.statement_id == statement.id),
            None,
        )
        value = statement.uses[-1] if statement.uses else "<unknown>"
        return f"{_location_text(access) if access else 'storage[unknown]'} = {value};"
    if statement.opcode in {
        "CALL",
        "STATICCALL",
        "DELEGATECALL",
        "CALLCODE",
        "CREATE",
        "CREATE2",
        "SELFDESTRUCT",
    }:
        call = next(
            (item for item in function.external_calls if item.statement_id == statement.id),
            None,
        )
        return _call_text(call, variable)
    if statement.opcode.startswith("LOG"):
        event = next((item for item in function.events if item.statement_id == statement.id), None)
        count = len(event.topics) if event else int(statement.opcode[3:] or 0)
        return f"emit Log{count}(<unknown data>);"
    if statement.opcode == "JUMPI":
        return "if (<unknown condition>) { goto <unknown destination>; }"
    if statement.opcode == "JUMP":
        return "goto <unknown destination>;"
    if statement.opcode == "RETURN":
        return "return <unknown>;"
    if statement.opcode == "REVERT":
        return "revert();"
    if statement.opcode == "INVALID":
        return "invalid();"
    if statement.opcode == "STOP":
        return "return;"
    return f"// pc {statement.pc}: {statement.opcode} (raw deterministic operation)"


def _call_text(call: CallIR | None, variable: str) -> str:
    if call is None:
        return "// unresolved low-level call"
    if call.call_type == "selfdestruct":
        return "selfdestruct(<unknown beneficiary>);"
    if call.call_type in {"create", "create2"}:
        return f"address {variable} = {call.call_type}(<unknown init code>);"
    target = expression_text(call.target)
    return f"bool {variable} = {target}.{call.call_type}(<unknown calldata>);"


def _function_info(abi: InferredABI, function: FunctionIR) -> InferredFunction | None:
    return next((item for item in abi.functions if item.function_id == function.id), None)


def render_contract(
    contract: ContractIR, abi: InferredABI, storage: Iterable[StorageLayoutEntry]
) -> str:
    lines = [
        "// EVM Bytecode Decompiler semantic decompilation",
        "// RECONSTRUCTED / UNVERIFIED: this is pseudocode, not verified source.",
        "",
        "contract DecompiledContract {",
    ]
    for entry in storage:
        suffix = f" // {entry.origin}, confidence {entry.confidence:.2f}"
        type_name = "mapping(bytes32 => uint256)" if "mapping" in entry.kind else "uint256"
        lines.append(f"    {type_name} internal {entry.name};{suffix}")
    if storage:
        lines.append("")
    for function in contract.functions:
        info = _function_info(abi, function)
        name = (
            info.name
            if info
            else (f"func_{function.selector}" if function.selector else "fallback")
        )
        args = ", ".join(f"uint256 {arg}" for arg in (info.arguments if info else []))
        lines.append(f"    // selector: {function.selector or '<fallback>'}")
        if info and info.candidates:
            for candidate in info.candidates:
                lines.append(
                    f"    // signature candidate: {candidate.signature} ({candidate.source})"
                )
        lines.append(f"    function {name}({args}) external {{")
        for block in function.blocks:
            lines.append(f"        // basic block {block.id} @ pc {block.pc}")
            for statement in block.statements:
                lines.append(f"        {_statement_text(statement, function)}")
        lines.append("    }")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_storage_layout(storage: Iterable[StorageLayoutEntry]) -> str:
    return (
        json.dumps({"storage": [item.model_dump(mode="json") for item in storage]}, indent=2)
        + "\n"
    )


def render_evidence_map(contract: ContractIR, abi: InferredABI) -> str:
    functions: dict[str, object] = {}
    for function in contract.functions:
        info = _function_info(abi, function)
        statements: dict[str, object] = {}
        for block in function.blocks:
            for statement in block.statements:
                statements[statement.id] = {
                    "pc": statement.pc,
                    "opcode": statement.opcode,
                    "evidence": [item.model_dump(mode="json") for item in statement.evidence],
                }
        functions[function.id] = {
            "selector": function.selector,
            "name": info.name if info else function.id,
            "statements": statements,
        }
    return json.dumps({"functions": functions}, indent=2) + "\n"
