from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FunctionSemanticAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function_id: str
    selector: str | None = None
    proposed_name: str | None = None
    name_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = ""
    argument_names: dict[str, str] = Field(default_factory=dict)
    argument_types: dict[str, str] = Field(default_factory=dict)
    storage_labels: dict[str, str] = Field(default_factory=dict)
    semantic_patterns: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    claimed_constants: list[str] = Field(default_factory=list)


class ContractSemanticReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_labels: dict[str, str] = Field(default_factory=dict)
    function_names: dict[str, str] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)
    patterns: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class PseudoArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type_name: str = "uint256"


class PseudoStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "assignment",
        "storage_read",
        "storage_write",
        "if",
        "require",
        "revert",
        "loop",
        "call",
        "delegatecall",
        "staticcall",
        "event",
        "return",
        "create",
        "create2",
        "unknown",
    ]
    target: str | None = None
    value: str | None = None
    condition: str | None = None
    body: list["PseudoStatement"] = Field(default_factory=list)
    call_type: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    unresolved: str | None = None

    @field_validator("call_type")
    @classmethod
    def validate_call_type(cls, value: str | None) -> str | None:
        if value is not None and value not in {
            "call",
            "staticcall",
            "delegatecall",
            "callcode",
            "create",
            "create2",
            "selfdestruct",
        }:
            raise ValueError(f"unsupported call type: {value}")
        return value


class PseudoFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function_id: str
    selector: str | None = None
    name: str
    arguments: list[PseudoArgument] = Field(default_factory=list)
    returns: list[PseudoArgument] = Field(default_factory=list)
    body: list[PseudoStatement] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class PseudoContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    functions: list[PseudoFunction] = Field(default_factory=list)
    storage_labels: dict[str, str] = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    missing_storage_writes: list[str] = Field(default_factory=list)
    missing_calls: list[str] = Field(default_factory=list)
    missing_events: list[str] = Field(default_factory=list)
    missing_reverts: list[str] = Field(default_factory=list)
    incorrect_constants: list[str] = Field(default_factory=list)
    unsupported_semantic_claims: list[str] = Field(default_factory=list)
    severity: Literal["pass", "warn", "fail"] = "pass"


PseudoStatement.model_rebuild()
