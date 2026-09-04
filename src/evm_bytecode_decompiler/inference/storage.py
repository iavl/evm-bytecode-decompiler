from pydantic import BaseModel, ConfigDict, Field

from ..models.evidence import EvidenceSource, SemanticOrigin
from ..models.ir import (
    ContractIR,
    DynamicArraySlot,
    FixedSlot,
    MappingSlot,
    NestedMappingSlot,
    StorageAccessIR,
)


class StorageLayoutEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: str
    slot: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    origin: str
    evidence: list[str]


def _entry(access: StorageAccessIR) -> StorageLayoutEntry:
    location = access.location
    if isinstance(location, FixedSlot):
        return StorageLayoutEntry(
            id=f"slot_{location.slot}",
            name=f"storage_{location.slot}",
            kind=location.kind,
            slot=location.slot,
            confidence=1.0,
            origin=SemanticOrigin.DETERMINISTIC.value,
            evidence=[access.id],
        )
    if isinstance(location, MappingSlot):
        return StorageLayoutEntry(
            id=f"mapping_{location.base_slot}",
            name=f"mapping_{location.base_slot}",
            kind=location.kind,
            slot=location.base_slot,
            confidence=0.80,
            origin=EvidenceSource.HEURISTIC.value,
            evidence=[access.id],
        )
    if isinstance(location, NestedMappingSlot):
        return StorageLayoutEntry(
            id=f"nested_mapping_{location.base_slot}",
            name=f"mapping_{location.base_slot}_nested",
            kind=location.kind,
            slot=location.base_slot,
            confidence=0.80,
            origin=EvidenceSource.HEURISTIC.value,
            evidence=[access.id],
        )
    if isinstance(location, DynamicArraySlot):
        return StorageLayoutEntry(
            id=f"array_{location.base_slot}",
            name=f"array_{location.base_slot}",
            kind=location.kind,
            slot=location.base_slot,
            confidence=0.80,
            origin=EvidenceSource.HEURISTIC.value,
            evidence=[access.id],
        )
    return StorageLayoutEntry(
        id=access.id,
        name=f"symbolic_{access.id}",
        kind=location.kind,
        confidence=0.40,
        origin=EvidenceSource.HEURISTIC.value,
        evidence=[access.id],
    )


def infer_storage_layout(contract: ContractIR) -> list[StorageLayoutEntry]:
    by_id: dict[str, StorageLayoutEntry] = {}
    for access in contract.storage:
        item = _entry(access)
        by_id.setdefault(item.id, item)
    return sorted(by_id.values(), key=lambda item: (item.slot is None, item.slot or 0, item.id))
