from ..errors import ValidationError
from ..models.ir import ContractIR


def validate_structure(contract: ContractIR) -> list[str]:
    """Validate ownership and references before a run is published."""
    warnings: list[str] = []
    canonical_blocks = {block.id: block for block in contract.blocks}
    canonical_statements = {statement.id: statement for statement in contract.statements}
    seen_effects: set[str] = set()
    for function in contract.functions:
        function_blocks = {block.id for block in function.blocks}
        if function.entry_block not in function_blocks:
            raise ValidationError(f"{function.id} entry block is not in its ownership set")
        if canonical_blocks and any(
            block_id not in canonical_blocks for block_id in function_blocks
        ):
            raise ValidationError(f"{function.id} references a block outside the canonical IR")
        if any(block.function_id not in {None, function.id} for block in function.blocks):
            raise ValidationError(f"{function.id} contains a block owned by another function")
        statement_ids = {
            statement.id for block in function.blocks for statement in block.statements
        }
        if canonical_statements and any(item not in canonical_statements for item in statement_ids):
            raise ValidationError(f"{function.id} references a statement outside the canonical IR")
        if any(
            edge not in function_blocks for block in function.blocks for edge in block.successor_ids
        ):
            raise ValidationError(f"{function.id} has a cross-function CFG edge")
        if any(not block.statements for block in function.blocks):
            warnings.append(f"{function.id} contains an empty basic block")
        for access in function.storage_reads + function.storage_writes:
            if access.statement_id not in statement_ids:
                raise ValidationError(f"{access.id} references an unknown statement")
            seen_effects.add(access.id)
        for call in function.external_calls:
            if call.statement_id not in statement_ids:
                raise ValidationError(f"{call.id} references an unknown statement")
            seen_effects.add(call.id)
        for event in function.events:
            if event.statement_id not in statement_ids:
                raise ValidationError(f"{event.id} references an unknown statement")
            seen_effects.add(event.id)
        for revert in function.reverts:
            if revert.statement_id not in statement_ids:
                raise ValidationError(f"{revert.id} references an unknown statement")
            seen_effects.add(revert.id)
    if canonical_blocks:
        for block in contract.blocks:
            if any(edge not in canonical_blocks for edge in block.successor_ids):
                raise ValidationError(f"block {block.id} has an unknown CFG successor")
            if any(statement.block_id != block.id for statement in block.statements):
                raise ValidationError(f"block {block.id} contains a statement with the wrong owner")
    for access in contract.storage:
        if access.id not in seen_effects:
            warnings.append(f"unassigned storage effect {access.id}")
    for call in contract.external_calls:
        if call.id not in seen_effects:
            warnings.append(f"unassigned call effect {call.id}")
    return warnings
