from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import EvidenceRef


class ExpressionIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    args: list["ExpressionIR"] = Field(default_factory=list)
    value: int | str | None = None
    name: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def reject_float_constants(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("IR expressions cannot contain floating-point values")
        return value


class ValueIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type_hint: str | None = None


class FixedSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["fixed_slot"] = "fixed_slot"
    slot: int = Field(ge=0)


class MappingSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mapping"] = "mapping"
    base_slot: int = Field(ge=0)
    key: ExpressionIR


class NestedMappingSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["nested_mapping"] = "nested_mapping"
    base_slot: int = Field(ge=0)
    keys: list[ExpressionIR] = Field(min_length=2)


class DynamicArraySlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dynamic_array"] = "dynamic_array"
    base_slot: int = Field(ge=0)
    index: ExpressionIR


class SymbolicSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["symbolic"] = "symbolic"
    expression: ExpressionIR


StorageLocation = Annotated[
    FixedSlot | MappingSlot | NestedMappingSlot | DynamicArraySlot | SymbolicSlot,
    Field(discriminator="kind"),
]


class StatementIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    block_id: str
    pc: int = Field(ge=0)
    opcode: str
    operand: int | None = Field(default=None, ge=0)
    uses: list[str] = Field(default_factory=list)
    defines: list[str] = Field(default_factory=list)
    expression: ExpressionIR | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class StorageAccessIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    access: Literal["read", "write"]
    location: StorageLocation
    statement_id: str
    value: ExpressionIR | None = None
    result_variable: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class CallIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    call_type: Literal[
        "call",
        "staticcall",
        "delegatecall",
        "callcode",
        "create",
        "create2",
        "selfdestruct",
    ]
    statement_id: str
    target: ExpressionIR | None = None
    value: ExpressionIR | None = None
    input: ExpressionIR | None = None
    output: ExpressionIR | None = None
    success: ExpressionIR | None = None
    result_variable: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class EventIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement_id: str
    topics: list[ExpressionIR] = Field(default_factory=list, max_length=4)
    data: ExpressionIR | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class RevertIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["revert", "invalid"]
    statement_id: str
    condition: ExpressionIR | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class BasicBlockIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    pc: int = Field(ge=0)
    function_id: str
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    branch_condition: ExpressionIR | None = None
    statements: list[StatementIR] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_edges(self) -> "BasicBlockIR":
        if len(self.successor_ids) != len(set(self.successor_ids)):
            raise ValueError(f"duplicate successor in block {self.id}")
        if len(self.predecessor_ids) != len(set(self.predecessor_ids)):
            raise ValueError(f"duplicate predecessor in block {self.id}")
        return self


class FunctionIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    selector: str | None = None
    entry_block: str
    blocks: list[BasicBlockIR] = Field(min_length=1)
    arguments: list[ValueIR] = Field(default_factory=list)
    returns: list[ValueIR] = Field(default_factory=list)
    external_calls: list[CallIR] = Field(default_factory=list)
    storage_reads: list[StorageAccessIR] = Field(default_factory=list)
    storage_writes: list[StorageAccessIR] = Field(default_factory=list)
    events: list[EventIR] = Field(default_factory=list)
    reverts: list[RevertIR] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_blocks(self) -> "FunctionIR":
        ids = {block.id for block in self.blocks}
        if len(ids) != len(self.blocks):
            raise ValueError(f"duplicate block in function {self.id}")
        if self.entry_block not in ids:
            raise ValueError(f"unknown entry block {self.entry_block}")
        if any(edge not in ids for block in self.blocks for edge in block.successor_ids):
            raise ValueError(f"function {self.id} has an edge to an unknown block")
        return self


class ContractIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    bytecode_sha256: str
    bytecode_size: int = Field(ge=1)
    metadata: dict[str, object] = Field(default_factory=dict)
    functions: list[FunctionIR] = Field(min_length=1)
    storage: list[StorageAccessIR] = Field(default_factory=list)
    external_calls: list[CallIR] = Field(default_factory=list)
    events: list[EventIR] = Field(default_factory=list)
    reverts: list[RevertIR] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids_and_membership(self) -> "ContractIR":
        function_ids = [function.id for function in self.functions]
        if len(function_ids) != len(set(function_ids)):
            raise ValueError("function IDs must be unique")
        statement_ids: list[str] = []
        for function in self.functions:
            statement_ids.extend(
                statement.id for block in function.blocks for statement in block.statements
            )
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("statement IDs must be unique")
        return self


ExpressionIR.model_rebuild()
