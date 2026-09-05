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
    backend: str = "auto"
    executable: str = "gigahorse"
    client: str = "src/evm_bytecode_decompiler/gigahorse/client/evm_bytecode_decompiler.dl"
    timeout_seconds: int = 180
    commit: str = ""
    image: str = ""
    toolchain_dir: Path = Path("vendor/gigahorse-toolchain")

    def __post_init__(self) -> None:
        if self.backend not in {"auto", "local", "docker", "builtin"}:
            raise ValueError(f"unsupported Gigahorse backend: {self.backend}")
        if self.timeout_seconds < 1:
            raise ValueError("Gigahorse timeout_seconds must be positive")


@dataclass(frozen=True)
class OutputConfig:
    root: Path = Path("runs")
    keep_raw_gigahorse: bool = True


@dataclass(frozen=True)
class AIConfig:
    provider: str = "openai-compatible"
    model: str = ""
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    temperature: float = 0.0
    max_concurrency: int = 4
    timeout_seconds: int = 60
    max_prompt_bytes: int = 128 * 1024
    cache_dir: Path = Path.home() / ".cache" / "evm-bytecode-decompiler" / "ai"

    def __post_init__(self) -> None:
        if self.max_concurrency < 1 or self.timeout_seconds < 1 or self.max_prompt_bytes < 1:
            raise ValueError("AI concurrency, timeout, and prompt limit must be positive")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("AI temperature must be between 0 and 2")


@dataclass(frozen=True)
class AppConfig:
    gigahorse: GigahorseConfig = field(default_factory=GigahorseConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    rpc: dict[str, str] = field(default_factory=dict)
    output: OutputConfig = field(default_factory=OutputConfig)


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or Path("evm-bytecode-decompiler.toml")
    if not config_path.is_file():
        return AppConfig()
    with config_path.open("rb") as handle:
        raw = _expand(tomllib.load(handle))
    gh = raw.get("gigahorse", {})
    ai = raw.get("ai", {})
    output = raw.get("output", {})
    return AppConfig(
        gigahorse=GigahorseConfig(
            backend=gh.get("backend", "auto"),
            executable=gh.get("executable", "gigahorse"),
            client=gh.get(
                "client",
                "src/evm_bytecode_decompiler/gigahorse/client/evm_bytecode_decompiler.dl",
            ),
            timeout_seconds=int(gh.get("timeout_seconds", 180)),
            commit=gh.get("commit", ""),
            image=gh.get("image", ""),
            toolchain_dir=Path(gh.get("toolchain_dir", "vendor/gigahorse-toolchain")).expanduser(),
        ),
        ai=AIConfig(
            provider=ai.get("provider", "openai-compatible"),
            model=ai.get("model", ""),
            endpoint=ai.get("endpoint", "https://api.openai.com/v1/chat/completions"),
            temperature=float(ai.get("temperature", 0.0)),
            max_concurrency=int(ai.get("max_concurrency", 4)),
            timeout_seconds=int(ai.get("timeout_seconds", 60)),
            max_prompt_bytes=int(ai.get("max_prompt_bytes", 128 * 1024)),
            cache_dir=Path(
                ai.get(
                    "cache_dir",
                    str(Path.home() / ".cache" / "evm-bytecode-decompiler" / "ai"),
                )
            ).expanduser(),
        ),
        rpc={str(key): str(value) for key, value in raw.get("rpc", {}).items() if value},
        output=OutputConfig(
            root=Path(output.get("root", "runs")),
            keep_raw_gigahorse=bool(output.get("keep_raw_gigahorse", True)),
        ),
    )
