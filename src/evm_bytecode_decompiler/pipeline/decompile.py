import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from ..ai.pipeline import AIPipelineResult, run_ai_pipeline
from ..ai.provider import AIProvider, provider_from_environment
from ..cache.store import CacheStore
from ..config import AppConfig, load_config
from ..errors import AIProviderError, GigahorseAnalysisError
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
from .artifacts import load_abi, load_contract, load_storage, load_synthesis
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
    ai: AIPipelineResult | None = None


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resume_result(run_dir: Path, normalized_sha256: str) -> DecompileResult | None:
    manifest = run_dir / "run.json"
    required = (
        manifest,
        run_dir / "ir" / "contract.json",
        run_dir / "output" / "abi.inferred.json",
        run_dir / "output" / "storage.layout.json",
    )
    if not all(path.is_file() for path in required):
        return None
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if value.get("bytecode_sha256") != normalized_sha256:
            return None
        contract = load_contract(run_dir)
        abi = load_abi(run_dir)
        storage = load_storage(run_dir)
        pseudo = load_synthesis(run_dir)
        results = json.loads((run_dir / "gigahorse" / "results.json").read_text(encoding="utf-8"))
        status = str(results.get("status", "ok"))
        if status not in {"ok", "partial", "timeout", "error"}:
            return None
        gigahorse = GigahorseResult(
            status=cast(Literal["ok", "partial", "timeout", "error"], status),
            version=str(results.get("version", "cached")),
            commit=str(results.get("commit", "cached")),
            relations_dir=run_dir / "gigahorse" / "facts",
            warnings=[str(item) for item in results.get("warnings", [])],
            errors=[str(item) for item in results.get("errors", [])],
            duration_ms=int(results.get("duration_ms", 0)),
        )
        if gigahorse.status in {"timeout", "error"}:
            return None
        return DecompileResult(
            run_dir,
            contract,
            abi,
            storage,
            compute_coverage(contract, pseudo or None),
            gigahorse,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


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
            toolchain_dir=gh.toolchain_dir,
        )
    if gh.backend == "local" and shutil.which("souffle"):
        executable = gh.toolchain_dir / "gigahorse.py"
        functors = gh.toolchain_dir / "souffle-addon" / "libfunctors.so"
        if executable.is_file() and functors.is_file():
            return LocalGigahorseRunner(
                executable=str(executable),
                client=client,
                timeout_seconds=gh.timeout_seconds,
                commit=gh.commit,
                toolchain_dir=gh.toolchain_dir,
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
    use_ai: bool = True,
    provider: AIProvider | None = None,
    resume: bool = False,
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
    if resume:
        cached = _resume_result(run_dir, normalized.metadata.bytecode_sha256)
        if cached is not None:
            return cached
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

    ai_result: AIPipelineResult | None = None
    ai_warnings: list[str] = []
    if use_ai:
        active_provider = provider
        if active_provider is None:
            try:
                active_provider = provider_from_environment(
                    model=app_config.ai.model,
                    endpoint=app_config.ai.endpoint,
                    timeout=app_config.ai.timeout_seconds,
                )
            except AIProviderError as exc:
                ai_warnings.append(str(exc))
        if active_provider is None:
            ai_warnings.append("AI provider is not configured; deterministic output was retained.")
        else:
            try:
                ai_result = run_ai_pipeline(
                    contract,
                    abi,
                    storage,
                    provider=active_provider,
                    cache=CacheStore(app_config.ai.cache_dir),
                    max_concurrency=app_config.ai.max_concurrency,
                    temperature=app_config.ai.temperature,
                )
                ai_warnings.extend(ai_result.warnings)
                context.stages.update(
                    {
                        name: details
                        for name, details in ai_result.stages.items()
                        if name != Stage.VALIDATION.value
                    }
                )
            except (AIProviderError, ValueError, TypeError) as exc:
                ai_warnings.append(f"AI pipeline failed; deterministic output was retained: {exc}")
    if ai_result is None:
        for stage in (
            Stage.AI_FUNCTION_SEMANTICS,
            Stage.AI_RECONCILIATION,
            Stage.SYNTHESIS,
        ):
            context.mark(stage, "skipped", reason="--no-ai or provider unavailable")

    ir_dir = run_dir / "ir"
    _write_json(ir_dir / "contract.json", contract.model_dump(mode="json"))
    (ir_dir / "schema_version").write_text("1\n", encoding="ascii")
    output_dir_path = run_dir / "output"
    output_dir_path.mkdir(exist_ok=True)
    pseudo_functions = ai_result.accepted if ai_result else None
    solidity = render_contract(contract, abi, storage, pseudo_functions=pseudo_functions)
    (output_dir_path / "decompiled.sol").write_text(solidity, encoding="utf-8")
    (output_dir_path / "decompiled.annotated.sol").write_text(
        render_contract(
            contract,
            abi,
            storage,
            pseudo_functions=pseudo_functions,
            annotated=True,
        ),
        encoding="utf-8",
    )
    _write_json(output_dir_path / "abi.inferred.json", abi.model_dump(mode="json"))
    (output_dir_path / "storage.layout.json").write_text(
        render_storage_layout(storage), encoding="utf-8"
    )
    (output_dir_path / "evidence-map.json").write_text(
        render_evidence_map(
            contract,
            abi,
            annotations=ai_result.annotations if ai_result else None,
            pseudo_functions=pseudo_functions,
        ),
        encoding="utf-8",
    )

    warnings = validate_structure(contract)
    warnings.extend(ai_warnings)
    coverage = compute_coverage(contract, pseudo_functions)
    context.mark(Stage.VALIDATION, "pass_with_warnings" if warnings else "pass", warnings=warnings)
    (output_dir_path / "report.md").write_text(
        render_report(
            normalized,
            contract,
            abi,
            storage,
            coverage,
            result,
            ai_usage=(
                {"enabled": True, **ai_result.usage, "warnings": ai_warnings}
                if ai_result
                else {"enabled": False, "warnings": ai_warnings}
            ),
        ),
        encoding="utf-8",
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
            "ai": (
                {"enabled": True, **ai_result.usage, "warnings": ai_warnings}
                if ai_result
                else {"enabled": False, "warnings": ai_warnings}
            ),
        },
    )
    semantics_dir = run_dir / "semantics"
    _write_json(
        semantics_dir / "storage.json",
        {"storage": [item.model_dump(mode="json") for item in storage]},
    )
    if ai_result:
        for function_id, annotation in ai_result.annotations.items():
            _write_json(
                semantics_dir / "functions" / f"{function_id}.json",
                annotation.model_dump(mode="json"),
            )
        _write_json(
            semantics_dir / "contract.json",
            ai_result.reconciliation.semantics.model_dump(mode="json"),
        )
        _write_json(
            semantics_dir / "synthesis.json",
            {key: value.model_dump(mode="json") for key, value in ai_result.accepted.items()},
        )
        _write_json(
            semantics_dir / "reviews.json",
            {key: value.model_dump(mode="json") for key, value in ai_result.review.reviews.items()},
        )
        _write_json(semantics_dir / "ai_usage.json", {"enabled": True, **ai_result.usage})
    else:
        _write_json(
            semantics_dir / "contract.json",
            {"enabled": False, "reason": "AI provider unavailable or --no-ai"},
        )
        _write_json(semantics_dir / "ai_usage.json", {"enabled": False})
    return DecompileResult(run_dir, contract, abi, storage, coverage, result, ai_result)
