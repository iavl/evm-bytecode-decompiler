from pathlib import Path

from benchmarks.metrics import deterministic_metrics, render_benchmark_report
from benchmarks.runner import CONTRACTS, fixture_manifest

from evm_bytecode_decompiler.gigahorse.builtin import build_builtin_relations
from evm_bytecode_decompiler.ir.builder import build_contract_ir
from evm_bytecode_decompiler.models.evidence import EvidenceSource


def test_benchmark_manifest_has_twenty_source_fixtures() -> None:
    manifest = fixture_manifest()
    assert len(manifest) >= 20
    assert len({item["name"] for item in manifest}) == len(manifest)
    assert all((CONTRACTS / item["source"]).is_file() for item in manifest)


def test_benchmark_metrics_are_deterministic() -> None:
    fixture = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"
    code = bytes.fromhex(fixture.read_text(encoding="ascii").strip())
    contract = build_contract_ir(
        build_builtin_relations(code),
        bytecode_sha256="a" * 64,
        bytecode_size=len(code),
        evidence_source=EvidenceSource.BYTECODE,
    )
    metrics = deterministic_metrics(contract)
    report = render_benchmark_report([{"name": "fixture", "status": "ok", "metrics": metrics}])
    assert metrics["functions"] == 2
    assert "Successful fixtures: `1/1`" in report
