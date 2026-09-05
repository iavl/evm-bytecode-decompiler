import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .. import __version__
from ..errors import AnnotationError
from ..models.annotations import AnnotationProposal, FunctionAnnotation
from ..models.ir import FunctionIR
from ..pipeline.artifacts import artifact_hash, load_contract, load_storage, validate_manifest

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RESERVED_IDENTIFIERS = {
    "break",
    "case",
    "contract",
    "else",
    "external",
    "false",
    "function",
    "if",
    "import",
    "internal",
    "mapping",
    "new",
    "private",
    "public",
    "return",
    "struct",
    "true",
    "uint256",
    "while",
}


def _evidence_ids(function: FunctionIR) -> set[str]:
    known = {function.id}
    known.update(block.id for block in function.blocks)
    known.update(statement.id for block in function.blocks for statement in block.statements)
    known.update(item.id for item in function.storage_reads + function.storage_writes)
    known.update(item.id for item in function.external_calls + function.events + function.reverts)
    references = list(function.evidence)
    references.extend(
        reference
        for block in function.blocks
        for statement in block.statements
        for reference in statement.evidence
    )
    references.extend(
        reference
        for item in (
            function.storage_reads
            + function.storage_writes
            + function.external_calls
            + function.events
            + function.reverts
        )
        for reference in item.evidence
    )
    for reference in references:
        for value in (reference.fact_id, reference.statement_id, reference.block_id):
            if value:
                known.add(value)
    return known


def _all_evidence(functions: list[FunctionIR]) -> set[str]:
    return {value for function in functions for value in _evidence_ids(function)}


def _validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER_RE.fullmatch(value) or value in RESERVED_IDENTIFIERS:
        raise AnnotationError(f"{label} is not a valid Solidity identifier: {value!r}")


def _validate_text(value: str, label: str) -> None:
    if len(value) > 4096 or any(character in value for character in "\x00\r\n"):
        raise AnnotationError(f"{label} contains unsupported control characters or is too long")


def _validate_type(value: str, label: str) -> None:
    _validate_text(value, label)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]*\])*", value):
        raise AnnotationError(f"{label} is not a supported type label: {value!r}")


def _has_function_claim(annotation: FunctionAnnotation) -> bool:
    return bool(
        annotation.proposed_name
        or annotation.summary
        or annotation.argument_names
        or annotation.argument_types
        or annotation.storage_labels
        or annotation.semantic_patterns
        or annotation.uncertainties
    )


def _parse_proposal(proposal: AnnotationProposal | Mapping[str, Any] | Path) -> AnnotationProposal:
    if isinstance(proposal, Path):
        try:
            value = json.loads(proposal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AnnotationError(f"could not read annotation proposal: {exc}") from exc
    else:
        value = proposal
    if isinstance(value, AnnotationProposal):
        return value
    try:
        return AnnotationProposal.model_validate(value)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise AnnotationError(f"invalid annotation proposal: {exc}") from exc


def validate_proposal(
    run_dir: Path,
    proposal: AnnotationProposal | Mapping[str, Any] | Path,
) -> AnnotationProposal:
    """Validate a proposal against canonical evidence without writing files."""
    manifest = validate_manifest(run_dir)
    contract = load_contract(run_dir)
    parsed = _parse_proposal(proposal)
    fingerprint = manifest.get("fingerprint")
    if parsed.run_fingerprint != fingerprint:
        raise AnnotationError("annotation run_fingerprint does not match the deterministic run")

    functions = {function.id: function for function in contract.functions}
    storage = load_storage(run_dir)
    storage_ids = {value for item in storage for value in [item.id, *item.evidence]}
    known_global = _all_evidence(contract.functions) | storage_ids
    for function_id, annotation in parsed.functions.items():
        function = functions.get(function_id)
        if function is None:
            raise AnnotationError(f"annotation references unknown function: {function_id}")
        if (
            annotation.selector is not None
            and annotation.selector.lower() != (function.selector or "").lower()
        ):
            raise AnnotationError(f"annotation selector does not match function: {function_id}")
        function_storage_ids = {
            item.id for item in function.storage_reads + function.storage_writes
        }
        function_known = _evidence_ids(function) | {
            item.id for item in storage if set(item.evidence) & function_storage_ids
        }
        unknown = sorted(set(annotation.evidence_refs) - function_known)
        if unknown:
            raise AnnotationError(f"annotation references unknown function evidence: {unknown}")
        if _has_function_claim(annotation) and not annotation.evidence_refs:
            raise AnnotationError(f"function annotation needs evidence_refs: {function_id}")
        if annotation.proposed_name:
            _validate_identifier(annotation.proposed_name, "proposed_name")
        _validate_text(annotation.summary, f"summary for {function_id}")
        for value in [*annotation.semantic_patterns, *annotation.uncertainties]:
            _validate_text(value, f"semantic text for {function_id}")
        for key, value in {**annotation.argument_names, **annotation.storage_labels}.items():
            _validate_identifier(value, f"annotation label for {key}")
        for key, value in annotation.argument_types.items():
            _validate_type(value, f"argument type for {key}")
        argument_ids = {item.id for item in function.arguments}
        argument_ids.update(f"arg{index}" for index in range(len(function.arguments)))
        for key in [*annotation.argument_names, *annotation.argument_types]:
            if key not in argument_ids:
                raise AnnotationError(f"annotation references unknown argument: {key}")
        storage_access_ids = {item.id for item in function.storage_reads + function.storage_writes}
        storage_access_ids.update(
            item.id for item in storage if set(item.evidence) & storage_access_ids
        )
        unknown_storage = sorted(set(annotation.storage_labels) - storage_access_ids)
        if unknown_storage:
            raise AnnotationError(f"annotation references unknown storage: {unknown_storage}")

    contract_annotation = parsed.contract
    contract_claim = bool(
        contract_annotation.summary
        or contract_annotation.roles
        or contract_annotation.patterns
        or contract_annotation.uncertainties
        or parsed.storage_labels
    )
    unknown_contract = sorted(set(contract_annotation.evidence_refs) - known_global)
    if unknown_contract:
        raise AnnotationError(
            f"contract annotation references unknown evidence: {unknown_contract}"
        )
    if contract_claim and not contract_annotation.evidence_refs:
        raise AnnotationError("contract semantic claims need evidence_refs")
    _validate_text(contract_annotation.summary, "contract summary")
    for key, value in {**contract_annotation.roles, **parsed.storage_labels}.items():
        _validate_text(key, "contract annotation key")
        _validate_text(value, "contract annotation value")
    for value in [*contract_annotation.patterns, *contract_annotation.uncertainties]:
        _validate_text(value, "contract semantic text")
    for key, value in parsed.storage_labels.items():
        _validate_identifier(value, f"contract label for {key}")
    unknown_labels = sorted(set(parsed.storage_labels) - storage_ids)
    if unknown_labels:
        raise AnnotationError(f"annotation references unknown storage label: {unknown_labels}")
    labels = list(parsed.storage_labels.values())
    if len(labels) != len(set(labels)):
        raise AnnotationError("annotation contains duplicate storage labels")
    return parsed


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def apply_proposal(
    run_dir: Path,
    proposal: AnnotationProposal | Mapping[str, Any] | Path,
) -> AnnotationProposal:
    """Validate and persist an agent overlay without touching canonical artifacts."""
    parsed = validate_proposal(run_dir, proposal)
    value = parsed.model_dump(mode="json")
    agent_dir = run_dir / "agent"
    annotations_path = agent_dir / "annotations.json"
    _write_json(agent_dir / "proposal.json", value)
    _write_json(annotations_path, value)
    annotations_hash = artifact_hash(annotations_path)
    _write_json(
        agent_dir / "manifest.json",
        {
            "schema_version": 1,
            "deterministic_run_fingerprint": parsed.run_fingerprint,
            "annotations_sha256": annotations_hash,
            "tool_version": __version__,
        },
    )
    return parsed
