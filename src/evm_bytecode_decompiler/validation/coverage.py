from pydantic import BaseModel, ConfigDict, Field

from ..models.ir import ContractIR


class ValidationCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    functions: float | None = Field(default=None, ge=0.0, le=1.0)
    storage_writes: float | None = Field(default=None, ge=0.0, le=1.0)
    external_calls: float | None = Field(default=None, ge=0.0, le=1.0)
    events: float | None = Field(default=None, ge=0.0, le=1.0)
    reverts: float | None = Field(default=None, ge=0.0, le=1.0)
    branches: float | None = Field(default=None, ge=0.0, le=1.0)
    analysis_completeness: float = Field(default=1.0, ge=0.0, le=1.0)
    operation_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    unresolved_statements: int = Field(default=0, ge=0)
    unassigned_blocks: int = Field(default=0, ge=0)


def _ratio(total: int, represented: int | None = None) -> float | None:
    if total == 0:
        return None
    value = represented if represented is not None else total
    return max(0.0, min(1.0, value / total))


def compute_coverage(
    contract: ContractIR,
) -> ValidationCoverage:
    branches = sum(
        1
        for function in contract.functions
        for block in function.blocks
        if len(block.successor_ids) > 1
    )
    storage_write_count = len([item for item in contract.storage if item.access == "write"])
    analysis_metadata = contract.metadata.get("analysis", {})
    analysis_completeness = 1.0
    if isinstance(analysis_metadata, dict):
        value = analysis_metadata.get("completeness")
        if isinstance(value, (int, float)):
            analysis_completeness = max(0.0, min(1.0, float(value)))
    unresolved = sum(
        statement.truncated or statement.opcode.startswith("OP_")
        for block in contract.blocks
        for statement in block.statements
    )
    unassigned = len(contract.unassigned_block_ids)
    return ValidationCoverage(
        functions=_ratio(len(contract.functions), len(contract.functions)),
        storage_writes=_ratio(storage_write_count, storage_write_count),
        external_calls=_ratio(len(contract.external_calls), len(contract.external_calls)),
        events=_ratio(len(contract.events), len(contract.events)),
        reverts=_ratio(len(contract.reverts), len(contract.reverts)),
        branches=_ratio(branches),
        analysis_completeness=analysis_completeness,
        operation_coverage=_ratio(
            sum(len(block.statements) for block in contract.blocks),
            sum(len(block.statements) for block in contract.blocks),
        ),
        unresolved_statements=unresolved,
        unassigned_blocks=unassigned,
    )
