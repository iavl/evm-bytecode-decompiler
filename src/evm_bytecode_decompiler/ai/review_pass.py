import asyncio
import json
from dataclasses import dataclass, field

from ..errors import AIProviderError, AIResponseValidationError
from ..models.ir import FunctionIR
from ..validation.hallucination import validate_pseudo_function
from .prompts import load_prompt
from .provider import AIProvider
from .schemas import PseudoFunction, ReviewResult


@dataclass
class ReviewPassResult:
    reviews: dict[str, ReviewResult] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)


async def run_reviews(
    functions: list[FunctionIR],
    synthesized: dict[str, PseudoFunction],
    *,
    provider: AIProvider,
    max_concurrency: int = 4,
    temperature: float = 0.0,
    max_prompt_bytes: int = 128 * 1024,
) -> ReviewPassResult:
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")
    if max_prompt_bytes < 1:
        raise ValueError("max_prompt_bytes must be positive")
    result = ReviewPassResult()
    semaphore = asyncio.Semaphore(max_concurrency)
    system = load_prompt("review_function.v1.md")

    async def one(function: FunctionIR) -> None:
        pseudo = synthesized.get(function.id)
        if pseudo is None:
            return
        deterministic = validate_pseudo_function(function, pseudo)
        if deterministic.severity == "fail":
            result.reviews[function.id] = deterministic
            return
        context = {
            "function_ir": function.model_dump(mode="json"),
            "pseudo_function": pseudo.model_dump(mode="json"),
        }
        prompt = json.dumps(context, sort_keys=True, indent=2)
        if len(prompt.encode("utf-8")) > max_prompt_bytes:
            result.rejected[function.id] = (
                f"review prompt exceeds {max_prompt_bytes} bytes; function was not truncated"
            )
            return
        try:
            async with semaphore:
                review = await provider.generate_structured(
                    system=system,
                    prompt=prompt,
                    schema=ReviewResult,
                    temperature=temperature,
                )
            if review.severity == "pass" and (
                review.missing_storage_writes
                or review.missing_calls
                or review.missing_events
                or review.missing_reverts
                or review.incorrect_constants
                or review.unsupported_semantic_claims
            ):
                review.severity = "fail"
            result.reviews[function.id] = review
        except (AIProviderError, AIResponseValidationError, ValueError, TypeError) as exc:
            result.rejected[function.id] = str(exc)

    await asyncio.gather(*(one(function) for function in functions))
    return result
