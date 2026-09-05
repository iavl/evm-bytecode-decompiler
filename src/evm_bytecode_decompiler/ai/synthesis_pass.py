import asyncio
import json
from dataclasses import dataclass, field

from ..cache.keys import cache_key, schema_hash
from ..cache.store import CacheStore
from ..errors import AIProviderError, AIResponseValidationError
from ..models.ir import ContractIR, FunctionIR
from ..validation.hallucination import validate_pseudo_function
from .prompts import load_prompt, prompt_hash
from .provider import AIProvider, provider_identity
from .reconciliation import ReconciliationResult
from .schemas import (
    ContractSemanticReconciliation,
    FunctionSemanticAnnotation,
    PseudoFunction,
    ReviewResult,
)


@dataclass
class SynthesisResult:
    functions: dict[str, PseudoFunction] = field(default_factory=dict)
    reviews: dict[str, ReviewResult] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)
    cache_hits: int = 0


def synthesis_slice(
    function: FunctionIR,
    annotation: FunctionSemanticAnnotation | None,
    reconciliation: ContractSemanticReconciliation,
) -> dict[str, object]:
    return {
        "function_ir": function.model_dump(mode="json"),
        "annotation": annotation.model_dump(mode="json") if annotation else None,
        "contract_storage_labels": reconciliation.storage_labels,
        "evidence_ids": sorted(
            {
                item.id
                for item in function.storage_reads
                + function.storage_writes
                + function.external_calls
                + function.events
                + function.reverts
            }
            | {
                item.fact_id
                for block in function.blocks
                for statement in block.statements
                for item in statement.evidence
                if item.fact_id
            }
            | {
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
            }
        ),
    }


def _review_text(review: ReviewResult) -> str:
    return json.dumps(review.model_dump(mode="json"), sort_keys=True)


async def run_synthesis(
    contract: ContractIR,
    annotations: dict[str, FunctionSemanticAnnotation],
    reconciliation: ReconciliationResult,
    *,
    provider: AIProvider,
    cache: CacheStore | None = None,
    max_concurrency: int = 4,
    temperature: float = 0.0,
    max_prompt_bytes: int = 128 * 1024,
) -> SynthesisResult:
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")
    if max_prompt_bytes < 1:
        raise ValueError("max_prompt_bytes must be positive")
    result = SynthesisResult()
    semaphore = asyncio.Semaphore(max_concurrency)
    system = load_prompt("synthesize_function.v1.md")
    version = prompt_hash("synthesize_function.v1.md")

    async def one(function: FunctionIR) -> None:
        context = synthesis_slice(function, annotations.get(function.id), reconciliation.semantics)
        key = cache_key(
            {"context": context, "temperature": temperature},
            prompt_version=version,
            model=provider_identity(provider),
            schema_version=1,
            schema_hash=schema_hash(PseudoFunction),
        )
        if cache:
            cached = cache.get(key)
            if cached is not None:
                try:
                    cached_pseudo = PseudoFunction.model_validate(cached)
                    review = validate_pseudo_function(function, cached_pseudo)
                except (ValueError, TypeError) as exc:
                    result.rejected[function.id] = f"invalid cached synthesis: {exc}"
                else:
                    if review.severity == "fail":
                        result.rejected[function.id] = _review_text(review)
                    else:
                        result.functions[function.id] = cached_pseudo
                        result.reviews[function.id] = review
                        result.cache_hits += 1
                    return
        prompt = json.dumps(context, sort_keys=True, indent=2)
        if len(prompt.encode("utf-8")) > max_prompt_bytes:
            result.rejected[function.id] = (
                f"synthesis prompt exceeds {max_prompt_bytes} bytes; function was not truncated"
            )
            return
        pseudo: PseudoFunction | None = None
        review = ReviewResult(severity="fail")
        for attempt in range(2):
            try:
                async with semaphore:
                    pseudo = await provider.generate_structured(
                        system=system,
                        prompt=prompt,
                        schema=PseudoFunction,
                        temperature=temperature,
                    )
                review = validate_pseudo_function(function, pseudo)
            except (AIProviderError, AIResponseValidationError, ValueError, TypeError) as exc:
                result.rejected[function.id] = str(exc)
                return
            if review.severity != "fail" or attempt == 1:
                break
            prompt = (
                json.dumps(context, sort_keys=True, indent=2)
                + "\nREPAIR_REQUEST\n"
                + _review_text(review)
            )
        if pseudo is None or review.severity == "fail":
            result.rejected[function.id] = _review_text(review)
            return
        result.functions[function.id] = pseudo
        result.reviews[function.id] = review
        if cache:
            cache.put(key, pseudo.model_dump(mode="json"))

    await asyncio.gather(*(one(function) for function in contract.functions))
    return result
