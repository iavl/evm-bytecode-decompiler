import json
from collections.abc import Iterable, Mapping

from ..inference.abi import InferredABI, InferredFunction
from ..inference.storage import StorageLayoutEntry
from ..models.annotations import ContractAnnotation, FunctionAnnotation
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
from .names import safe_identifier


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


def _label_for(access: StorageAccessIR, labels: Mapping[str, str] | None) -> str | None:
    if not labels:
        return None
    return labels.get(access.id)


def _location_text(access: StorageAccessIR | None, labels: Mapping[str, str] | None = None) -> str:
    if access is None:
        return "storage[unknown]"
    label = _label_for(access, labels)
    location = access.location
    if isinstance(location, FixedSlot):
        return label or f"storage_{location.slot}"
    if isinstance(location, MappingSlot):
        name = label or f"mapping_{location.base_slot}"
        return f"{name}[{expression_text(location.key)}]"
    if isinstance(location, NestedMappingSlot):
        keys = "][".join(expression_text(key) for key in location.keys)
        return f"{label or f'mapping_{location.base_slot}_nested'}[{keys}]"
    if isinstance(location, DynamicArraySlot):
        return f"{label or f'array_{location.base_slot}'}[{expression_text(location.index)}]"
    if isinstance(location, SymbolicSlot):
        return label or f"storage[{expression_text(location.expression)}]"
    return label or "storage[unknown]"


def _statement_text(
    statement: StatementIR,
    function: FunctionIR,
    storage_labels: Mapping[str, str] | None = None,
) -> str:
    pc_text = f"{statement.pc:04x}" if statement.pc is not None else "unknown"
    variable = statement.defines[0] if statement.defines else f"v_{pc_text}"
    if statement.truncated:
        return f"// pc {pc_text}: {statement.opcode} (truncated operand, unresolved)"
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
        return f"{variable} = {_location_text(access, storage_labels)};"
    if statement.opcode == "SSTORE":
        access = next(
            (item for item in function.storage_writes if item.statement_id == statement.id),
            None,
        )
        value = expression_text(access.value) if access and access.value else "<unknown>"
        return f"{_location_text(access, storage_labels)} = {value};"
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
        block = next(
            (item for item in function.blocks if statement.id in {s.id for s in item.statements}),
            None,
        )
        if block and block.true_successor_id and block.false_successor_id:
            return (
                "if (<unknown condition>) { "
                f"goto {block.true_successor_id}; }} else {{ "
                f"goto {block.false_successor_id}; }}"
            )
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
    return (
        f"// pc {statement.pc if statement.pc is not None else '<unknown>'}: "
        f"{statement.opcode} (raw deterministic operation)"
    )


def _call_text(call: CallIR | None, variable: str) -> str:
    if call is None:
        return "// unresolved low-level call"
    if call.call_type == "selfdestruct":
        return f"selfdestruct({expression_text(call.beneficiary)});"
    if call.call_type in {"create", "create2"}:
        return f"address {variable} = {call.call_type}({expression_text(call.input)});"
    target = expression_text(call.target)
    return f"bool {variable} = {target}.{call.call_type}({expression_text(call.input)});"


def _function_info(abi: InferredABI, function: FunctionIR) -> InferredFunction | None:
    return next((item for item in abi.functions if item.function_id == function.id), None)


def _function_name(
    function: FunctionIR,
    info: InferredFunction | None,
    annotation: FunctionAnnotation | None,
) -> str:
    fallback = (
        info.name if info else (f"func_{function.selector}" if function.selector else "fallback")
    )
    return safe_identifier(annotation.proposed_name, fallback) if annotation else fallback


def _arguments(
    function: FunctionIR,
    info: InferredFunction | None,
    annotation: FunctionAnnotation | None,
) -> str:
    names = info.arguments if info else [item.id for item in function.arguments]
    values: list[str] = []
    for index, default_name in enumerate(names):
        value_id = function.arguments[index].id if index < len(function.arguments) else default_name
        name = default_name
        type_name = info.argument_types.get(default_name, "uint256") if info else "uint256"
        if annotation:
            name = annotation.argument_names.get(
                value_id, annotation.argument_names.get(default_name, name)
            )
            type_name = annotation.argument_types.get(
                value_id,
                annotation.argument_types.get(default_name, type_name),
            )
        values.append(f"{type_name} {safe_identifier(name, f'arg{index}')}")
    return ", ".join(values)


def _labels(
    annotation: FunctionAnnotation | None,
    storage_labels: Mapping[str, str] | None,
) -> dict[str, str]:
    result = dict(storage_labels or {})
    if annotation:
        result.update(annotation.storage_labels)
    return result


def render_contract(
    contract: ContractIR,
    abi: InferredABI,
    storage: Iterable[StorageLayoutEntry],
    *,
    annotations: Mapping[str, FunctionAnnotation] | None = None,
    contract_annotation: ContractAnnotation | None = None,
    storage_labels: Mapping[str, str] | None = None,
    annotated: bool = False,
) -> str:
    annotations = annotations or {}
    labels = dict(storage_labels or {})
    lines = [
        "// EVM Bytecode Decompiler semantic decompilation",
        "// RECONSTRUCTED / UNVERIFIED: this is pseudocode, not verified source.",
        "",
        "contract DecompiledContract {",
    ]
    if annotated and contract_annotation:
        if contract_annotation.summary:
            lines.append(f"    // semantic summary (advisory): {contract_annotation.summary}")
        for role, value in contract_annotation.roles.items():
            lines.append(f"    // inferred role (advisory): {role} = {value}")
        for uncertainty in contract_annotation.uncertainties:
            lines.append(f"    // uncertainty: {uncertainty}")
        if (
            contract_annotation.summary
            or contract_annotation.roles
            or contract_annotation.uncertainties
        ):
            lines.append("")
    storage_items = list(storage)
    for entry in storage_items:
        name = safe_identifier(labels.get(entry.id, entry.name), entry.name)
        suffix = f" // {entry.origin}, confidence {entry.confidence:.2f}"
        type_name = "mapping(bytes32 => uint256)" if "mapping" in entry.kind else "uint256"
        lines.append(f"    {type_name} internal {name};{suffix}")
    if storage_items:
        lines.append("")
    for function in contract.functions:
        info = _function_info(abi, function)
        annotation = annotations.get(function.id) if annotated else None
        function_labels = _labels(annotation, labels)
        name = _function_name(function, info, annotation)
        lines.append(f"    // selector: {function.selector or '<fallback>'}")
        if info and info.candidates:
            for candidate in info.candidates:
                lines.append(
                    f"    // signature candidate: {candidate.signature} ({candidate.source})"
                )
        if annotation and annotation.summary:
            lines.append(f"    // semantic summary (advisory): {annotation.summary}")
        if annotation:
            for pattern in annotation.semantic_patterns:
                lines.append(f"    // inferred pattern (advisory): {pattern}")
            for uncertainty in annotation.uncertainties:
                lines.append(f"    // uncertainty: {uncertainty}")
        lines.append(f"    function {name}({_arguments(function, info, annotation)}) external {{")
        for block in function.blocks:
            lines.append(
                f"        // basic block {block.id} @ pc "
                f"{block.pc if block.pc is not None else '<unknown>'}"
            )
            for statement in block.statements:
                rendered = _statement_text(statement, function, function_labels)
                if annotated:
                    rendered += f" // evidence: {statement.id}"
                lines.append(f"        {rendered}")
        lines.append("    }")
        lines.append("")
    unassigned = set(contract.unassigned_block_ids)
    if unassigned:
        lines.extend(
            [
                "    // Unassigned bytecode blocks (no function ownership was proven).",
                "    function __unassigned_code() internal {",
            ]
        )
        for block in contract.blocks:
            if block.id not in unassigned:
                continue
            lines.append(
                f"        // basic block {block.id} @ pc "
                f"{block.pc if block.pc is not None else '<unknown>'}"
            )
            statement_ids = {statement.id for statement in block.statements}
            view_block = block.model_copy(
                update={
                    "predecessor_ids": [],
                    "successor_ids": [],
                    "true_successor_id": None,
                    "false_successor_id": None,
                }
            )
            view_function = FunctionIR(
                id="__unassigned_code",
                selector=None,
                entry_block=block.id,
                blocks=[view_block],
                storage_reads=[
                    item
                    for item in contract.storage
                    if item.access == "read" and item.statement_id in statement_ids
                ],
                storage_writes=[
                    item
                    for item in contract.storage
                    if item.access == "write" and item.statement_id in statement_ids
                ],
                external_calls=[
                    item for item in contract.external_calls if item.statement_id in statement_ids
                ],
                events=[item for item in contract.events if item.statement_id in statement_ids],
                reverts=[item for item in contract.reverts if item.statement_id in statement_ids],
                evidence=block.evidence,
            )
            for statement in block.statements:
                rendered = _statement_text(statement, view_function, labels)
                if annotated:
                    rendered += f" // evidence: {statement.id}"
                lines.append(f"        {rendered}")
        lines.extend(["    }", ""])
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_storage_layout(storage: Iterable[StorageLayoutEntry]) -> str:
    return (
        json.dumps({"storage": [item.model_dump(mode="json") for item in storage]}, indent=2) + "\n"
    )


def render_evidence_map(
    contract: ContractIR,
    abi: InferredABI,
    *,
    annotations: Mapping[str, FunctionAnnotation] | None = None,
) -> str:
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
        item: dict[str, object] = {
            "selector": function.selector,
            "name": info.name if info else function.id,
            "statements": statements,
        }
        if annotations and function.id in annotations:
            item["semantic_annotation"] = annotations[function.id].model_dump(mode="json")
        functions[function.id] = item
    unassigned: dict[str, object] = {}
    for block in contract.blocks:
        if block.id not in contract.unassigned_block_ids:
            continue
        unassigned[block.id] = {
            "pc": block.pc,
            "statements": {
                statement.id: {
                    "pc": statement.pc,
                    "opcode": statement.opcode,
                    "evidence": [item.model_dump(mode="json") for item in statement.evidence],
                }
                for statement in block.statements
            },
        }
    return json.dumps({"functions": functions, "unassigned_blocks": unassigned}, indent=2) + "\n"
