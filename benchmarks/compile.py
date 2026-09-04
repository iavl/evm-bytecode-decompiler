import json
import os
import re
import shutil
import subprocess
from pathlib import Path


class BenchmarkCompileError(RuntimeError):
    """A benchmark source could not be compiled to runtime bytecode."""


def _solc_select_binary(version: str | None) -> str | None:
    if version is None or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return None
    candidate = Path.home() / ".solc-select" / "artifacts" / f"solc-{version}" / f"solc-{version}"
    return str(candidate) if candidate.is_file() else None


def _resolve_compiler(compiler: str) -> str:
    selected = _solc_select_binary(compiler)
    if selected:
        return selected
    if compiler != "solc" or Path(compiler).is_file():
        return compiler
    requested = os.environ.get("SOLC_VERSION")
    if not requested:
        try:
            requested = (
                (Path.home() / ".solc-select" / "global-version")
                .read_text(encoding="ascii")
                .strip()
            )
        except OSError:
            requested = None
    if requested:
        selected = _solc_select_binary(requested)
        if selected:
            return selected
    selector = shutil.which("solc-select")
    if selector:
        try:
            result = subprocess.run(
                [selector, "versions"], capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result and result.returncode == 0:
            for line in result.stdout.splitlines():
                if "(current" in line:
                    selected = _solc_select_binary(line.split()[0])
                    if selected:
                        return selected
    return compiler


def compile_runtime(source: Path, *, compiler: str = "solc", timeout: int = 180) -> bytes:
    executable = _resolve_compiler(compiler)
    try:
        completed = subprocess.run(
            [executable, "--combined-json", "bin-runtime", str(source)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkCompileError(f"could not run {compiler}: {exc}") from exc
    if completed.returncode:
        raise BenchmarkCompileError(completed.stderr.strip() or "solc failed")
    try:
        document = json.loads(completed.stdout)
        runtimes = [
            item.get("bin-runtime", "")
            for item in document["contracts"].values()
            if item.get("bin-runtime")
        ]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BenchmarkCompileError("solc returned no combined runtime bytecode") from exc
    if not runtimes:
        raise BenchmarkCompileError(f"{source} produced no runtime bytecode")
    return bytes.fromhex(runtimes[0])
