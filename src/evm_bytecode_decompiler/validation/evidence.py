from ..models.ir import ContractIR


def evidence_ids(contract: ContractIR) -> set[str]:
    ids: set[str] = set()
    for statement in contract.statements:
        ids.add(statement.id)
        ids.update(item.fact_id for item in statement.evidence if item.fact_id)
    for block in contract.blocks:
        ids.update(item.fact_id for item in block.evidence if item.fact_id)
    for function in contract.functions:
        ids.update(item.fact_id for item in function.evidence if item.fact_id)
        for block in function.blocks:
            ids.update(item.fact_id for item in block.evidence if item.fact_id)
            for statement in block.statements:
                ids.update(item.fact_id for item in statement.evidence if item.fact_id)
        for item in (
            function.storage_reads
            + function.storage_writes
            + function.external_calls
            + function.events
            + function.reverts
        ):
            ids.add(item.id)
            ids.update(ref.fact_id for ref in item.evidence if ref.fact_id)
    return ids
