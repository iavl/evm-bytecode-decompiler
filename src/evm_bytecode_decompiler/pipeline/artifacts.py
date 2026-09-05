import hashlib
import json
import re
from pathlib import Path

from ..inference.abi import InferredABI
from ..inference.storage import StorageLayoutEntry
from ..models.ir import ContractIR


def read_manifest(run_dir: Path) -> dict[str, object]:
    value = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("run manifest must be an object")
    return value


def artifact_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(run_dir: Path, *, fingerprint: str | None = None) -> dict[str, object]:
    manifest = read_manifest(run_dir)
    if manifest.get("schema_version") != 3:
        raise ValueError("unsupported or missing run manifest version")
    if manifest.get("status") != "complete":
        raise ValueError(f"run is not complete: {manifest.get('status', 'unknown')}")
    if fingerprint is not None and manifest.get("fingerprint") != fingerprint:
        raise ValueError("run identity does not match the requested input")
    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ValueError("run manifest has invalid artifact index")
    for relative, expected in artifacts.items():
        relative_path = Path(str(relative))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"artifact path escapes run directory: {relative}")
        path = run_dir / relative_path
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"artifact hash is invalid: {relative}")
        if not path.is_file() or artifact_hash(path) != expected:
            raise ValueError(f"artifact hash mismatch: {relative}")
    return manifest


def load_contract(run_dir: Path) -> ContractIR:
    contract = ContractIR.model_validate(
        json.loads((run_dir / "ir" / "contract.json").read_text(encoding="utf-8"))
    )
    if contract.schema_version != 2:
        raise ValueError("unsupported canonical IR schema version")
    return contract


def load_abi(run_dir: Path) -> InferredABI:
    return InferredABI.model_validate(
        json.loads((run_dir / "output" / "abi.inferred.json").read_text(encoding="utf-8"))
    )


def load_storage(run_dir: Path) -> list[StorageLayoutEntry]:
    value = json.loads((run_dir / "output" / "storage.layout.json").read_text(encoding="utf-8"))
    return [StorageLayoutEntry.model_validate(item) for item in value.get("storage", [])]
