import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig, load_config
from ..errors import GigahorseAnalysisError
from ..gigahorse.docker import DockerGigahorseRunner
from ..gigahorse.relations import load_relations
from ..gigahorse.runner import BuiltinRunner, GigahorseResult, LocalGigahorseRunner
from ..inference.abi import InferredABI, infer_abi
from ..inference.proxies import detect_proxy
from ..inference.storage import StorageLayoutEntry, infer_storage_layout
from ..input.normalize import normalize_target
from ..ir.builder import build_contract_ir
from ..models.evidence import EvidenceSource
from ..models.ir import ContractIR
from ..synthesis.pseudocode import render_contract, render_evidence_map, render_storage_layout
from ..validation.coverage import ValidationCoverage, compute_coverage
from ..validation.report import render_report
from ..validation.structural import validate_structure
from .context import PipelineContext
from .stages import Stage


@dataclass(frozen=True)
class DecompileResult:
    run_dir: Path
    contract: ContractIR
    abi: InferredABI
    storage: list[StorageLayoutEntry]
    coverage: ValidationCoverage
    gigahorse: GigahorseResult


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _runner(
    config: AppConfig,
) -> LocalGigahorseRunner | DockerGigahorseRunner | BuiltinRunner:
    gh = config.gigahorse
    client = Path(gh.client)
    if not client.is_absolute():
        client = (Path.cwd() / client).resolve()
    if gh.backend == "docker" and gh.image:
        return DockerGigahorseRunner(gh.image, timeout_seconds=gh.timeout_seconds, client=client)
    if gh.backend == "local" and shutil.which(gh.executable):
        return LocalGigahorseRunner(
            executable=gh.executable,
            client=client,
            timeout_seconds=gh.timeout_seconds,
            commit=gh.commit,
        )
    return BuiltinRunner()


def decompile(
    target: str,
    *,
    output_dir: Path | None = None,
    rpc_url: str | None = None,
    chain: str | None = None,
    block: int | str | None = None,
    config: AppConfig | None = None,
) -> DecompileResult:
    app_config = config or load_config()
    resolved_rpc = rpc_url or (app_config.rpc.get(chain) if chain else None)
    normalized = normalize_target(
        target,
        rpc_url=resolved_rpc,
        chain=chain,
        block=block,
    )
    run_dir = output_dir or app_config.output.root / normalized.metadata.bytecode_sha256[:16]
    run_dir.mkdir(parents=True, exist_ok=True)
    context = PipelineContext(run_dir)
    context.mark(Stage.INPUT, "pass", bytecode_size=normalized.metadata.bytecode_size)
    input_dir = run_dir / "input"
    input_dir.mkdir(exist_ok=True)
    (input_dir / "runtime.hex").write_text(normalized.code.hex() + "\n", encoding="ascii")
    (input_dir / "analysis.hex").write_text(normalized.analysis_code.hex() + "\n", encoding="ascii")
    _write_json(input_dir / "metadata.json", normalized.metadata.model_dump(mode="json"))

    gigahorse_dir = run_dir / "gigahorse"
    result = _runner(app_config).run(
        normalized.analysis_code,
        gigahorse_dir,
        sha256=normalized.metadata.bytecode_sha256,
    )
    _write_json(
        gigahorse_dir / "results.json",
        {
            "status": result.status,
            "version": result.version,
            "commit": result.commit,
            "warnings": result.warnings,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        },
    )
    context.mark(Stage.GIGAHORSE, result.status, duration_ms=result.duration_ms)
    if result.status in {"timeout", "error"}:
        message = "; ".join(result.errors) or "Gigahorse analysis failed"
        raise GigahorseAnalysisError(message)

    relations = load_relations(result.relations_dir)
    source = EvidenceSource.BYTECODE if result.commit == "builtin" else EvidenceSource.GIGAHORSE
    proxy = detect_proxy(normalized.analysis_code)
    contract = build_contract_ir(
        relations,
        bytecode_sha256=normalized.metadata.bytecode_sha256,
        bytecode_size=normalized.metadata.bytecode_size,
        metadata={
            "input": normalized.metadata.model_dump(mode="json"),
            "proxy": proxy.model_dump(mode="json"),
            "analysis_bytecode_size": len(normalized.analysis_code),
        },
        evidence_source=source,
    )
    context.mark(Stage.IR_BUILD, "pass", functions=len(contract.functions))
    abi = infer_abi(contract)
    storage = infer_storage_layout(contract)
    context.mark(
        Stage.DETERMINISTIC_INFERENCE,
        "pass",
        selectors=len(abi.functions),
        storage=len(storage),
    )

    ir_dir = run_dir / "ir"
    _write_json(ir_dir / "contract.json", contract.model_dump(mode="json"))
    (ir_dir / "schema_version").write_text("1\n", encoding="ascii")
    output_dir_path = run_dir / "output"
    output_dir_path.mkdir(exist_ok=True)
    solidity = render_contract(contract, abi, storage)
    (output_dir_path / "decompiled.sol").write_text(solidity, encoding="utf-8")
    (output_dir_path / "decompiled.annotated.sol").write_text(solidity, encoding="utf-8")
    (output_dir_path / "storage.layout.json").write_text(
        render_storage_layout(storage), encoding="utf-8"
    )
    (output_dir_path / "evidence-map.json").write_text(
        render_evidence_map(contract, abi), encoding="utf-8"
    )

    warnings = validate_structure(contract)
    coverage = compute_coverage(contract)
    context.mark(Stage.VALIDATION, "pass_with_warnings" if warnings else "pass", warnings=warnings)
    (output_dir_path / "report.md").write_text(
        render_report(normalized, contract, abi, storage, coverage, result), encoding="utf-8"
    )
    context.mark(Stage.REPORT, "pass")
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    if result.errors or warnings:
        errors = [{"kind": "gigahorse", "message": item} for item in result.errors]
        errors.extend({"kind": "validation", "message": item} for item in warnings)
        (logs_dir / "errors.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in errors), encoding="utf-8"
        )
    else:
        (logs_dir / "errors.jsonl").write_text("", encoding="utf-8")
    (logs_dir / "pipeline.log").write_text(
        "".join(f"[{name}] {details['status']}\n" for name, details in context.stages.items()),
        encoding="utf-8",
    )
    _write_json(
        run_dir / "run.json",
        {
            "schema_version": 1,
            "bytecode_sha256": normalized.metadata.bytecode_sha256,
            "run_dir": str(run_dir),
            "stages": context.stages,
            "coverage": coverage.model_dump(mode="json"),
            "ai": {"enabled": False, "reason": "checkpoint stops before Phase 7"},
        },
    )
    return DecompileResult(run_dir, contract, abi, storage, coverage, result)
