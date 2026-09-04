from ..models.ir import ContractIR


def validate_structure(contract: ContractIR) -> list[str]:
    """Return deterministic warnings; Pydantic has already enforced hard invariants."""
    warnings: list[str] = []
    for function in contract.functions:
        if any(not block.statements for block in function.blocks):
            warnings.append(f"{function.id} contains an empty basic block")
    return warnings
