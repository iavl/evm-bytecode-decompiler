from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSource(StrEnum):
    GIGAHORSE = "gigahorse"
    BYTECODE = "bytecode"
    RPC = "rpc"
    SIGNATURE_DB = "signature_db"
    HEURISTIC = "heuristic"


class SemanticOrigin(StrEnum):
    DETERMINISTIC = "deterministic"
    HEURISTIC = "heuristic"
    EXTERNAL_SIGNATURE = "external_signature"
    USER_SUPPLIED = "user_supplied"


class NamedSemantic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    origin: SemanticOrigin
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    schema_version: int = Field(default=1, ge=1)
    relation: str | None = None
    fact_id: str | None = None
    pc: int | None = Field(default=None, ge=0)
    block_id: str | None = None
    statement_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
