import json
from pathlib import Path

from typer.testing import CliRunner

from evm_bytecode_decompiler.cli import app


def test_resume_render_validate_and_explain_commands(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "erc20" / "runtime.hex"
    runner = CliRunner()
    run_dir = tmp_path / "run"
    initial = runner.invoke(app, ["decompile", str(fixture), "--no-ai", "-o", str(run_dir)])
    resumed = runner.invoke(
        app,
        ["decompile", str(fixture), "--no-ai", "--resume", "-o", str(run_dir)],
    )
    rendered = runner.invoke(app, ["render", str(run_dir)])
    validated = runner.invoke(app, ["validate", str(run_dir)])
    explained = runner.invoke(app, ["explain", str(run_dir), "--selector", "0xa9059cbb"])

    assert initial.exit_code == resumed.exit_code == rendered.exit_code == 0
    assert validated.exit_code == explained.exit_code == 0
    assert json.loads(validated.stdout)["functions"] == 1.0
    assert json.loads(explained.stdout)["function"]["selector"] == "0xa9059cbb"
