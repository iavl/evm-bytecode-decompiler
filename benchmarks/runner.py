import json
from pathlib import Path
from typing import Any

from evm_bytecode_decompiler.config import AppConfig, OutputConfig
from evm_bytecode_decompiler.pipeline.decompile import decompile

from .compile import BenchmarkCompileError, compile_runtime
from .metrics import (
    deterministic_metrics,
    regression_failures,
    render_benchmark_report,
    write_results,
)

ROOT = Path(__file__).parent
CONTRACTS = ROOT / "contracts"
MANIFEST = ROOT / "manifest.json"


def fixture_manifest() -> list[dict[str, Any]]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("benchmark manifest must be a list")
    return value


def run_benchmark(
    output_dir: Path,
    *,
    compiler: str = "solc",
    strict: bool = False,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for item in fixture_manifest():
        name = item["name"]
        source = CONTRACTS / item["source"]
        record: dict[str, Any] = {
            "name": name,
            "source": item["source"],
            "status": "error",
            "expected": item.get("expected", {}),
        }
        try:
            runtime = compile_runtime(source, compiler=item.get("compiler", compiler))
            result = decompile(
                "0x" + runtime.hex(),
                output_dir=output_dir / name,
                config=AppConfig(output=OutputConfig(root=output_dir)),
            )
            record["status"] = "ok"
            record["runtime_sha256"] = result.contract.bytecode_sha256
            record["metrics"] = deterministic_metrics(result.contract)
        except (BenchmarkCompileError, OSError, ValueError) as exc:
            record["error"] = str(exc)
            message = str(exc).lower()
            if "could not run" in message or "requires different compiler version" in message:
                record["status"] = "unavailable"
        results.append(record)
    write_results(output_dir / "results.json", results)
    (output_dir / "report.md").write_text(render_benchmark_report(results), encoding="utf-8")
    if strict:
        failures = [
            f"{item['name']}: {item.get('error', 'fixture did not complete')}"
            for item in results
            if item["status"] != "ok"
        ]
        failures.extend(regression_failures(results))
        if failures:
            raise BenchmarkCompileError("benchmark strict mode failed: " + "; ".join(failures))
    return results


def report_benchmark(output_dir: Path) -> str:
    value = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    return render_benchmark_report(value.get("fixtures", []))
