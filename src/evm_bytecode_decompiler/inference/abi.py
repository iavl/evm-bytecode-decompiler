from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..models.ir import ContractIR, FunctionIR


class SignatureCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature: str
    source: str
    confidence: float = Field(ge=0.0, le=1.0)


class InferredFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function_id: str
    selector: str | None
    name: str
    arguments: list[str] = Field(default_factory=list)
    returns: list[str] = Field(default_factory=list)
    candidates: list[SignatureCandidate] = Field(default_factory=list)


class InferredABI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    functions: list[InferredFunction]


def _argument_names(function: FunctionIR) -> list[str]:
    loads = sum(
        1
        for block in function.blocks
        for statement in block.statements
        if statement.opcode == "CALLDATALOAD"
    )
    return [f"arg{index}" for index in range(min(loads, 32))]


def infer_abi(
    contract: ContractIR,
    signatures: Mapping[str, Sequence[SignatureCandidate | str]] | None = None,
) -> InferredABI:
    inferred: list[InferredFunction] = []
    for function in contract.functions:
        selector = function.selector
        raw_candidates = signatures.get(selector, ()) if signatures and selector else ()
        candidates = [
            item
            if isinstance(item, SignatureCandidate)
            else SignatureCandidate(signature=item, source="signature_db", confidence=0.98)
            for item in raw_candidates
        ]
        name = f"func_{selector}" if selector else "fallback"
        arguments = _argument_names(function)
        if candidates:
            signature_name = candidates[0].signature.split("(", 1)[0]
            if signature_name and signature_name not in {"fallback", "receive"}:
                name = signature_name
        inferred.append(
            InferredFunction(
                function_id=function.id,
                selector=selector,
                name=name,
                arguments=arguments,
                candidates=candidates,
            )
        )
    return InferredABI(functions=inferred)
