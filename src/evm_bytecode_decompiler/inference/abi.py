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
    argument_types: dict[str, str] = Field(default_factory=dict)
    returns: list[str] = Field(default_factory=list)
    return_types: dict[str, str] = Field(default_factory=dict)
    candidates: list[SignatureCandidate] = Field(default_factory=list)
    name_origin: str = "deterministic"
    name_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    argument_count_origin: str = "heuristic"
    argument_count_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    argument_type_confidence: dict[str, float] = Field(default_factory=dict)


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
    return [f"arg{index}" for index in range(loads)]


def _argument_types(function: FunctionIR, arguments: list[str]) -> dict[str, str]:
    """Use conservative uint256 defaults until a mask or call context proves more."""
    return {argument: "uint256" for argument in arguments}


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
        argument_types = _argument_types(function, arguments)
        returns = [item.id for item in function.returns]
        if candidates:
            signature_name = candidates[0].signature.split("(", 1)[0]
            if signature_name and signature_name not in {"fallback", "receive"}:
                name = signature_name
        name_origin = "external_signature" if candidates else "deterministic"
        name_confidence = candidates[0].confidence if candidates else 1.0
        argument_origin = "external_signature" if candidates else "heuristic"
        argument_confidence = candidates[0].confidence if candidates else 0.4
        inferred.append(
            InferredFunction(
                function_id=function.id,
                selector=selector,
                name=name,
                arguments=arguments,
                argument_types=argument_types,
                returns=returns,
                return_types={item: "uint256" for item in returns},
                candidates=candidates,
                name_origin=name_origin,
                name_confidence=name_confidence,
                argument_count_origin=argument_origin,
                argument_count_confidence=argument_confidence,
                argument_type_confidence={argument: argument_confidence for argument in arguments},
            )
        )
    return InferredABI(functions=inferred)
