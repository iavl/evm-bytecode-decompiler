import json
import re
import shutil
import subprocess
from pathlib import Path

import typer
from benchmarks.compile import BenchmarkCompileError
from benchmarks.runner import report_benchmark, run_benchmark

from . import __version__
from .cache.store import CacheStore
from .config import load_config
from .errors import DecompilerError
from .pipeline.artifacts import (
    load_abi,
    load_contract,
    load_storage,
    load_synthesis,
    validate_manifest,
)
from .pipeline.decompile import decompile as run_decompile
from .synthesis.pseudocode import render_contract
from .validation.coverage import compute_coverage
from .validation.structural import validate_structure

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command("decompile")
def decompile_command(
    target: str = typer.Argument(..., metavar="TARGET"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Run deterministic phases only."),
    rpc_url: str | None = typer.Option(None, "--rpc-url"),
    chain: str | None = typer.Option(None, "--chain"),
    block: str | None = typer.Option(None, "--block", help="Explicit block number or block tag."),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    resume: bool = typer.Option(
        False, "--resume", help="Reuse valid saved deterministic and AI artifacts."
    ),
    backend: str | None = typer.Option(
        None, "--backend", help="Require auto, local, docker, or builtin analysis."
    ),
) -> None:
    """Decompile raw bytecode, a .hex file, or an address."""
    try:
        result = run_decompile(
            target,
            output_dir=output_dir,
            rpc_url=rpc_url,
            chain=chain,
            block=block,
            use_ai=not no_ai,
            resume=resume,
            backend=backend,
        )
    except (DecompilerError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.run_dir)


@app.command("analyze")
def analyze_command(
    target: str = typer.Argument(..., metavar="TARGET"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    backend: str | None = typer.Option(
        None, "--backend", help="Require auto, local, docker, or builtin analysis."
    ),
) -> None:
    """Run the deterministic analysis checkpoint."""
    try:
        result = run_decompile(target, output_dir=output_dir, use_ai=False, backend=backend)
    except (DecompilerError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.run_dir)


@app.command()
def doctor() -> None:
    """Check the configured analysis environment."""
    config = load_config()
    executable = config.gigahorse.executable
    found = shutil.which(executable)
    toolchain = config.gigahorse.toolchain_dir
    script = toolchain / "gigahorse.py"
    functors = toolchain / "souffle-addon" / "libfunctors.so"
    pin = "not present"
    if toolchain.is_dir():
        result = subprocess.run(
            ["git", "-C", str(toolchain), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            pin = result.stdout.strip()
    typer.echo("python: ok")
    typer.echo("builtin_lifter: ok")
    local_ready = found or (script.is_file() and shutil.which("souffle") and functors.is_file())
    typer.echo(f"gigahorse_pin: {pin}")
    typer.echo(f"gigahorse_local: {'ok' if local_ready else 'not ready'}")
    docker_ready = bool(re.search(r"@sha256:[0-9a-fA-F]{64}$", config.gigahorse.image))
    typer.echo(f"gigahorse_docker: {'configured' if docker_ready else 'not configured'}")


@app.command()
def explain(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    selector: str = typer.Option(..., "--selector"),
) -> None:
    """Show one function's canonical evidence and inferred facts."""
    try:
        validate_manifest(run_dir)
        contract = load_contract(run_dir)
        function = next(item for item in contract.functions if item.selector == selector.lower())
    except (DecompilerError, StopIteration, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: selector not found or invalid run: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(function.model_dump(mode="json"), indent=2))


@app.command()
def render(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    annotated: bool = typer.Option(False, "--annotated"),
) -> None:
    """Re-render a saved run without rerunning analysis or AI."""
    try:
        validate_manifest(run_dir)
        contract = load_contract(run_dir)
        abi = load_abi(run_dir)
        storage = load_storage(run_dir)
        synthesis = load_synthesis(run_dir)
        output = render_contract(
            contract,
            abi,
            storage,
            pseudo_functions=synthesis or None,
            annotated=annotated,
        )
        path = run_dir / "output" / ("decompiled.annotated.sol" if annotated else "decompiled.sol")
        path.write_text(output, encoding="utf-8")
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: invalid run: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(path)


@app.command()
def validate(run_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Validate saved structured synthesis coverage against canonical IR."""
    try:
        validate_manifest(run_dir)
        contract = load_contract(run_dir)
        validate_structure(contract)
        coverage = compute_coverage(contract)
        path = run_dir / "output" / "validation.json"
        path.write_text(
            json.dumps(coverage.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: invalid run: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(coverage.model_dump(mode="json"), indent=2))


cache_app = typer.Typer(add_completion=False)
app.add_typer(cache_app, name="cache")


@cache_app.command("stats")
def cache_stats() -> None:
    """Show the local AI cache size."""
    typer.echo(json.dumps(CacheStore(load_config().ai.cache_dir).stats(), indent=2))


@cache_app.command("clear")
def cache_clear() -> None:
    """Clear local AI cache entries."""
    removed = CacheStore(load_config().ai.cache_dir).clear()
    typer.echo(f"removed {removed} cache entries")


benchmark_app = typer.Typer(add_completion=False)
app.add_typer(benchmark_app, name="benchmark")


@benchmark_app.command("run")
def benchmark_run(
    output_dir: Path = typer.Option(Path("runs/benchmark"), "--output-dir", "-o"),
    solc: str = typer.Option("solc", "--solc"),
    strict: bool = typer.Option(False, "--strict"),
) -> None:
    """Compile and run the deterministic benchmark fixtures."""
    try:
        results = run_benchmark(output_dir, compiler=solc, strict=strict)
    except (BenchmarkCompileError, OSError, ValueError) as exc:
        typer.echo(f"error: benchmark failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"completed {sum(item['status'] == 'ok' for item in results)}/{len(results)} fixtures"
    )


@benchmark_app.command("report")
def benchmark_report(
    output_dir: Path = typer.Option(Path("runs/benchmark"), "--output-dir", "-o"),
) -> None:
    """Render a saved benchmark result report."""
    try:
        typer.echo(report_benchmark(output_dir))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: benchmark results unavailable: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
