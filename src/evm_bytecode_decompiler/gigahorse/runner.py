import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .builtin import write_builtin_workspace


@dataclass(frozen=True)
class GigahorseResult:
    status: Literal["ok", "partial", "timeout", "error"]
    version: str
    commit: str
    relations_dir: Path
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode() if isinstance(value, bytes) else value


def _write_invocation(path: Path, argv: Sequence[str], *, cwd: Path | None = None) -> None:
    path.write_text(
        json.dumps({"argv": list(argv), "cwd": str(cwd) if cwd else None}, indent=2) + "\n",
        encoding="utf-8",
    )


class LocalGigahorseRunner:
    def __init__(
        self,
        executable: str = "gigahorse",
        client: Path | None = None,
        timeout_seconds: int = 180,
        commit: str = "",
    ) -> None:
        self.executable = executable
        self.client = client.resolve() if client else None
        self.timeout_seconds = timeout_seconds
        self.commit = commit or "unknown"

    def run(self, code: bytes, output_dir: Path, *, sha256: str) -> GigahorseResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="evm-bytecode-decompiler-") as temp_name:
            work = Path(temp_name)
            input_path = work / f"{sha256}.hex"
            input_path.write_text(code.hex() + "\n", encoding="ascii")
            relations_dir = work / "relations"
            relations_dir.mkdir()
            argv = [self.executable, str(input_path), "--output", str(relations_dir)]
            if self.client:
                argv.extend(["--client", str(self.client)])
            _write_invocation(output_dir / "invocation.json", argv, cwd=work)
            try:
                completed = subprocess.run(
                    argv,
                    cwd=work,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return GigahorseResult(
                    "timeout",
                    "unknown",
                    self.commit,
                    output_dir / "facts",
                    errors=[f"Gigahorse timed out after {self.timeout_seconds}s"],
                    duration_ms=int((time.monotonic() - started) * 1000),
                    stdout=_text(exc.stdout),
                    stderr=_text(exc.stderr),
                )
            except OSError as exc:
                return GigahorseResult(
                    "error",
                    "unknown",
                    self.commit,
                    output_dir / "facts",
                    errors=[f"could not execute Gigahorse: {exc}"],
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            facts_dir = output_dir / "facts"
            facts_dir.mkdir(exist_ok=True)
            for path in relations_dir.rglob("*"):
                if path.is_file() and path.suffix in {".csv", ".tsv", ".facts"}:
                    shutil.copy2(path, facts_dir / path.name)
            (output_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
            (output_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
            status: Literal["ok", "error"] = "ok" if completed.returncode == 0 else "error"
            errors = (
                []
                if status == "ok"
                else [f"Gigahorse exited with status {completed.returncode}"]
            )
            return GigahorseResult(
                status,
                "unknown",
                self.commit,
                facts_dir,
                warnings=[completed.stderr] if completed.stderr and status == "ok" else [],
                errors=errors,
                duration_ms=int((time.monotonic() - started) * 1000),
                stdout=completed.stdout,
                stderr=completed.stderr,
            )


class BuiltinRunner:
    """Small deterministic fallback for environments without Gigahorse."""

    def run(self, code: bytes, output_dir: Path, *, sha256: str) -> GigahorseResult:
        started = time.monotonic()
        output_dir.mkdir(parents=True, exist_ok=True)
        write_builtin_workspace(code, output_dir, sha256=sha256)
        _write_invocation(
            output_dir / "invocation.json",
            ["builtin-evm-lifter", "<runtime.hex>", "--output", str(output_dir / "facts")],
        )
        return GigahorseResult(
            "ok",
            "builtin-evm-lifter-1",
            "builtin",
            output_dir / "facts",
            warnings=["Gigahorse was not configured; using the limited built-in lifter."],
            duration_ms=int((time.monotonic() - started) * 1000),
        )
