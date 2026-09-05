import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .builtin import write_builtin_workspace
from .relations import RELATION_SCHEMA_VERSION


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
    backend: str = "unknown"
    completeness: Literal["full", "partial", "unknown"] = "unknown"

    @property
    def effective_status(self) -> Literal["ok", "partial", "timeout", "error"]:
        return "partial" if self.completeness == "partial" and self.status == "ok" else self.status


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode() if isinstance(value, bytes) else value


def _write_invocation(path: Path, argv: Sequence[str], *, cwd: Path | None = None) -> None:
    path.write_text(
        json.dumps({"argv": list(argv), "cwd": str(cwd) if cwd else None}, indent=2) + "\n",
        encoding="utf-8",
    )


def _collect_facts(source_dir: Path, facts_dir: Path) -> int:
    facts_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    if not source_dir.is_dir():
        return copied
    for path in source_dir.rglob("*"):
        if path.is_file() and path.suffix in {".csv", ".tsv", ".facts"}:
            shutil.copy2(path, facts_dir / path.name)
            copied += 1
    return copied


class LocalGigahorseRunner:
    def __init__(
        self,
        executable: str = "gigahorse",
        client: Path | None = None,
        timeout_seconds: int = 180,
        commit: str = "",
        toolchain_dir: Path | None = None,
    ) -> None:
        self.executable = executable
        self.client = client.resolve() if client else None
        self.timeout_seconds = timeout_seconds
        self.commit = commit or "unknown"
        self.toolchain_dir = toolchain_dir.resolve() if toolchain_dir else None

    def _commit(self) -> str:
        if self.commit != "unknown" or self.toolchain_dir is None:
            return self.commit
        try:
            result = subprocess.run(
                ["git", "-C", str(self.toolchain_dir), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        return result.stdout.strip() if result.returncode == 0 else "unknown"

    def run(self, code: bytes, output_dir: Path, *, sha256: str) -> GigahorseResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="evm-bytecode-decompiler-") as temp_name:
            work = Path(temp_name)
            input_path = work / f"{sha256}.hex"
            input_path.write_text(code.hex() + "\n", encoding="ascii")
            relations_dir = work / "relations"
            relations_dir.mkdir()
            executable_path = Path(self.executable)
            is_script = executable_path.name == "gigahorse.py"
            if is_script:
                gh_work = work / "gigahorse-work"
                results_path = work / "gigahorse-results.json"
                argv = [
                    sys.executable,
                    str(executable_path.resolve()),
                    "-w",
                    str(gh_work),
                    "-r",
                    str(results_path),
                    "-T",
                    str(self.timeout_seconds),
                ]
                if self.client:
                    argv.extend(["-C", str(self.client)])
                argv.append(str(input_path))
                command_cwd = self.toolchain_dir or executable_path.resolve().parent
            else:
                argv = [self.executable, str(input_path), "--output", str(relations_dir)]
                if self.client:
                    argv.extend(["--client", str(self.client)])
                command_cwd = work
            _write_invocation(output_dir / "invocation.json", argv, cwd=command_cwd)
            try:
                completed = subprocess.run(
                    argv,
                    cwd=command_cwd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return GigahorseResult(
                    "timeout",
                    "unknown",
                    self._commit(),
                    output_dir / "facts",
                    errors=[f"Gigahorse timed out after {self.timeout_seconds}s"],
                    duration_ms=int((time.monotonic() - started) * 1000),
                    stdout=_text(exc.stdout),
                    stderr=_text(exc.stderr),
                    backend="local",
                )
            except OSError as exc:
                return GigahorseResult(
                    "error",
                    "unknown",
                    self._commit(),
                    output_dir / "facts",
                    errors=[f"could not execute Gigahorse: {exc}"],
                    duration_ms=int((time.monotonic() - started) * 1000),
                    backend="local",
                )
            facts_dir = output_dir / "facts"
            facts_dir.mkdir(exist_ok=True)
            source_dir = relations_dir
            if is_script:
                source_dir = work / "gigahorse-work" / sha256 / "out"
            fact_count = _collect_facts(source_dir, facts_dir)
            if fact_count:
                (facts_dir / "schema.json").write_text(
                    json.dumps({"version": RELATION_SCHEMA_VERSION}) + "\n", encoding="utf-8"
                )
            if is_script and (work / "gigahorse-results.json").is_file():
                shutil.copy2(work / "gigahorse-results.json", output_dir / "raw-results.json")
            (output_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
            (output_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
            status: Literal["ok", "error"] = "ok" if completed.returncode == 0 else "error"
            errors = []
            if completed.returncode != 0:
                errors.append(f"Gigahorse exited with status {completed.returncode}")
            warnings = [completed.stderr] if completed.stderr and status == "ok" else []
            if status == "ok" and not fact_count:
                warnings.append("Gigahorse produced no relation files")
            return GigahorseResult(
                status,
                "unknown",
                self._commit(),
                facts_dir,
                warnings=warnings,
                errors=errors,
                duration_ms=int((time.monotonic() - started) * 1000),
                stdout=completed.stdout,
                stderr=completed.stderr,
                backend="local",
                completeness="full" if fact_count else "partial",
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
            backend="builtin",
            completeness="partial",
        )
