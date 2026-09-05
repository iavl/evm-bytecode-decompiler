import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from ..config import AppConfig, load_config
from ..errors import ArtifactError, BackendUnavailableError, GigahorseAnalysisError
from ..gigahorse.docker import DockerGigahorseRunner
from ..gigahorse.relations import load_relations
from ..gigahorse.runner import BuiltinRunner, GigahorseResult, LocalGigahorseRunner
from ..inference.abi import InferredABI, infer_abi
from ..inference.proxies import detect_proxy
from ..inference.storage import StorageLayoutEntry, infer_storage_layout
from ..input.normalize import normalize_target
from ..ir.builder import build_contract_ir
from ..models.evidence import EvidenceSource
from ..models.input import NormalizedBytecode
from ..models.ir import ContractIR
from ..synthesis.pseudocode import render_contract, render_evidence_map, render_storage_layout
from ..validation.coverage import ValidationCoverage, compute_coverage
from ..validation.report import render_report
from ..validation.structural import validate_structure
from .artifacts import artifact_hash, load_abi, load_contract, load_storage, validate_manifest
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


RUN_SCHEMA_VERSION = 3


def _client_path(config: AppConfig) -> Path:
    configured = Path(config.gigahorse.client)
    if configured.is_absolute() and configured.is_file():
        return configured
    candidates = [
        (Path.cwd() / configured).resolve(),
        (Path(__file__).resolve().parents[1] / "gigahorse" / "client" / configured.name),
    ]
    return next((item for item in candidates if item.is_file()), candidates[0])


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _mark_failed(run_dir: Path, fingerprint: str, error: Exception) -> None:
    _write_json(
        run_dir / "run.json",
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "status": "failed",
            "fingerprint": fingerprint,
            "error": str(error),
        },
    )


def _fingerprint(
    normalized: NormalizedBytecode,
    config: AppConfig,
    *,
    selected_backend: str | None = None,
) -> str:
    metadata = normalized.metadata.model_dump(mode="json")
    client = _client_path(config)
    client_digest = artifact_hash(client) if client.is_file() else "missing"
    value = {
        "schema_version": RUN_SCHEMA_VERSION,
        "input": metadata,
        "runtime_sha256": metadata["bytecode_sha256"],
        "analysis_sha256": hashlib.sha256(normalized.code).hexdigest(),
        "gigahorse": {
            "backend": config.gigahorse.backend,
            "selected_backend": selected_backend or "unresolved",
            "executable": config.gigahorse.executable,
            "client": config.gigahorse.client,
            "commit": config.gigahorse.commit,
            "image": config.gigahorse.image,
            "toolchain_dir": str(config.gigahorse.toolchain_dir),
            "client_sha256": client_digest,
        },
    }
    material = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(material).hexdigest()


def _runner_name(runner: object) -> str:
    if isinstance(runner, DockerGigahorseRunner):
        return "docker"
    if isinstance(runner, LocalGigahorseRunner):
        return "local"
    if isinstance(runner, BuiltinRunner):
        return "builtin"
    return runner.__class__.__name__.lower()


def _resume_result(run_dir: Path, fingerprint: str) -> DecompileResult | None:
    manifest = run_dir / "run.json"
    required = (
        manifest,
        run_dir / "ir" / "contract.json",
        run_dir / "ir" / "schema_version",
        run_dir / "gigahorse" / "facts" / "schema.json",
        run_dir / "output" / "abi.inferred.json",
        run_dir / "output" / "storage.layout.json",
        run_dir / "output" / "decompiled.sol",
        run_dir / "output" / "evidence-map.json",
        run_dir / "output" / "report.md",
    )
    if not all(path.is_file() for path in required):
        return None
    try:
        validate_manifest(run_dir, fingerprint=fingerprint)
        contract = load_contract(run_dir)
        abi = load_abi(run_dir)
        storage = load_storage(run_dir)
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
            backend=str(results.get("backend", "cached")),
            completeness=cast(
                Literal["full", "partial", "unknown"],
                str(results.get("completeness", "unknown")),
            ),
        )
        if gigahorse.status in {"timeout", "error"}:
            return None
        return DecompileResult(
            run_dir,
            contract,
            abi,
            storage,
            compute_coverage(contract),
            gigahorse,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _runner(config: AppConfig) -> LocalGigahorseRunner | DockerGigahorseRunner | BuiltinRunner:
    gh = config.gigahorse
    client = _client_path(config)
    backend = gh.backend.lower()
    if backend not in {"auto", "local", "docker", "builtin"}:
        raise BackendUnavailableError(f"unknown Gigahorse backend: {gh.backend}")
    if backend == "builtin":
        return BuiltinRunner()
    if backend in {"local", "docker"} and not client.is_file():
        raise BackendUnavailableError(f"Gigahorse client file is missing: {client}")
    if backend == "docker" and not gh.image:
        raise BackendUnavailableError("docker backend requires a digest-pinned image")
    if backend in {"docker", "auto"} and gh.image:
        try:
            return DockerGigahorseRunner(
                gh.image, timeout_seconds=gh.timeout_seconds, client=client
            )
        except ValueError as exc:
            raise BackendUnavailableError(str(exc)) from exc
    if backend in {"local", "auto"} and shutil.which(gh.executable):
        return LocalGigahorseRunner(
            executable=gh.executable,
            client=client,
            timeout_seconds=gh.timeout_seconds,
            commit=gh.commit,
            toolchain_dir=gh.toolchain_dir,
        )
    if backend in {"local", "auto"} and shutil.which("souffle"):
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
    if backend == "local":
        raise BackendUnavailableError("local Gigahorse and Soufflé are not available")
    return BuiltinRunner()


def decompile(
    target: str,
    *,
    output_dir: Path | None = None,
    rpc_url: str | None = None,
    chain: str | None = None,
    block: int | str | None = None,
    config: AppConfig | None = None,
    use_ai: bool | None = None,
    resume: bool = False,
    backend: str | None = None,
) -> DecompileResult:
    """Run only deterministic analysis; ``use_ai`` remains a deprecated no-op."""
    del use_ai
    app_config = config or load_config()
    if backend is not None:
        if backend not in {"auto", "local", "docker", "builtin"}:
            raise BackendUnavailableError(f"unknown Gigahorse backend: {backend}")
        app_config = replace(
            app_config,
            gigahorse=replace(app_config.gigahorse, backend=backend),
        )
    resolved_rpc = rpc_url or (app_config.rpc.get(chain) if chain else None)
    normalized = normalize_target(
        target,
        rpc_url=resolved_rpc,
        chain=chain,
        block=block,
    )
    selected_runner = _runner(app_config)
    identity = _fingerprint(
        normalized,
        app_config,
        selected_backend=_runner_name(selected_runner),
    )
    run_dir = output_dir or app_config.output.root / (
        f"{normalized.metadata.bytecode_sha256[:16]}-{identity[:12]}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        cached = _resume_result(run_dir, identity)
        if cached is not None:
            return cached
        if any(run_dir.iterdir()):
            raise ArtifactError(
                "cannot resume: saved run is incomplete or has a different identity"
            )
    elif any(run_dir.iterdir()):
        raise ArtifactError(
            f"output directory is not empty: {run_dir}; use --resume for the matching run"
        )
    _write_json(
        run_dir / "run.json",
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "status": "running",
            "fingerprint": identity,
            "input": normalized.metadata.model_dump(mode="json"),
        },
    )
    context = PipelineContext(run_dir)
    context.mark(Stage.INPUT, "pass", bytecode_size=normalized.metadata.bytecode_size)
    input_dir = run_dir / "input"
    input_dir.mkdir(exist_ok=True)
    (input_dir / "runtime.hex").write_text(normalized.code.hex() + "\n", encoding="ascii")
    (input_dir / "analysis.hex").write_text(normalized.code.hex() + "\n", encoding="ascii")
    _write_json(input_dir / "metadata.json", normalized.metadata.model_dump(mode="json"))

    gigahorse_dir = run_dir / "gigahorse"
    try:
        result = selected_runner.run(
            normalized.code,
            gigahorse_dir,
            sha256=normalized.metadata.bytecode_sha256,
        )
    except Exception as exc:
        _mark_failed(run_dir, identity, exc)
        raise
    _write_json(
        gigahorse_dir / "results.json",
        {
            "status": result.effective_status,
            "version": result.version,
            "commit": result.commit,
            "warnings": result.warnings,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
            "backend": result.backend,
            "completeness": result.completeness,
        },
    )
    context.mark(Stage.GIGAHORSE, result.effective_status, duration_ms=result.duration_ms)
    if result.status in {"timeout", "error"}:
        message = "; ".join(result.errors) or "Gigahorse analysis failed"
        error = GigahorseAnalysisError(message)
        _mark_failed(run_dir, identity, error)
        raise error
    if result.backend in {"local", "docker"} and result.completeness == "partial":
        error = GigahorseAnalysisError(
            "; ".join(result.errors or result.warnings)
            or "Gigahorse produced an incomplete relation workspace"
        )
        _mark_failed(run_dir, identity, error)
        raise error

    try:
        relations = load_relations(result.relations_dir)
    except (OSError, ValueError) as exc:
        error = GigahorseAnalysisError(f"invalid Gigahorse relation workspace: {exc}")
        _mark_failed(run_dir, identity, error)
        raise error from exc
    source = EvidenceSource.BYTECODE if result.backend == "builtin" else EvidenceSource.GIGAHORSE
    proxy = detect_proxy(normalized.code)
    try:
        contract = build_contract_ir(
            relations,
            bytecode_sha256=normalized.metadata.bytecode_sha256,
            bytecode_size=normalized.metadata.bytecode_size,
            metadata={
                "input": normalized.metadata.model_dump(mode="json"),
                "proxy": proxy.model_dump(mode="json"),
                "analysis_bytecode_size": len(normalized.code),
                "analysis": {
                    "backend": result.backend,
                    "completeness": 1.0 if result.completeness == "full" else 0.5,
                    "warnings": result.warnings,
                },
            },
            evidence_source=source,
        )
    except Exception as exc:
        _mark_failed(run_dir, identity, exc)
        raise
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
    (ir_dir / "schema_version").write_text("2\n", encoding="ascii")
    output_dir_path = run_dir / "output"
    output_dir_path.mkdir(exist_ok=True)
    (output_dir_path / "decompiled.sol").write_text(
        render_contract(contract, abi, storage), encoding="utf-8"
    )
    _write_json(output_dir_path / "abi.inferred.json", abi.model_dump(mode="json"))
    (output_dir_path / "storage.layout.json").write_text(
        render_storage_layout(storage), encoding="utf-8"
    )
    (output_dir_path / "evidence-map.json").write_text(
        render_evidence_map(contract, abi), encoding="utf-8"
    )

    try:
        warnings = validate_structure(contract)
    except Exception as exc:
        _mark_failed(run_dir, identity, exc)
        raise
    coverage = compute_coverage(contract)
    context.mark(Stage.VALIDATION, "pass_with_warnings" if warnings else "pass", warnings=warnings)
    (output_dir_path / "report.md").write_text(
        render_report(normalized, contract, abi, storage, coverage, result),
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
    artifacts = {
        str(path.relative_to(run_dir)): artifact_hash(path)
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path != run_dir / "run.json"
    }
    _write_json(
        run_dir / "run.json",
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "status": "complete",
            "fingerprint": identity,
            "identity": {
                "runtime_sha256": normalized.metadata.bytecode_sha256,
                "analysis_sha256": hashlib.sha256(normalized.code).hexdigest(),
                "client_sha256": (
                    artifact_hash(_client_path(app_config))
                    if _client_path(app_config).is_file()
                    else "missing"
                ),
            },
            "run_dir": str(run_dir),
            "input": normalized.metadata.model_dump(mode="json"),
            "bytecode_sha256": normalized.metadata.bytecode_sha256,
            "stages": context.stages,
            "coverage": coverage.model_dump(mode="json"),
            "backend": {
                "name": result.backend,
                "version": result.version,
                "commit": result.commit,
                "completeness": result.completeness,
            },
            "artifacts": artifacts,
        },
    )
    return DecompileResult(run_dir, contract, abi, storage, coverage, result)
