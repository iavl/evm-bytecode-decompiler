from collections import defaultdict
from collections.abc import Iterable
from typing import Literal, cast

from ..errors import IRBuildError
from ..gigahorse.relations import RelationSet
from ..models.evidence import EvidenceRef, EvidenceSource
from ..models.ir import (
    BasicBlockIR,
    CallIR,
    ContractIR,
    DynamicArraySlot,
    EventIR,
    ExpressionIR,
    FixedSlot,
    FunctionIR,
    MappingSlot,
    NestedMappingSlot,
    RevertIR,
    StatementIR,
    StorageAccessIR,
    StorageLocation,
    SymbolicSlot,
)


def _int(value: str, *, label: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        try:
            return int(value)
        except ValueError as exc:
            raise IRBuildError(f"invalid {label}: {value}") from exc


def _first(
    rows: Iterable[tuple[str, ...]], index: int, default: str | None = None
) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        if len(row) > index:
            result[row[0]] = row[index]
    return result


def _evidence(
    source: EvidenceSource,
    relation: str,
    fact_id: str,
    *,
    pc: int | None = None,
    block_id: str | None = None,
    statement_id: str | None = None,
    confidence: float = 1.0,
) -> EvidenceRef:
    return EvidenceRef(
        source=source,
        relation=relation,
        fact_id=fact_id,
        pc=pc,
        block_id=block_id,
        statement_id=statement_id,
        confidence=confidence,
    )


def _expr(value: str | None) -> ExpressionIR:
    if value is None or value in {"unknown", "symbolic"}:
        return ExpressionIR(kind="unknown", value=value or "unknown")
    if value.startswith("fixed:"):
        raw = value.split(":", 1)[1]
        try:
            return ExpressionIR(kind="constant", value=int(raw, 0))
        except ValueError:
            return ExpressionIR(kind="symbolic", value=value)
    if value.startswith("mapping:"):
        return ExpressionIR(kind="keccak256", value=value)
    try:
        return ExpressionIR(kind="constant", value=int(value, 0))
    except ValueError:
        return ExpressionIR(kind="value", name=value)


def _location(slot_expr: str) -> StorageLocation:
    parts = slot_expr.split(":")
    try:
        if parts[0] == "fixed" and len(parts) == 2:
            return FixedSlot(slot=_int(parts[1], label="storage slot"))
        if parts[0] == "mapping" and len(parts) >= 3 and parts[1] != "unknown":
            base = _int(parts[1], label="mapping base slot")
            return MappingSlot(base_slot=base, key=_expr(":".join(parts[2:])))
        if parts[0] == "nested" and len(parts) >= 4:
            base = _int(parts[1], label="nested mapping base slot")
            return NestedMappingSlot(base_slot=base, keys=[_expr(part) for part in parts[2:]])
        if parts[0] == "array" and len(parts) >= 3:
            return DynamicArraySlot(
                base_slot=_int(parts[1], label="array base slot"), index=_expr(parts[2])
            )
    except (ValueError, IndexError) as exc:
        raise IRBuildError(f"invalid storage expression: {slot_expr}") from exc
    return SymbolicSlot(expression=ExpressionIR(kind="symbolic", value=slot_expr))


def _storage_accesses(
    relations: RelationSet,
    source: EvidenceSource,
    statement_pcs: dict[str, int],
    statement_blocks: dict[str, str],
) -> tuple[list[StorageAccessIR], list[StorageAccessIR]]:
    reads: list[StorageAccessIR] = []
    writes: list[StorageAccessIR] = []
    storage_relations: list[tuple[Literal["read", "write"], list[tuple[str, ...]]]] = [
        ("read", list(relations.get("StorageLoad", ()))),
        ("write", list(relations.get("StorageStore", ()))),
    ]
    for access, rows in storage_relations:
        for index, row in enumerate(rows):
            if len(row) < 3:
                raise IRBuildError(f"{access} relation requires three columns")
            statement_id, slot_expr, variable = row[:3]
            item = StorageAccessIR(
                id=f"storage_{access}_{index}_{statement_id}",
                access=access,
                location=_location(slot_expr),
                statement_id=statement_id,
                value=ExpressionIR(kind="value", name=variable) if access == "write" else None,
                result_variable=variable if access == "read" else None,
                evidence=[
                    _evidence(
                        source,
                        "StorageLoad" if access == "read" else "StorageStore",
                        f"{access}:{index}",
                        pc=statement_pcs.get(statement_id),
                        block_id=statement_blocks.get(statement_id),
                        statement_id=statement_id,
                    )
                ],
            )
            (reads if access == "read" else writes).append(item)
    return reads, writes


def _calls(
    relations: RelationSet,
    source: EvidenceSource,
    statement_pcs: dict[str, int],
    statement_blocks: dict[str, str],
) -> list[CallIR]:
    calls: list[CallIR] = []
    for index, row in enumerate(relations.get("Call", ())):
        if len(row) < 7:
            raise IRBuildError("Call relation requires seven columns")
        statement_id, call_type, target, value, input_expr, output, result = row[:7]
        calls.append(
            CallIR(
                id=f"call_{index}_{statement_id}",
                call_type=cast(
                    Literal[
                        "call",
                        "staticcall",
                        "delegatecall",
                        "callcode",
                        "create",
                        "create2",
                        "selfdestruct",
                    ],
                    call_type,
                ),
                statement_id=statement_id,
                target=_expr(target),
                value=_expr(value),
                input=_expr(input_expr),
                output=_expr(output),
                result_variable=result if result != "unknown" else None,
                evidence=[
                    _evidence(
                        source,
                        "Call",
                        f"call:{index}",
                        pc=statement_pcs.get(statement_id),
                        block_id=statement_blocks.get(statement_id),
                        statement_id=statement_id,
                    )
                ],
            )
        )
    return calls


def _events(
    relations: RelationSet,
    source: EvidenceSource,
    statement_pcs: dict[str, int],
    statement_blocks: dict[str, str],
) -> list[EventIR]:
    events: list[EventIR] = []
    for index, row in enumerate(relations.get("Event", ())):
        if len(row) < 4:
            raise IRBuildError("Event relation requires four columns")
        event_id, statement_id, topic_count, data = row[:4]
        count = _int(topic_count, label="event topic count")
        events.append(
            EventIR(
                id=event_id,
                statement_id=statement_id,
                topics=[
                    ExpressionIR(kind="unknown", name=f"topic{topic}")
                    for topic in range(count)
                ],
                data=_expr(data),
                evidence=[
                    _evidence(
                        source,
                        "Event",
                        f"event:{index}",
                        pc=statement_pcs.get(statement_id),
                        block_id=statement_blocks.get(statement_id),
                        statement_id=statement_id,
                    )
                ],
            )
        )
    return events


def _reverts(
    relations: RelationSet,
    source: EvidenceSource,
    statement_pcs: dict[str, int],
    statement_blocks: dict[str, str],
) -> list[RevertIR]:
    reverts: list[RevertIR] = []
    for index, row in enumerate(relations.get("Revert", ())):
        if len(row) < 3:
            raise IRBuildError("Revert relation requires three columns")
        revert_id, statement_id, kind = row[:3]
        reverts.append(
            RevertIR(
                id=revert_id,
                statement_id=statement_id,
                kind=cast(Literal["revert", "invalid"], kind),
                evidence=[
                    _evidence(
                        source,
                        "Revert",
                        f"revert:{index}",
                        pc=statement_pcs.get(statement_id),
                        block_id=statement_blocks.get(statement_id),
                        statement_id=statement_id,
                    )
                ],
            )
        )
    return reverts


def build_contract_ir(
    relations: RelationSet,
    *,
    bytecode_sha256: str,
    bytecode_size: int,
    metadata: dict[str, object] | None = None,
    evidence_source: EvidenceSource = EvidenceSource.GIGAHORSE,
) -> ContractIR:
    block_pcs = {
        row[0]: _int(row[1], label="block pc")
        for row in relations.get("BlockPC", ())
        if len(row) >= 2
    }
    block_ids = {row[0] for row in relations.get("Block", ()) if row}
    block_ids.update(block_pcs)
    block_ids.update(row[0] for row in relations.get("BlockSuccessor", ()) if row)
    block_ids.update(row[1] for row in relations.get("BlockSuccessor", ()) if len(row) >= 2)
    block_ids.update(row[1] for row in relations.get("FunctionEntry", ()) if len(row) >= 2)
    block_ids.update(row[1] for row in relations.get("FunctionBlock", ()) if len(row) >= 2)
    if not block_ids:
        raise IRBuildError("relations contain no basic blocks")
    for block_id in block_ids:
        if block_id not in block_pcs:
            try:
                block_pcs[block_id] = int(block_id.split("_")[-1], 16)
            except ValueError:
                block_pcs[block_id] = 0

    statement_blocks = _first(relations.get("StatementBlock", ()), 1)
    statement_pcs = {
        row[0]: _int(row[1], label="statement pc")
        for row in relations.get("StatementPC", ())
        if len(row) >= 2
    }
    statement_opcodes = _first(relations.get("StatementOpcode", ()), 1)
    statement_operands = {
        row[0]: _int(row[1], label="statement operand")
        for row in relations.get("StatementOperand", ())
        if len(row) >= 2
    }
    defines: dict[str, list[str]] = defaultdict(list)
    uses: dict[str, list[str]] = defaultdict(list)
    for statement, variable in relations.get("Defines", ()):
        defines[statement].append(variable)
    for statement, variable in relations.get("Uses", ()):
        uses[statement].append(variable)
    statement_ids = {row[0] for row in relations.get("Statement", ()) if row}
    statement_ids.update(statement_blocks)
    statement_ids.update(statement_opcodes)
    if not statement_ids:
        raise IRBuildError("relations contain no statements")
    statements_by_block: dict[str, list[StatementIR]] = defaultdict(list)
    for statement_id in sorted(statement_ids, key=lambda item: (statement_pcs.get(item, 0), item)):
        statement_block_id = statement_blocks.get(statement_id)
        if statement_block_id is None:
            raise IRBuildError(f"statement {statement_id} has no block")
        pc = statement_pcs.get(statement_id, 0)
        statements_by_block[statement_block_id].append(
            StatementIR(
                id=statement_id,
                block_id=statement_block_id,
                pc=pc,
                opcode=statement_opcodes.get(statement_id, "UNKNOWN"),
                operand=statement_operands.get(statement_id),
                uses=uses.get(statement_id, []),
                defines=defines.get(statement_id, []),
                expression=(
                    ExpressionIR(kind="constant", value=statement_operands[statement_id])
                    if statement_id in statement_operands
                    else None
                ),
                evidence=[
                    _evidence(
                        evidence_source,
                        "Statement",
                        statement_id,
                        pc=pc,
                        block_id=statement_block_id,
                        statement_id=statement_id,
                    )
                ],
            )
        )

    successors: dict[str, list[str]] = defaultdict(list)
    for row in relations.get("BlockSuccessor", ()):
        if len(row) >= 2:
            successors[row[0]].append(row[1])
    predecessors: dict[str, list[str]] = defaultdict(list)
    for source, targets in successors.items():
        for target in targets:
            predecessors[target].append(source)

    reads, writes = _storage_accesses(relations, evidence_source, statement_pcs, statement_blocks)
    calls = _calls(relations, evidence_source, statement_pcs, statement_blocks)
    events = _events(relations, evidence_source, statement_pcs, statement_blocks)
    reverts = _reverts(relations, evidence_source, statement_pcs, statement_blocks)
    function_rows = relations.get("PublicFunction", ())
    entries = {row[0]: row[1] for row in relations.get("FunctionEntry", ()) if len(row) >= 2}
    memberships: dict[str, set[str]] = defaultdict(set)
    for row in relations.get("FunctionBlock", ()):
        if len(row) >= 2:
            memberships[row[0]].add(row[1])
    functions: list[FunctionIR] = []
    known_functions = [row[1] for row in function_rows if len(row) >= 2]
    known_functions.extend(function for function in entries if function not in known_functions)
    if not known_functions:
        known_functions = ["fallback"]
        entries["fallback"] = min(block_ids, key=lambda item: block_pcs[item])
        memberships["fallback"].update(block_ids)
    for function_id in known_functions:
        entry = entries.get(function_id)
        if entry is None:
            raise IRBuildError(f"function {function_id} has no entry block")
        member_ids = memberships.get(function_id) or {entry}
        member_ids.add(entry)
        member_ids = {item for item in member_ids if item in block_ids}
        if not member_ids:
            raise IRBuildError(f"function {function_id} has no known blocks")
        selector = next(
            (row[0] for row in function_rows if len(row) >= 2 and row[1] == function_id),
            None,
        )
        function_blocks = [
            BasicBlockIR(
                id=block_id,
                pc=block_pcs[block_id],
                function_id=function_id,
                predecessor_ids=sorted(
                    item for item in predecessors.get(block_id, []) if item in member_ids
                ),
                successor_ids=sorted(
                    set(item for item in successors.get(block_id, []) if item in member_ids)
                ),
                statements=statements_by_block.get(block_id, []),
                evidence=[
                    _evidence(
                        evidence_source,
                        "FunctionBlock",
                        f"{function_id}:{block_id}",
                        pc=block_pcs[block_id],
                        block_id=block_id,
                    )
                ],
            )
            for block_id in sorted(member_ids, key=lambda item: block_pcs[item])
        ]
        function_statement_ids = {
            statement.id for block in function_blocks for statement in block.statements
        }
        function_call_ids = {
            call.statement_id for call in calls if call.statement_id in function_statement_ids
        }
        function_calls = [call for call in calls if call.statement_id in function_call_ids]
        function_storage = {
            statement.id for block in function_blocks for statement in block.statements
        }
        function_reads = [item for item in reads if item.statement_id in function_storage]
        function_writes = [item for item in writes if item.statement_id in function_storage]
        function_events = [item for item in events if item.statement_id in function_storage]
        function_reverts = [item for item in reverts if item.statement_id in function_storage]
        functions.append(
            FunctionIR(
                id=function_id,
                selector=selector,
                entry_block=entry,
                blocks=function_blocks,
                external_calls=function_calls,
                storage_reads=function_reads,
                storage_writes=function_writes,
                events=function_events,
                reverts=function_reverts,
                evidence=[
                    _evidence(
                        evidence_source,
                        "FunctionEntry",
                        function_id,
                        pc=block_pcs[entry],
                        block_id=entry,
                    )
                ],
            )
        )
    return ContractIR(
        bytecode_sha256=bytecode_sha256,
        bytecode_size=bytecode_size,
        metadata=metadata or {},
        functions=functions,
        storage=reads + writes,
        external_calls=calls,
        events=events,
        reverts=reverts,
    )
