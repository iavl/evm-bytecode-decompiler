from pathlib import Path

import pytest

from evm_bytecode_decompiler.config import AppConfig, GigahorseConfig, OutputConfig
from evm_bytecode_decompiler.errors import ArtifactError
from evm_bytecode_decompiler.gigahorse.builtin import build_builtin_relations
from evm_bytecode_decompiler.gigahorse.parser import disassemble
from evm_bytecode_decompiler.gigahorse.relations import load_relations
from evm_bytecode_decompiler.inference.abi import infer_abi
from evm_bytecode_decompiler.inference.storage import infer_storage_layout
from evm_bytecode_decompiler.input.normalize import normalize_bytecode
from evm_bytecode_decompiler.ir.builder import build_contract_ir
from evm_bytecode_decompiler.models.annotations import FunctionAnnotation
from evm_bytecode_decompiler.models.evidence import EvidenceSource
from evm_bytecode_decompiler.pipeline.decompile import decompile
from evm_bytecode_decompiler.synthesis.pseudocode import render_contract


def _contract(code: str):
    value = bytes.fromhex(code)
    return build_contract_ir(
        build_builtin_relations(value),
        bytecode_sha256="a" * 64,
        bytecode_size=len(value),
        evidence_source=EvidenceSource.BYTECODE,
    )


def test_builtin_stack_facts_handle_swap_and_truncated_push() -> None:
    relations = build_builtin_relations(bytes.fromhex("600160029055"))
    assert relations["StorageStore"][0][1] == "fixed:1"
    instruction = disassemble(bytes.fromhex("61aa"))[0]
    assert instruction.operand is None and instruction.truncated


def test_relation_csv_with_tabs_is_parsed_and_validated(tmp_path: Path) -> None:
    (tmp_path / "Block.csv").write_text("B_0000\n", encoding="utf-8")
    (tmp_path / "Statement.csv").write_text("S_0000\n", encoding="utf-8")
    (tmp_path / "StatementBlock.csv").write_text("S_0000\tB_0000\n", encoding="utf-8")
    assert load_relations(tmp_path)["StatementBlock"] == [("S_0000", "B_0000")]


def test_pipeline_analyzes_full_runtime_even_with_metadata_candidate(tmp_path: Path) -> None:
    runtime = "60a060005560015560000009"
    normalized = normalize_bytecode(runtime + "a10102" + "0003")
    assert normalized.metadata.metadata_trailer is not None
    config = AppConfig(
        gigahorse=GigahorseConfig(backend="builtin"),
        output=OutputConfig(root=tmp_path),
    )
    result = decompile(
        "0x" + runtime + "a10102" + "0003",
        output_dir=tmp_path / "run",
        config=config,
    )
    assert any(item.opcode == "SSTORE" for item in result.contract.statements)
    assert (tmp_path / "run" / "input" / "analysis.hex").read_text().strip() == (
        runtime + "a10102" + "0003"
    )


def test_resume_requires_matching_input_identity(tmp_path: Path) -> None:
    config = AppConfig(
        gigahorse=GigahorseConfig(backend="builtin"),
        output=OutputConfig(root=tmp_path),
    )
    decompile("0x6000", output_dir=tmp_path / "run", config=config)
    with pytest.raises(ArtifactError):
        decompile("0x6000", output_dir=tmp_path / "run", config=config, block=1, resume=True)


def test_annotations_can_rename_without_replacing_canonical_operations() -> None:
    contract = _contract("602a60005500")
    function = contract.functions[0]
    annotation = FunctionAnnotation(
        proposed_name="renamed",
        summary="writes one fixed storage slot",
        storage_labels={function.storage_writes[0].id: "balance"},
        evidence_refs=[function.storage_writes[0].id],
    )
    output = render_contract(
        contract,
        infer_abi(contract),
        infer_storage_layout(contract),
        annotations={function.id: annotation},
        annotated=True,
    )
    assert "function renamed" in output
    assert "balance =" in output
    assert "return 0;" not in output
