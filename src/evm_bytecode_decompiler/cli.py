import json
import re
import shutil
import subprocess
from pathlib import Path

import typer
from benchmarks.compile import BenchmarkCompileError
from benchmarks.runner import report_benchmark, run_benchmark

from . import __version__
from .agent.artifacts import render_agent
from .agent.context import build_context
from .agent.validation import apply_proposal, validate_proposal
from .config import load_config
from .errors import DecompilerError
from .pipeline.artifacts import load_abi, load_contract, load_storage, validate_manifest
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
    no_ai: bool = typer.Option(
        False,
        "--no-ai",
        help="Deprecated compatibility flag; deterministic analysis never calls an AI provider.",
    ),
    rpc_url: str | None = typer.Option(None, "--rpc-url"),
    chain: str | None = typer.Option(None, "--chain"),
    block: str | None = typer.Option(None, "--block", help="Explicit block number or block tag."),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    resume: bool = typer.Option(False, "--resume", help="Reuse a valid deterministic run."),
    backend: str | None = typer.Option(
        None, "--backend", help="Require auto, local, docker, or builtin analysis."
    ),
) -> None:
    """Decompile raw bytecode, a .hex file, or an address deterministically."""
    if no_ai:
        typer.echo(
            "--no-ai is deprecated; the core CLI is deterministic and does not call "
            "an AI provider.",
            err=True,
        )
    try:
        result = run_decompile(
            target,
            output_dir=output_dir,
            rpc_url=rpc_url,
            chain=chain,
            block=block,
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
        result = run_decompile(target, output_dir=output_dir, backend=backend)
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
def context(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    selector: str | None = typer.Option(None, "--selector"),
) -> None:
    """Print bounded contract or function-level canonical evidence as JSON."""
    try:
        typer.echo(json.dumps(build_context(run_dir, selector), indent=2))
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: invalid run or context: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def explain(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    selector: str = typer.Option(..., "--selector"),
) -> None:
    """Show one function's bounded canonical evidence and inferred facts."""
    try:
        payload = build_context(run_dir, selector)
        function = payload.get("function")
        if isinstance(function, dict):
            payload.setdefault("id", function.get("id"))
            payload.setdefault("selector", function.get("selector"))
        typer.echo(json.dumps(payload, indent=2))
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: selector not found or invalid run: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def render(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    annotated: bool = typer.Option(False, "--annotated"),
) -> None:
    """Re-render canonical output, or an already-applied agent overlay."""
    try:
        validate_manifest(run_dir)
        if annotated:
            path, _ = render_agent(run_dir)
        else:
            contract = load_contract(run_dir)
            abi = load_abi(run_dir)
            storage = load_storage(run_dir)
            path = run_dir / "output" / "decompiled.sol"
            path.write_text(render_contract(contract, abi, storage), encoding="utf-8")
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: invalid run: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(path)


@app.command()
def validate(run_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Validate the saved deterministic IR and report its coverage."""
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


agent_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(agent_app, name="agent")


@agent_app.command("validate")
def agent_validate(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    proposal: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Validate an agent annotation proposal without writing it."""
    try:
        validated = validate_proposal(run_dir, proposal)
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: invalid annotation proposal: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(validated.model_dump(mode="json"), indent=2))


@agent_app.command("apply")
def agent_apply(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    proposal: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Validate and persist an agent annotation overlay."""
    try:
        apply_proposal(run_dir, proposal)
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: invalid annotation proposal: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(run_dir / "agent" / "annotations.json")


@agent_app.command("render")
def agent_render(run_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Render an applied semantic overlay and its report."""
    try:
        output, report = render_agent(run_dir)
    except (DecompilerError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"error: invalid agent overlay: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(output)
    typer.echo(report)


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
