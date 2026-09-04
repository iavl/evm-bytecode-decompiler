import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..cache.keys import cache_key
from ..cache.store import CacheStore
from ..errors import AIProviderError, AIResponseValidationError
from ..inference.storage import StorageLayoutEntry
from ..models.ir import ContractIR
from .prompts import load_prompt, prompt_hash
from .provider import AIProvider
from .schemas import ContractSemanticReconciliation, FunctionSemanticAnnotation

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


@dataclass
class ReconciliationResult:
    semantics: ContractSemanticReconciliation = field(
        default_factory=ContractSemanticReconciliation
    )
    rejected: str | None = None
    cache_hit: bool = False


def contract_semantic_slice(
    contract: ContractIR,
    annotations: list[FunctionSemanticAnnotation],
    storage: list[StorageLayoutEntry],
) -> dict[str, Any]:
    evidence: set[str] = set()
    for function in contract.functions:
        evidence.update(item.fact_id for item in function.evidence if item.fact_id is not None)
        evidence.update(statement.id for block in function.blocks for statement in block.statements)
    evidence.update(item.id for item in contract.storage)
    evidence.update(item.id for item in contract.external_calls)
    evidence.update(item.id for item in contract.events)
    evidence.update(item.id for item in contract.reverts)
    return {
        "function_annotations": [item.model_dump(mode="json") for item in annotations],
        "storage": [item.model_dump(mode="json") for item in storage],
        "deterministic_facts": {
            "function_ids": [item.id for item in contract.functions],
            "storage_access_ids": [item.id for item in contract.storage],
            "call_types": [item.call_type for item in contract.external_calls],
            "event_ids": [item.id for item in contract.events],
        },
        "evidence_ids": sorted(evidence),
    }


def validate_reconciliation(
    semantics: ContractSemanticReconciliation,
    contract: ContractIR,
) -> ContractSemanticReconciliation:
    function_ids = {item.id for item in contract.functions}
    storage_ids = {item.id for item in contract.storage}
    unknown_functions = sorted(set(semantics.function_names) - function_ids)
    unknown_storage = sorted(set(semantics.storage_labels) - storage_ids)
    if unknown_functions or unknown_storage:
        raise AIResponseValidationError(
            f"reconciliation references unknown ids: functions={unknown_functions}, "
            f"storage={unknown_storage}"
        )
    known_evidence = {
        item.fact_id
        for function in contract.functions
        for item in function.evidence
        if item.fact_id
    }
    known_evidence.update(
        statement.id
        for function in contract.functions
        for block in function.blocks
        for statement in block.statements
    )
    known_evidence.update(item.id for item in contract.storage)
    known_evidence.update(item.id for item in contract.external_calls)
    known_evidence.update(item.id for item in contract.events)
    known_evidence.update(item.id for item in contract.reverts)
    unknown_evidence = sorted(set(semantics.evidence_refs) - known_evidence)
    if unknown_evidence:
        raise AIResponseValidationError(
            f"reconciliation references unknown evidence: {unknown_evidence}"
        )
    names = list(semantics.function_names.values()) + list(semantics.storage_labels.values())
    if any(not IDENTIFIER_RE.fullmatch(name) for name in names):
        raise AIResponseValidationError("reconciliation contains an invalid identifier")
    return semantics


async def run_reconciliation(
    contract: ContractIR,
    annotations: list[FunctionSemanticAnnotation],
    storage: list[StorageLayoutEntry],
    *,
    provider: AIProvider,
    cache: CacheStore | None = None,
    temperature: float = 0.0,
) -> ReconciliationResult:
    context = contract_semantic_slice(contract, annotations, storage)
    version = prompt_hash("contract_reconcile.v1.md")
    key = cache_key(
        context,
        prompt_version=version,
        model=getattr(provider, "model", "unknown"),
        schema_version=1,
    )
    if cache:
        cached = cache.get(key)
        if cached is not None:
            try:
                semantics = validate_reconciliation(
                    ContractSemanticReconciliation.model_validate(cached), contract
                )
            except (ValueError, TypeError, AIResponseValidationError) as exc:
                return ReconciliationResult(rejected=f"invalid cached reconciliation: {exc}")
            usage = getattr(provider, "usage", None)
            if usage is not None and hasattr(usage, "cache_hits"):
                usage.cache_hits += 1
            return ReconciliationResult(semantics=semantics, cache_hit=True)
    try:
        semantics = await provider.generate_structured(
            system=load_prompt("contract_reconcile.v1.md"),
            prompt=json.dumps(context, sort_keys=True, indent=2),
            schema=ContractSemanticReconciliation,
            temperature=temperature,
        )
        semantics = validate_reconciliation(semantics, contract)
    except (AIProviderError, AIResponseValidationError, ValueError, TypeError) as exc:
        return ReconciliationResult(rejected=str(exc))
    if cache:
        cache.put(key, semantics.model_dump(mode="json"))
    return ReconciliationResult(semantics=semantics)
