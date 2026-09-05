from pathlib import Path
from typing import Any

from ..models.ir import FunctionIR
from ..pipeline.artifacts import (
    load_abi,
    load_contract,
    load_storage,
    validate_manifest,
)

DEFAULT_MAX_FUNCTIONS = 64
DEFAULT_MAX_STATEMENTS = 512
DEFAULT_MAX_FACTS = 256
DEFAULT_MAX_STORAGE = 256


def _function_evidence_ids(function: FunctionIR) -> set[str]:
    identifiers = {function.id}
    identifiers.update(block.id for block in function.blocks)
    identifiers.update(statement.id for block in function.blocks for statement in block.statements)
    identifiers.update(item.id for item in function.storage_reads + function.storage_writes)
    identifiers.update(
        item.id for item in function.external_calls + function.events + function.reverts
    )
    for item in (
        function.evidence,
        [
            reference
            for block in function.blocks
            for statement in block.statements
            for reference in statement.evidence
        ],
        [
            reference
            for access in function.storage_reads + function.storage_writes
            for reference in access.evidence
        ],
        [reference for call in function.external_calls for reference in call.evidence],
        [reference for event in function.events for reference in event.evidence],
        [reference for revert in function.reverts for reference in revert.evidence],
    ):
        identifiers.update(reference.fact_id for reference in item if reference.fact_id)
        identifiers.update(reference.statement_id for reference in item if reference.statement_id)
        identifiers.update(reference.block_id for reference in item if reference.block_id)
    return identifiers


def _function_context(function: FunctionIR, *, max_statements: int) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    included_statements = 0
    omitted_statements = 0
    omitted_blocks = 0
    for block in function.blocks:
        if included_statements + len(block.statements) > max_statements and blocks:
            omitted_blocks += 1
            omitted_statements += len(block.statements)
            continue
        if included_statements + len(block.statements) > max_statements:
            remaining = max_statements - included_statements
            clipped = block.model_copy(update={"statements": block.statements[:remaining]})
            blocks.append(clipped.model_dump(mode="json"))
            omitted_statements += len(block.statements) - remaining
            included_statements = max_statements
            continue
        blocks.append(block.model_dump(mode="json"))
        included_statements += len(block.statements)
    fact_values = {
        "storage_reads": [item.model_dump(mode="json") for item in function.storage_reads],
        "storage_writes": [item.model_dump(mode="json") for item in function.storage_writes],
        "external_calls": [item.model_dump(mode="json") for item in function.external_calls],
        "events": [item.model_dump(mode="json") for item in function.events],
        "reverts": [item.model_dump(mode="json") for item in function.reverts],
    }
    omitted_facts = {
        name: max(0, len(values) - DEFAULT_MAX_FACTS) for name, values in fact_values.items()
    }
    evidence_ids = sorted(_function_evidence_ids(function))
    return {
        "id": function.id,
        "selector": function.selector,
        "entry_block": function.entry_block,
        "arguments": [item.model_dump(mode="json") for item in function.arguments],
        "returns": [item.model_dump(mode="json") for item in function.returns],
        "blocks": blocks,
        **{name: values[:DEFAULT_MAX_FACTS] for name, values in fact_values.items()},
        "evidence_ids": evidence_ids[: DEFAULT_MAX_FACTS * 4],
        "truncated": bool(
            omitted_blocks
            or omitted_statements
            or any(omitted_facts.values())
            or len(evidence_ids) > DEFAULT_MAX_FACTS * 4
        ),
        "omitted_blocks": omitted_blocks,
        "omitted_statements": omitted_statements,
        "omitted_facts": {name: count for name, count in omitted_facts.items() if count},
        "omitted_evidence": max(0, len(evidence_ids) - DEFAULT_MAX_FACTS * 4),
    }


def _base_context(run_dir: Path) -> tuple[dict[str, Any], Any, Any, list[Any]]:
    manifest = validate_manifest(run_dir)
    contract = load_contract(run_dir)
    abi = load_abi(run_dir)
    storage = load_storage(run_dir)
    backend = manifest.get("backend", {})
    if not isinstance(backend, dict):
        backend = {}
    analysis = contract.metadata.get("analysis", {})
    if not isinstance(analysis, dict):
        analysis = {}
    proxy = contract.metadata.get("proxy", {})
    if not isinstance(proxy, dict):
        proxy = {}
    functions = contract.functions[:DEFAULT_MAX_FUNCTIONS]
    omitted = max(0, len(contract.functions) - len(functions))
    function_inventory = []
    selector_map: dict[str, str] = {}
    abi_by_id = {item.function_id: item for item in abi.functions}
    for function in functions:
        info = abi_by_id.get(function.id)
        item = {
            "id": function.id,
            "selector": function.selector,
            "name": info.name if info else function.id,
            "arguments": info.arguments if info else [value.id for value in function.arguments],
            "blocks": len(function.blocks),
            "statements": sum(len(block.statements) for block in function.blocks),
            "storage_reads": len(function.storage_reads),
            "storage_writes": len(function.storage_writes),
            "external_calls": len(function.external_calls),
            "events": len(function.events),
            "reverts": len(function.reverts),
        }
        function_inventory.append(item)
        if function.selector:
            selector_map[function.selector] = function.id
    unresolved = [
        statement.id
        for block in contract.blocks
        for statement in block.statements
        if statement.truncated or statement.opcode.startswith("OP_")
    ]
    context = {
        "context_schema_version": 1,
        "run_fingerprint": manifest["fingerprint"],
        "input": manifest.get("input", {}),
        "backend": {
            "name": backend.get("name", analysis.get("backend", "unknown")),
            "version": backend.get("version"),
            "commit": backend.get("commit"),
            "completeness": backend.get("completeness", "unknown"),
            "warnings": analysis.get("warnings", []),
        },
        "proxy": proxy,
        "abi": [item.model_dump(mode="json") for item in abi.functions[:DEFAULT_MAX_FUNCTIONS]],
        "storage": [item.model_dump(mode="json") for item in storage[:DEFAULT_MAX_STORAGE]],
        "functions": function_inventory,
        "selector_to_function_id": selector_map,
        "counts": {
            "functions": len(contract.functions),
            "blocks": len(contract.blocks),
            "statements": len(contract.statements),
            "storage_accesses": len(contract.storage),
            "external_calls": len(contract.external_calls),
            "events": len(contract.events),
            "reverts": len(contract.reverts),
            "unassigned_blocks": len(contract.unassigned_block_ids),
        },
        "unresolved_statement_ids": unresolved[:DEFAULT_MAX_STATEMENTS],
        "truncated": bool(omitted or len(storage) > DEFAULT_MAX_STORAGE),
        "omitted_functions": omitted,
        "omitted_storage": max(0, len(storage) - DEFAULT_MAX_STORAGE),
        "limits": {
            "max_functions": DEFAULT_MAX_FUNCTIONS,
            "max_storage": DEFAULT_MAX_STORAGE,
            "max_facts_per_function": DEFAULT_MAX_FACTS,
            "max_statements": DEFAULT_MAX_STATEMENTS,
        },
    }
    return context, contract, abi, storage


def build_contract_context(run_dir: Path) -> dict[str, Any]:
    """Return bounded contract-level evidence for an agent."""
    return _base_context(run_dir)[0]


def build_function_context(
    run_dir: Path,
    selector: str,
    *,
    max_statements: int = DEFAULT_MAX_STATEMENTS,
) -> dict[str, Any]:
    """Return bounded canonical evidence for one selector."""
    if max_statements < 1:
        raise ValueError("max_statements must be positive")
    max_statements = min(max_statements, DEFAULT_MAX_STATEMENTS)
    context, contract, abi, storage = _base_context(run_dir)
    normalized_selector = selector.lower()
    function = next(
        (
            item
            for item in contract.functions
            if item.selector and item.selector.lower() == normalized_selector
        ),
        None,
    )
    if function is None:
        raise ValueError(f"selector not found: {selector}")
    context["scope"] = "function"
    context["function"] = _function_context(function, max_statements=max_statements)
    context["function_abi"] = next(
        (item.model_dump(mode="json") for item in abi.functions if item.function_id == function.id),
        None,
    )
    context["storage"] = [item.model_dump(mode="json") for item in storage[:DEFAULT_MAX_STORAGE]]
    context["omitted_storage"] = max(0, len(storage) - DEFAULT_MAX_STORAGE)
    context["limits"] = {**context["limits"], "max_statements": max_statements}
    return context


def build_context(run_dir: Path, selector: str | None = None) -> dict[str, Any]:
    if selector:
        return build_function_context(run_dir, selector)
    return build_contract_context(run_dir)
