from ..models.ir import ContractIR


def evidence_ids(contract: ContractIR) -> set[str]:
    ids: set[str] = set()
    for function in contract.functions:
        ids.update(item.fact_id for item in function.evidence if item.fact_id)
        for block in function.blocks:
            ids.update(item.fact_id for item in block.evidence if item.fact_id)
            for statement in block.statements:
                ids.update(item.fact_id for item in statement.evidence if item.fact_id)
    return ids
