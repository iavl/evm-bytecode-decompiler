import json
import subprocess
import tempfile
from pathlib import Path

from .runner import GigahorseResult, _text


class DockerGigahorseRunner:
    def __init__(
        self, image: str, *, timeout_seconds: int = 180, client: Path | None = None
    ) -> None:
        if not image or "@sha256:" not in image:
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
                "--output",
                "/output/facts",
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
                )
            except OSError as exc:
                return GigahorseResult("error", "unknown", "unknown", facts, errors=[str(exc)])
        (output_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (output_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
        return GigahorseResult(
            "ok" if result.returncode == 0 else "error",
            "unknown",
            "unknown",
            facts,
            errors=(
                []
                if result.returncode == 0
                else [f"Docker exited with status {result.returncode}"]
            ),
            stdout=result.stdout,
            stderr=result.stderr,
        )
