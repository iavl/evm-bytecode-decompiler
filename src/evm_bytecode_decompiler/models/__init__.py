"""Versioned input and canonical IR models."""

from .annotations import AnnotationProposal, ContractAnnotation, FunctionAnnotation
from .evidence import EvidenceRef, EvidenceSource, NamedSemantic, SemanticOrigin
from .input import InputKind, InputMetadata, MetadataTrailer, NormalizedBytecode
from .ir import (
    BasicBlockIR,
    CallIR,
    ContractIR,
    DynamicArraySlot,
    EventIR,
    ExpressionIR,
    FixedSlot,
    FunctionIR,
    MappingSlot,
    NestedMappingSlot,
    RevertIR,
    StatementIR,
    StorageAccessIR,
    StorageLocation,
    SymbolicSlot,
    ValueIR,
)

__all__ = [
    "AnnotationProposal",
    "BasicBlockIR",
    "CallIR",
    "ContractAnnotation",
    "ContractIR",
    "DynamicArraySlot",
    "EventIR",
    "EvidenceRef",
    "EvidenceSource",
    "NamedSemantic",
    "ExpressionIR",
    "FixedSlot",
    "FunctionAnnotation",
    "FunctionIR",
    "InputKind",
    "InputMetadata",
    "MappingSlot",
    "MetadataTrailer",
    "NestedMappingSlot",
    "NormalizedBytecode",
    "RevertIR",
    "StatementIR",
    "StorageAccessIR",
    "StorageLocation",
    "SymbolicSlot",
    "SemanticOrigin",
    "ValueIR",
]
