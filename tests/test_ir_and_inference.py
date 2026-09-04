import hashlib
from pathlib import Path

from evm_bytecode_decompiler.gigahorse.builtin import build_builtin_relations
from evm_bytecode_decompiler.inference.abi import infer_abi
from evm_bytecode_decompiler.inference.proxies import detect_proxy
from evm_bytecode_decompiler.inference.storage import infer_storage_layout
from evm_bytecode_decompiler.ir.builder import build_contract_ir
from evm_bytecode_decompiler.ir.selectors import extract_public_selectors
from evm_bytecode_decompiler.models.evidence import EvidenceSource

FIXTURE = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"


def test_ir_preserves_functions_storage_calls_and_evidence() -> None:
    code = bytes.fromhex(FIXTURE.read_text(encoding="ascii").strip())
    digest = hashlib.sha256(code).hexdigest()
    contract = build_contract_ir(
        build_builtin_relations(code),
        bytecode_sha256=digest,
        bytecode_size=len(code),
        evidence_source=EvidenceSource.BYTECODE,
    )

    assert len(contract.functions) == 2
    assert contract.storage
    assert any(item.access == "write" for item in contract.storage)
    assert {item.call_type for item in contract.external_calls} == {"call"}
    assert contract.events and contract.reverts
    assert all(
        statement.evidence
        for function in contract.functions
        for block in function.blocks
        for statement in block.statements
    )

    abi = infer_abi(contract)
    layout = infer_storage_layout(contract)
    assert [item.selector for item in abi.functions] == ["0xa9059cbb", "0xdd62ed3e"]
    assert any(item.name == "storage_0" for item in layout)


def test_proxy_recognition_is_explicit() -> None:
    implementation_slot = bytes.fromhex(
        "360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
    )
    result = detect_proxy(b"\x7f" + implementation_slot)
    assert result.detected and result.kind == "eip1967"
    assert not detect_proxy(b"\x60\x00").detected


def test_selector_extraction_keeps_dispatch_destination() -> None:
    code = bytes.fromhex("63a9059cbb14601757" + "00" * 16)
    match = extract_public_selectors(code)[0]
    assert match.selector == "0xa9059cbb"
    assert match.destination_pc == 0x17
