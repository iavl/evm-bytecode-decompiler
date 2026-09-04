import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..cache.store import CacheStore
from ..inference.abi import InferredABI
from ..inference.storage import StorageLayoutEntry
from ..models.ir import ContractIR
from .provider import AIProvider, ProviderUsage
from .reconciliation import ReconciliationResult, run_reconciliation
from .review_pass import ReviewPassResult, run_reviews
from .schemas import FunctionSemanticAnnotation, PseudoFunction
from .semantic_pass import SemanticPassResult, run_function_semantics
from .synthesis_pass import SynthesisResult, run_synthesis


@dataclass
class AIPipelineResult:
    annotations: dict[str, FunctionSemanticAnnotation] = field(default_factory=dict)
    reconciliation: ReconciliationResult = field(default_factory=ReconciliationResult)
    synthesis: SynthesisResult = field(default_factory=SynthesisResult)
    review: ReviewPassResult = field(default_factory=ReviewPassResult)
    accepted: dict[str, PseudoFunction] = field(default_factory=dict)
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


def _usage(provider: AIProvider) -> dict[str, Any]:
    value = getattr(provider, "usage", None)
    if isinstance(value, ProviderUsage):
        return {
            "provider": value.provider,
            "model": value.model,
            "requests": value.requests,
            "input_tokens": value.input_tokens,
            "output_tokens": value.output_tokens,
            "cache_hits": value.cache_hits,
        }
    return {
        "provider": getattr(provider, "provider_name", "unknown"),
        "model": getattr(provider, "model", "unknown"),
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_hits": 0,
    }


async def _run(
    contract: ContractIR,
    abi: InferredABI,
    storage: list[StorageLayoutEntry],
    *,
    provider: AIProvider,
    cache: CacheStore | None,
    max_concurrency: int,
    temperature: float,
) -> AIPipelineResult:
    result = AIPipelineResult()
    abi_by_id = {item.function_id: item for item in abi.functions}
    semantic: SemanticPassResult = await run_function_semantics(
        contract.functions,
        provider=provider,
        abi_by_id=abi_by_id,
        storage=storage,
        cache=cache,
        max_concurrency=max_concurrency,
        temperature=temperature,
    )
    result.annotations = semantic.annotations
    result.warnings.extend(
        f"semantic annotation rejected for {function_id}: {message}"
        for function_id, message in semantic.rejected.items()
    )
    result.stages["ai_function_semantics"] = {
        "status": "pass_with_warnings" if semantic.rejected else "pass",
        "accepted": len(semantic.annotations),
        "rejected": len(semantic.rejected),
        "cache_hits": semantic.cache_hits,
    }
    result.reconciliation = await run_reconciliation(
        contract,
        list(semantic.annotations.values()),
        storage,
        provider=provider,
        cache=cache,
        temperature=temperature,
    )
    if result.reconciliation.rejected:
        result.warnings.append(
            f"contract semantic reconciliation rejected: {result.reconciliation.rejected}"
        )
    result.stages["ai_reconciliation"] = {
        "status": "pass_with_warnings" if result.reconciliation.rejected else "pass",
        "cache_hit": result.reconciliation.cache_hit,
    }
    result.synthesis = await run_synthesis(
        contract,
        result.annotations,
        result.reconciliation,
        provider=provider,
        cache=cache,
        max_concurrency=max_concurrency,
        temperature=temperature,
    )
    result.warnings.extend(
        f"synthesis rejected for {function_id}: {message}"
        for function_id, message in result.synthesis.rejected.items()
    )
    result.stages["synthesis"] = {
        "status": "pass_with_warnings" if result.synthesis.rejected else "pass",
        "accepted": len(result.synthesis.functions),
        "rejected": len(result.synthesis.rejected),
        "cache_hits": result.synthesis.cache_hits,
    }
    result.review = await run_reviews(
        contract.functions,
        result.synthesis.functions,
        provider=provider,
        max_concurrency=max_concurrency,
        temperature=temperature,
    )
    result.warnings.extend(
        f"review unavailable for {function_id}: {message}"
        for function_id, message in result.review.rejected.items()
    )
    result.accepted = {}
    for function_id, pseudo in result.synthesis.functions.items():
        review = result.review.reviews.get(function_id)
        if review is None or review.severity != "fail":
            result.accepted[function_id] = pseudo
    # A transport failure in the optional reviewer does not destroy a valid,
    # deterministically checked synthesis; it remains visibly warned in the report.
    result.stages["validation"] = {
        "status": "pass_with_warnings" if result.warnings else "pass",
        "reviewed": len(result.review.reviews),
        "rejected": len(result.review.rejected),
    }
    result.usage = _usage(provider)
    result.usage["cache_hits"] = int(result.usage.get("cache_hits", 0)) + (
        result.synthesis.cache_hits + (1 if result.reconciliation.cache_hit else 0)
    )
    return result


def run_ai_pipeline(
    contract: ContractIR,
    abi: InferredABI,
    storage: list[StorageLayoutEntry],
    *,
    provider: AIProvider,
    cache: CacheStore | None,
    max_concurrency: int,
    temperature: float = 0.0,
) -> AIPipelineResult:
    return asyncio.run(
        _run(
            contract,
            abi,
            storage,
            provider=provider,
            cache=cache,
            max_concurrency=max_concurrency,
            temperature=temperature,
        )
    )
