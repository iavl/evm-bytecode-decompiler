from pydantic import BaseModel, ConfigDict, Field

from ..ai.schemas import PseudoFunction
from ..models.ir import ContractIR
from .hallucination import validate_pseudo_function


class ValidationCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    functions: float = Field(ge=0.0, le=1.0)
    storage_writes: float = Field(ge=0.0, le=1.0)
    external_calls: float = Field(ge=0.0, le=1.0)
    events: float = Field(ge=0.0, le=1.0)
    reverts: float = Field(ge=0.0, le=1.0)
    branches: float = Field(ge=0.0, le=1.0)


def _ratio(total: int, represented: int | None = None) -> float:
    return 1.0 if total == 0 else (represented if represented is not None else total) / total


def compute_coverage(
    contract: ContractIR,
    pseudo_by_id: dict[str, PseudoFunction] | None = None,
) -> ValidationCoverage:
    branches = sum(
        1
        for function in contract.functions
        for block in function.blocks
        if len(block.successor_ids) > 1
    )
    storage_write_count = len([item for item in contract.storage if item.access == "write"])
    if pseudo_by_id is None:
        return ValidationCoverage(
            functions=1.0,
            storage_writes=_ratio(storage_write_count),
            external_calls=_ratio(len(contract.external_calls)),
            events=_ratio(len(contract.events)),
            reverts=_ratio(len(contract.reverts)),
            branches=_ratio(branches),
        )
    reviews = {
        function.id: validate_pseudo_function(function, pseudo_by_id[function.id])
        for function in contract.functions
        if function.id in pseudo_by_id
    }
    covered_functions = len(reviews)
    total_writes = sum(len(function.storage_writes) for function in contract.functions)
    total_calls = sum(len(function.external_calls) for function in contract.functions)
    total_events = sum(len(function.events) for function in contract.functions)
    total_reverts = sum(len(function.reverts) for function in contract.functions)
    covered_writes = 0
    covered_calls = 0
    covered_events = 0
    covered_reverts = 0
    for function in contract.functions:
        review = reviews.get(function.id)
        if review is None:
            continue
        covered_writes += len(function.storage_writes) - len(review.missing_storage_writes)
        covered_calls += len(function.external_calls) - len(review.missing_calls)
        covered_events += len(function.events) - len(review.missing_events)
        covered_reverts += len(function.reverts) - len(review.missing_reverts)
    return ValidationCoverage(
        functions=_ratio(len(contract.functions), covered_functions),
        storage_writes=_ratio(
            total_writes,
            covered_writes,
        ),
        external_calls=_ratio(total_calls, covered_calls),
        events=_ratio(total_events, covered_events),
        reverts=_ratio(total_reverts, covered_reverts),
        branches=_ratio(branches),
    )
