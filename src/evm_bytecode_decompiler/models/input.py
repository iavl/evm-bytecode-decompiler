from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class InputKind(StrEnum):
    RAW = "raw"
    FILE = "file"
    ADDRESS = "address"


class MetadataTrailer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(ge=0)
    length: int = Field(gt=0)
    codec: str = "cbor"


class InputMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: InputKind
    target: str
    chain: str | None = None
    block: str | None = None
    bytecode_sha256: str
    bytecode_size: int = Field(ge=1)
    metadata_trailer: MetadataTrailer | None = None


@dataclass(frozen=True)
class NormalizedBytecode:
    """Exact canonical runtime bytes plus the optional analysis view."""

    code: bytes
    analysis_code: bytes
    metadata: InputMetadata
