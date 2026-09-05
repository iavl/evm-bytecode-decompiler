import re

from ..ai.schemas import PseudoFunction, PseudoStatement, ReviewResult
from ..models.ir import FunctionIR

NUMBER_RE = re.compile(r"(?<![A-Za-z_])(?:0x[0-9a-fA-F]+|[0-9]+)(?![A-Za-z0-9_])")
CALL_TYPES = {
    "call",
    "staticcall",
    "delegatecall",
    "callcode",
    "create",
    "create2",
    "selfdestruct",
}


def _flatten(statements: list[PseudoStatement]) -> list[PseudoStatement]:
    return [statement for item in statements for statement in [item, *_flatten(item.body)]]


def _evidence_ids(function: FunctionIR) -> set[str]:
    known = {statement.id for block in function.blocks for statement in block.statements}
    known.update(item.id for item in function.storage_reads + function.storage_writes)
    known.update(item.id for item in function.external_calls + function.events + function.reverts)
    known.update(
        reference.fact_id
        for item in (
            function.storage_reads
            + function.storage_writes
            + function.external_calls
            + function.events
            + function.reverts
        )
        for reference in item.evidence
        if reference.fact_id
    )
    known.update(
        item.fact_id
        for block in function.blocks
        for statement in block.statements
        for item in statement.evidence
        if item.fact_id
    )
    return known


def _numeric_literals(statement: PseudoStatement) -> list[int]:
    values: list[int] = []
    for text in (statement.target, statement.value, statement.condition):
        if text:
            values.extend(
                int(token, 16) if token.lower().startswith("0x") else int(token)
                for token in NUMBER_RE.findall(text)
            )
    return values


def validate_pseudo_function(function: FunctionIR, pseudo: PseudoFunction) -> ReviewResult:
    if pseudo.function_id != function.id:
        return ReviewResult(
            unsupported_semantic_claims=[f"wrong function id: {pseudo.function_id}"],
            severity="fail",
        )
    if pseudo.selector is not None and pseudo.selector != function.selector:
        return ReviewResult(
            unsupported_semantic_claims=[f"wrong selector: {pseudo.selector}"], severity="fail"
        )
    statements = _flatten(pseudo.body)
    known_evidence = _evidence_ids(function)
    referenced = {ref for statement in statements for ref in statement.evidence_refs}
    unknown_evidence = sorted(referenced - known_evidence)
    if unknown_evidence:
        return ReviewResult(
            unsupported_semantic_claims=[f"unknown evidence: {item}" for item in unknown_evidence],
            severity="fail",
        )
    by_id: dict[str, tuple[str, str | None]] = {}
    for access in function.storage_reads:
        by_id[access.id] = ("storage_read", None)
        by_id[access.statement_id] = ("storage_read", None)
    for access in function.storage_writes:
        by_id[access.id] = ("storage_write", None)
        by_id[access.statement_id] = ("storage_write", None)
    for call in function.external_calls:
        by_id[call.id] = (call.call_type, call.call_type)
        by_id[call.statement_id] = (call.call_type, call.call_type)
    for event in function.events:
        by_id[event.id] = ("event", None)
        by_id[event.statement_id] = ("event", None)
    for revert in function.reverts:
        by_id[revert.id] = ("revert", None)
        by_id[revert.statement_id] = ("revert", None)
    semantic_mismatches: list[str] = []
    evidence_pcs = {
        statement.id: statement.pc
        for block in function.blocks
        for statement in block.statements
        if statement.pc is not None
    }
    statement_pc_by_id = evidence_pcs.copy()
    for item in (
        function.storage_reads
        + function.storage_writes
        + function.external_calls
        + function.events
        + function.reverts
    ):
        pc = statement_pc_by_id.get(item.statement_id)
        if pc is not None:
            evidence_pcs[item.id] = pc
    last_pc = -1
    for statement in statements:
        if statement.kind != "unknown" and not statement.evidence_refs:
            semantic_mismatches.append(f"{statement.kind} has no evidence")
            continue
        pcs = [evidence_pcs[ref] for ref in statement.evidence_refs if ref in evidence_pcs]
        if pcs and min(pcs) < last_pc:
            semantic_mismatches.append("evidence references are out of execution order")
        if pcs:
            last_pc = max(pcs)
        expected = {by_id[ref] for ref in statement.evidence_refs if ref in by_id}
        if (
            statement.kind
            in {
                "storage_read",
                "storage_write",
                "call",
                "delegatecall",
                "staticcall",
                "selfdestruct",
                "create",
                "create2",
                "event",
                "revert",
                "require",
            }
            and not expected
        ):
            semantic_mismatches.append(f"{statement.kind} has no matching deterministic fact")
        if not expected:
            continue
        for expected_kind, expected_call_type in expected:
            if expected_kind == "event" and statement.kind != "event":
                semantic_mismatches.append(f"event evidence used by {statement.kind}")
            elif expected_kind == "revert" and statement.kind not in {"revert", "require"}:
                semantic_mismatches.append(f"revert evidence used by {statement.kind}")
            elif expected_kind.startswith("storage_") and statement.kind != expected_kind:
                semantic_mismatches.append(f"{expected_kind} evidence used by {statement.kind}")
            elif expected_call_type and (
                statement.kind != expected_call_type or statement.call_type != expected_call_type
            ):
                semantic_mismatches.append(
                    f"{expected_call_type} evidence used by {statement.kind}"
                )
    known_constants = {
        statement.operand
        for block in function.blocks
        for statement in block.statements
        if statement.operand is not None
    }
    incorrect_constants = [
        str(value)
        for statement in statements
        for value in _numeric_literals(statement)
        if value not in known_constants
    ]
    missing_writes = [
        item.id
        for item in function.storage_writes
        if not any(
            item.id in statement.evidence_refs or item.statement_id in statement.evidence_refs
            for statement in statements
        )
    ]
    missing_calls = [
        item.id
        for item in function.external_calls
        if not any(
            item.id in statement.evidence_refs or item.statement_id in statement.evidence_refs
            for statement in statements
        )
    ]
    missing_events = [
        item.id
        for item in function.events
        if not any(
            item.id in statement.evidence_refs or item.statement_id in statement.evidence_refs
            for statement in statements
        )
    ]
    missing_reverts = [
        item.id
        for item in function.reverts
        if not any(
            item.id in statement.evidence_refs or item.statement_id in statement.evidence_refs
            for statement in statements
        )
    ]
    unsupported_calls = [
        statement.call_type
        for statement in statements
        if statement.call_type is not None and statement.call_type not in CALL_TYPES
    ]
    incorrect_call_types: list[str] = []
    for call in function.external_calls:
        matching = [
            statement
            for statement in statements
            if call.id in statement.evidence_refs or call.statement_id in statement.evidence_refs
        ]
        if matching and any(statement.call_type != call.call_type for statement in matching):
            incorrect_call_types.append(
                f"{call.id}: expected {call.call_type}, got {matching[0].call_type or '<unknown>'}"
            )
    unsupported_claims = (
        [f"unsupported call type: {item}" for item in unsupported_calls]
        + incorrect_call_types
        + semantic_mismatches
    )
    has_failures = any(
        (
            missing_writes,
            missing_calls,
            missing_events,
            missing_reverts,
            incorrect_constants,
            unsupported_claims,
        )
    )
    return ReviewResult(
        missing_storage_writes=missing_writes,
        missing_calls=missing_calls,
        missing_events=missing_events,
        missing_reverts=missing_reverts,
        incorrect_constants=incorrect_constants,
        unsupported_semantic_claims=unsupported_claims,
        severity="fail" if has_failures else "pass",
    )
