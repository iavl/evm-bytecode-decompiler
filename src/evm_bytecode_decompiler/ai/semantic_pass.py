import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..cache.keys import cache_key, schema_hash
from ..cache.store import CacheStore
from ..errors import AIProviderError, AIResponseValidationError
from ..inference.abi import InferredFunction
from ..inference.storage import StorageLayoutEntry
from ..models.ir import FunctionIR
from .prompts import load_prompt, prompt_hash
from .provider import AIProvider, provider_identity
from .schemas import FunctionSemanticAnnotation

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


@dataclass
class SemanticPassResult:
    annotations: dict[str, FunctionSemanticAnnotation] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)
    cache_hits: int = 0


def function_slice(
    function: FunctionIR,
    *,
    abi: InferredFunction | None = None,
    storage: list[StorageLayoutEntry] | None = None,
) -> dict[str, Any]:
    """Build the bounded, deterministic context sent to a semantic provider."""
    evidence: set[str] = set()
    for item in function.evidence:
        if item.fact_id:
            evidence.add(item.fact_id)
    for block in function.blocks:
        for item in block.evidence:
            if item.fact_id:
                evidence.add(item.fact_id)
        for statement in block.statements:
            evidence.add(statement.id)
            evidence.update(item.fact_id for item in statement.evidence if item.fact_id)
    for access in function.storage_reads + function.storage_writes:
        evidence.add(access.id)
        evidence.update(item.fact_id for item in access.evidence if item.fact_id)
    for fact in function.external_calls + function.events + function.reverts:
        evidence.add(fact.id)
        evidence.update(item.fact_id for item in fact.evidence if item.fact_id)
    return {
        "function": function.model_dump(mode="json"),
        "selector": function.selector,
        "signature_candidates": [
            item.model_dump(mode="json") for item in (abi.candidates if abi else [])
        ],
        "storage_layout": [item.model_dump(mode="json") for item in (storage or [])],
        "evidence_ids": sorted(evidence),
    }


def _known_evidence(function: FunctionIR) -> set[str]:
    result = set(function_slice(function)["evidence_ids"])
    return result


def _known_constants(function: FunctionIR) -> set[int]:
    return {
        statement.operand
        for block in function.blocks
        for statement in block.statements
        if statement.operand is not None
    }


def _parse_constant(value: str) -> int | None:
    try:
        return int(value, 0)
    except ValueError:
        try:
            return int(value)
        except ValueError:
            return None


def validate_annotation(
    annotation: FunctionSemanticAnnotation,
    function: FunctionIR,
) -> FunctionSemanticAnnotation:
    if annotation.function_id != function.id:
        raise AIResponseValidationError(
            f"annotation references unknown function {annotation.function_id}"
        )
    if annotation.selector is not None and annotation.selector != function.selector:
        raise AIResponseValidationError(
            f"annotation changed selector {function.selector} to {annotation.selector}"
        )
    known_evidence = _known_evidence(function)
    unknown_evidence = sorted(set(annotation.evidence_refs) - known_evidence)
    if unknown_evidence:
        raise AIResponseValidationError(
            f"annotation references unknown evidence: {unknown_evidence}"
        )
    proposal_evidence = {
        reference
        for proposal in annotation.proposals.values()
        for reference in proposal.evidence_refs
    }
    unknown_proposal_evidence = sorted(proposal_evidence - known_evidence)
    if unknown_proposal_evidence:
        raise AIResponseValidationError(
            f"proposal references unknown evidence: {unknown_proposal_evidence}"
        )
    if any(not proposal.evidence_refs for proposal in annotation.proposals.values()):
        raise AIResponseValidationError("semantic proposals must cite evidence")
    known_arguments = {item.id for item in function.arguments}
    unknown_arguments = sorted(set(annotation.argument_names) - known_arguments)
    unknown_arguments.extend(sorted(set(annotation.argument_types) - known_arguments))
    if unknown_arguments:
        raise AIResponseValidationError(
            f"annotation references unknown arguments: {unknown_arguments}"
        )
    known_storage = {item.id for item in function.storage_reads + function.storage_writes}
    unknown_storage = sorted(set(annotation.storage_labels) - known_storage)
    if unknown_storage:
        raise AIResponseValidationError(f"annotation references unknown storage: {unknown_storage}")
    names = list(annotation.argument_names.values()) + list(annotation.storage_labels.values())
    if any(not IDENTIFIER_RE.fullmatch(name) or name in RESERVED_IDENTIFIERS for name in names):
        raise AIResponseValidationError("annotation contains an invalid identifier")
    known_constants = _known_constants(function)
    unsupported = [
        value
        for value in annotation.claimed_constants
        if _parse_constant(value) is None or _parse_constant(value) not in known_constants
    ]
    if unsupported:
        raise AIResponseValidationError(f"annotation claims unsupported constants: {unsupported}")
    if annotation.proposed_name and (
        not IDENTIFIER_RE.fullmatch(annotation.proposed_name)
        or annotation.proposed_name in RESERVED_IDENTIFIERS
    ):
        raise AIResponseValidationError("proposed function name is not a Solidity identifier")
    if any(
        not IDENTIFIER_RE.fullmatch(proposal.value) or proposal.value in RESERVED_IDENTIFIERS
        for proposal in annotation.proposals.values()
    ):
        raise AIResponseValidationError("semantic proposal contains an invalid identifier")
    return annotation


def _mark_cache_hit(provider: AIProvider) -> None:
    usage = getattr(provider, "usage", None)
    if usage is not None and hasattr(usage, "cache_hits"):
        usage.cache_hits += 1


async def run_function_semantics(
    functions: list[FunctionIR],
    *,
    provider: AIProvider,
    abi_by_id: dict[str, InferredFunction] | None = None,
    storage: list[StorageLayoutEntry] | None = None,
    cache: CacheStore | None = None,
    max_concurrency: int = 4,
    temperature: float = 0.0,
    max_prompt_bytes: int = 128 * 1024,
) -> SemanticPassResult:
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")
    if max_prompt_bytes < 1:
        raise ValueError("max_prompt_bytes must be positive")
    result = SemanticPassResult()
    semaphore = asyncio.Semaphore(max_concurrency)
    system = load_prompt("function_semantics.v1.md")
    version = prompt_hash("function_semantics.v1.md")

    async def one(function: FunctionIR) -> None:
        context = function_slice(function, abi=(abi_by_id or {}).get(function.id), storage=storage)
        key = cache_key(
            {"context": context, "temperature": temperature},
            prompt_version=version,
            model=provider_identity(provider),
            schema_version=1,
            schema_hash=schema_hash(FunctionSemanticAnnotation),
        )
        canonical_key = cache_key(
            {"function": function.model_dump(mode="json"), "temperature": temperature},
            prompt_version=version,
            model=provider_identity(provider),
            schema_version=1,
            schema_hash=schema_hash(FunctionSemanticAnnotation),
        )
        if cache:
            cached = cache.get(key) or cache.get(canonical_key)
            if cached is not None:
                try:
                    annotation = validate_annotation(
                        FunctionSemanticAnnotation.model_validate(cached), function
                    )
                except (ValueError, TypeError, AIResponseValidationError) as exc:
                    result.rejected[function.id] = f"invalid cached annotation: {exc}"
                else:
                    result.annotations[function.id] = annotation
                    result.cache_hits += 1
                    _mark_cache_hit(provider)
                    return
        prompt = json.dumps(context, sort_keys=True, indent=2)
        if len(prompt.encode("utf-8")) > max_prompt_bytes:
            result.rejected[function.id] = (
                f"semantic prompt exceeds {max_prompt_bytes} bytes; function was not truncated"
            )
            return
        try:
            async with semaphore:
                annotation = await provider.generate_structured(
                    system=system,
                    prompt=prompt,
                    schema=FunctionSemanticAnnotation,
                    temperature=temperature,
                )
            annotation = validate_annotation(annotation, function)
        except (AIProviderError, AIResponseValidationError, ValueError, TypeError) as exc:
            result.rejected[function.id] = str(exc)
            return
        result.annotations[function.id] = annotation
        if cache:
            cache.put(key, annotation.model_dump(mode="json"))
            cache.put(canonical_key, annotation.model_dump(mode="json"))

    await asyncio.gather(*(one(function) for function in functions))
    return result
