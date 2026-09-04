import json
from pathlib import Path

from ..ai.schemas import PseudoFunction
from ..inference.abi import InferredABI
from ..inference.storage import StorageLayoutEntry
from ..models.ir import ContractIR


def load_contract(run_dir: Path) -> ContractIR:
    return ContractIR.model_validate(
        json.loads((run_dir / "ir" / "contract.json").read_text(encoding="utf-8"))
    )


def load_abi(run_dir: Path) -> InferredABI:
    return InferredABI.model_validate(
        json.loads((run_dir / "output" / "abi.inferred.json").read_text(encoding="utf-8"))
    )


def load_storage(run_dir: Path) -> list[StorageLayoutEntry]:
    value = json.loads((run_dir / "output" / "storage.layout.json").read_text(encoding="utf-8"))
    return [StorageLayoutEntry.model_validate(item) for item in value.get("storage", [])]


def load_synthesis(run_dir: Path) -> dict[str, PseudoFunction]:
    path = run_dir / "semantics" / "synthesis.json"
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return {}
    return {key: PseudoFunction.model_validate(item) for key, item in value.items()}
