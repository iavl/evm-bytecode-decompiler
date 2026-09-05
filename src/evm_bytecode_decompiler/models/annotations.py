from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FunctionAnnotation(BaseModel):
    """Advisory semantic labels for one canonical function."""

    model_config = ConfigDict(extra="forbid")

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

    @field_validator(
        "proposed_name",
        "summary",
        "semantic_patterns",
        "uncertainties",
        "evidence_refs",
        "argument_names",
        "argument_types",
        "storage_labels",
        mode="before",
    )
    @classmethod
    def reject_non_strings(cls, value: object) -> object:
        if isinstance(value, dict) and any(
            not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
        ):
            raise ValueError("annotation mappings must contain strings")
        if isinstance(value, list) and any(not isinstance(item, str) for item in value):
            raise ValueError("annotation lists must contain strings")
        if value is not None and not isinstance(value, (str, dict, list)):
            raise ValueError("annotation text fields must contain strings")
        return value


class ContractAnnotation(BaseModel):
    """Advisory contract-wide semantic labels."""

    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    roles: dict[str, str] = Field(default_factory=dict)
    patterns: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class AnnotationProposal(BaseModel):
    """Strict, run-bound semantic overlay supplied by the active agent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_fingerprint: str = Field(min_length=64, max_length=64)
    contract: ContractAnnotation = Field(default_factory=ContractAnnotation)
    functions: dict[str, FunctionAnnotation] = Field(default_factory=dict)
    storage_labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("run_fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        if any(character not in "0123456789abcdef" for character in value.lower()):
            raise ValueError("run_fingerprint must be a SHA-256 hex digest")
        return value.lower()
