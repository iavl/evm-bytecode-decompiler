import shutil
from pathlib import Path

import typer

from . import __version__
from .config import load_config
from .errors import DecompilerError
from .pipeline.decompile import decompile

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
) -> None:
    """Decompile raw bytecode, a .hex file, or an address."""
    try:
        result = decompile(
            target,
            output_dir=output_dir,
            rpc_url=rpc_url,
            chain=chain,
            block=block,
        )
    except DecompilerError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if not no_ai:
        typer.echo(
            "AI phases are not implemented at this checkpoint; deterministic output was produced.",
            err=True,
        )
    typer.echo(result.run_dir)


@app.command("analyze")
def analyze_command(
    target: str = typer.Argument(..., metavar="TARGET"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    """Run the deterministic analysis checkpoint."""
    try:
        result = decompile(target, output_dir=output_dir)
    except DecompilerError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(result.run_dir)


@app.command()
def doctor() -> None:
    """Check the configured analysis environment."""
    config = load_config()
    executable = config.gigahorse.executable
    found = shutil.which(executable)
    typer.echo("python: ok")
    typer.echo("builtin_lifter: ok")
    typer.echo(f"gigahorse_local: {'ok' if found else 'not configured'}")
    typer.echo(f"gigahorse_docker: {'configured' if config.gigahorse.image else 'not configured'}")


if __name__ == "__main__":
    app()
