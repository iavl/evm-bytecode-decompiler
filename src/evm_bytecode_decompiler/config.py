import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_RE.sub(lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class GigahorseConfig:
    backend: str = "local"
    executable: str = "gigahorse"
    client: str = "src/evm_bytecode_decompiler/gigahorse/client/evm_bytecode_decompiler.dl"
    timeout_seconds: int = 180
    commit: str = ""
    image: str = ""


@dataclass(frozen=True)
class OutputConfig:
    root: Path = Path("runs")
    keep_raw_gigahorse: bool = True


@dataclass(frozen=True)
class AppConfig:
    gigahorse: GigahorseConfig = field(default_factory=GigahorseConfig)
    rpc: dict[str, str] = field(default_factory=dict)
    output: OutputConfig = field(default_factory=OutputConfig)


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or Path("evm-bytecode-decompiler.toml")
    if not config_path.is_file():
        return AppConfig()
    with config_path.open("rb") as handle:
        raw = _expand(tomllib.load(handle))
    gh = raw.get("gigahorse", {})
    output = raw.get("output", {})
    return AppConfig(
        gigahorse=GigahorseConfig(
            backend=gh.get("backend", "local"),
            executable=gh.get("executable", "gigahorse"),
            client=gh.get(
                "client",
                "src/evm_bytecode_decompiler/gigahorse/client/evm_bytecode_decompiler.dl",
            ),
            timeout_seconds=int(gh.get("timeout_seconds", 180)),
            commit=gh.get("commit", ""),
            image=gh.get("image", ""),
        ),
        rpc={str(key): str(value) for key, value in raw.get("rpc", {}).items() if value},
        output=OutputConfig(
            root=Path(output.get("root", "runs")),
            keep_raw_gigahorse=bool(output.get("keep_raw_gigahorse", True)),
        ),
    )
