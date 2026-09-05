import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, cast

from .relations import RELATION_SCHEMA_VERSION
from .runner import GigahorseResult, _collect_facts, _text


class DockerGigahorseRunner:
    def __init__(
        self, image: str, *, timeout_seconds: int = 180, client: Path | None = None
    ) -> None:
        if not re.search(r"@sha256:[0-9a-fA-F]{64}$", image):
            raise ValueError("Docker Gigahorse image must be pinned by digest")
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.client = client.resolve() if client else None

    def command(self, input_dir: Path, output_dir: Path, input_name: str) -> list[str]:
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges:true",
            "-v",
            f"{input_dir}:/input:ro",
            "-v",
            f"{output_dir}:/output",
        ]
        if self.client:
            command.extend(["-v", f"{self.client.parent}:/client:ro"])
        command.extend(
            [
                self.image,
                f"/input/{input_name}",
                "-w",
                "/output/working",
                "-r",
                "/output/results.json",
                "-T",
                str(self.timeout_seconds),
            ]
        )
        if self.client:
            command.extend(["--client", f"/client/{self.client.name}"])
        return command

    def run(self, code: bytes, output_dir: Path, *, sha256: str) -> GigahorseResult:
        """Run a pinned image and preserve its normalized output contract."""
        # Docker needs a stable mounted input; use a direct subprocess invocation.
        output_dir.mkdir(parents=True, exist_ok=True)
        facts = output_dir / "facts"
        facts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="evm-bytecode-decompiler-docker-") as temp_name:
            input_dir = Path(temp_name)
            input_path = input_dir / f"{sha256}.hex"
            input_path.write_text(code.hex() + "\n", encoding="ascii")
            argv = self.command(input_dir, output_dir, input_path.name)
            (output_dir / "invocation.json").write_text(
                json.dumps({"argv": argv}, indent=2) + "\n", encoding="utf-8"
            )
            try:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return GigahorseResult(
                    "timeout",
                    "unknown",
                    "unknown",
                    facts,
                    errors=["Docker Gigahorse timed out"],
                    stdout=_text(exc.stdout),
                    stderr=_text(exc.stderr),
                    backend="docker",
                )
            except OSError as exc:
                return GigahorseResult(
                    "error", "unknown", "unknown", facts, errors=[str(exc)], backend="docker"
                )
        (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
        fact_count = _collect_facts(output_dir / "working", facts)
        if fact_count:
            (facts / "schema.json").write_text(
                json.dumps({"version": RELATION_SCHEMA_VERSION}) + "\n", encoding="utf-8"
            )
        raw_results = output_dir / "results.json"
        if raw_results.is_file():
            (output_dir / "raw-results.json").write_bytes(raw_results.read_bytes())
        status: Literal["ok", "error"] = "ok" if result.returncode == 0 else "error"
        errors = []
        if result.returncode != 0:
            errors.append(f"Docker exited with status {result.returncode}")
        warnings = ["Docker Gigahorse produced no relation files"] if not fact_count else []
        return GigahorseResult(
            cast(Literal["ok", "partial", "timeout", "error"], status),
            "unknown",
            "unknown",
            facts,
            errors=errors,
            warnings=warnings,
            stdout=result.stdout,
            stderr=result.stderr,
            backend="docker",
            completeness="full" if fact_count else "partial",
        )
