import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
SKILL = ROOT / ".agents" / "skills" / "evm-bytecode-decompiler"


def run_installer(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "CODEX_HOME": str(tmp_path / "codex"),
            "CLAUDE_HOME": str(tmp_path / "claude"),
        }
    )
    return subprocess.run(
        [str(INSTALLER), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def target_path(tmp_path: Path, platform: str) -> Path:
    return tmp_path / platform / "skills" / "evm-bytecode-decompiler"


def test_install_copies_skill_to_both_targets(tmp_path: Path) -> None:
    result = run_installer(tmp_path)

    assert result.returncode == 0, result.stderr
    for platform in ("codex", "claude"):
        installed = target_path(tmp_path, platform)
        assert installed.is_dir()
        for relative in (
            Path("SKILL.md"),
            Path("agents/openai.yaml"),
            Path("references/workflow.md"),
            Path("scripts/analyze.sh"),
        ):
            assert (installed / relative).read_bytes() == (SKILL / relative).read_bytes()
        assert (installed / "scripts/analyze.sh").stat().st_mode & stat.S_IXUSR
        assert not (installed / "install.sh").exists()
        assert not (installed / "tests").exists()


@pytest.mark.parametrize("platform", ("codex", "claude"))
def test_install_can_select_one_target(tmp_path: Path, platform: str) -> None:
    result = run_installer(tmp_path, "--target", platform)

    assert result.returncode == 0, result.stderr
    assert target_path(tmp_path, platform).is_dir()
    other = "claude" if platform == "codex" else "codex"
    assert not target_path(tmp_path, other).exists()


@pytest.mark.parametrize("kind", ("directory", "file", "symlink", "dangling_symlink"))
def test_install_refuses_existing_destination_without_partial_install(
    tmp_path: Path, kind: str
) -> None:
    destination = target_path(tmp_path, "codex")
    destination.parent.mkdir(parents=True)

    if kind == "directory":
        destination.mkdir()
        marker = destination / "marker.txt"
        marker.write_text("keep", encoding="utf-8")
    elif kind == "file":
        destination.write_text("keep", encoding="utf-8")
    elif kind == "symlink":
        real_target = tmp_path / "real-target"
        real_target.mkdir()
        destination.symlink_to(real_target, target_is_directory=True)
    else:
        destination.symlink_to(tmp_path / "missing-target")

    result = run_installer(tmp_path)

    assert result.returncode != 0
    assert "destination already exists" in result.stderr
    assert not target_path(tmp_path, "claude").exists()
    if kind == "directory":
        assert marker.read_text(encoding="utf-8") == "keep"
    elif kind == "file":
        assert destination.read_text(encoding="utf-8") == "keep"
    elif kind == "symlink":
        assert destination.is_symlink()
        assert destination.resolve() == (tmp_path / "real-target").resolve()
    else:
        assert destination.is_symlink()
