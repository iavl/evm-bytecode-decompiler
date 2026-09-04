from pathlib import Path

import pytest

from evm_bytecode_decompiler.gigahorse.docker import DockerGigahorseRunner
from evm_bytecode_decompiler.gigahorse.runner import BuiltinRunner, LocalGigahorseRunner


def test_builtin_runner_writes_reusable_workspace(tmp_path: Path) -> None:
    result = BuiltinRunner().run(bytes.fromhex("6000"), tmp_path / "gigahorse", sha256="abc")
    assert result.status == "ok"
    assert (tmp_path / "gigahorse" / "facts" / "Block.tsv").is_file()
    assert (tmp_path / "gigahorse" / "results.json").is_file()


def test_local_runner_uses_argument_vector_and_no_shell(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv: list[str], **kwargs: object) -> Completed:
        seen["argv"] = argv
        seen.update(kwargs)
        return Completed()

    monkeypatch.setattr("evm_bytecode_decompiler.gigahorse.runner.subprocess.run", fake_run)
    result = LocalGigahorseRunner("gigahorse", timeout_seconds=1).run(
        bytes.fromhex("6000"), tmp_path / "gigahorse", sha256="abc"
    )

    assert result.status == "ok"
    assert seen.get("shell", False) is False
    assert seen["argv"][0] == "gigahorse"


def test_docker_runner_requires_an_immutable_image_digest(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        DockerGigahorseRunner("ghcr.io/example/gigahorse:1")

    runner = DockerGigahorseRunner(
        "ghcr.io/example/gigahorse@sha256:" + "a" * 64,
        client=tmp_path / "client.dl",
    )
    command = runner.command(tmp_path / "input", tmp_path / "output", "runtime.hex")
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--client" in command


def test_local_runner_uses_gigahorse_script_contract(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv: list[str], **kwargs: object) -> Completed:
        seen["argv"] = argv
        seen.update(kwargs)
        return Completed()

    monkeypatch.setattr("evm_bytecode_decompiler.gigahorse.runner.subprocess.run", fake_run)
    result = LocalGigahorseRunner(
        str(tmp_path / "gigahorse.py"),
        client=tmp_path / "client.dl",
        commit="pinned",
        toolchain_dir=tmp_path,
    ).run(bytes.fromhex("6000"), tmp_path / "run", sha256="abc")

    argv = seen["argv"]
    assert result.status == "ok"
    assert Path(argv[0]).name.startswith("python")
    assert "-C" in argv and "-w" in argv and "-r" in argv and "-T" in argv
    assert seen.get("shell", False) is False
