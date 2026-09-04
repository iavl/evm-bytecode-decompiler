from pydantic import BaseModel, ConfigDict, Field

from ..models.ir import ContractIR


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


def compute_coverage(contract: ContractIR) -> ValidationCoverage:
    branches = sum(
        1
        for function in contract.functions
        for block in function.blocks
        if len(block.successor_ids) > 1
    )
    return ValidationCoverage(
        functions=1.0,
        storage_writes=_ratio(len([item for item in contract.storage if item.access == "write"])),
        external_calls=_ratio(len(contract.external_calls)),
        events=_ratio(len(contract.events)),
        reverts=_ratio(len(contract.reverts)),
        branches=_ratio(branches),
    )
