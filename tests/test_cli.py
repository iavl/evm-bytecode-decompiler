from pathlib import Path

from typer.testing import CliRunner

from evm_bytecode_decompiler.cli import app


def test_no_ai_checkpoint_produces_workspace(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"
    result = CliRunner().invoke(
        app,
        ["decompile", str(fixture), "--no-ai", "-o", str(tmp_path / "run")],
    )

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "run" / "ir" / "contract.json").is_file()
    output = (tmp_path / "run" / "output" / "decompiled.sol").read_text(encoding="utf-8")
    assert "RECONSTRUCTED / UNVERIFIED" in output
    assert "0xa9059cbb" in output
    assert (tmp_path / "run" / "output" / "report.md").is_file()


def test_normal_decompile_is_deterministic_without_compatibility_flag(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"
    result = CliRunner().invoke(
        app,
        ["decompile", str(fixture), "--backend", "builtin", "-o", str(tmp_path / "run")],
    )

    assert result.exit_code == 0, result.stdout
    manifest = (tmp_path / "run" / "run.json").read_text(encoding="utf-8")
    assert '"ai"' not in manifest
    assert not (tmp_path / "run" / "semantics").exists()
