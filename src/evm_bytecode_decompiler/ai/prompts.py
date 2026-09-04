import hashlib
from pathlib import Path

PROMPT_ROOT = Path(__file__).parent / "prompts"


def prompt_path(name: str) -> Path:
    path = PROMPT_ROOT / name
    if not path.is_file():
        raise FileNotFoundError(f"prompt not found: {name}")
    return path


def load_prompt(name: str) -> str:
    return prompt_path(name).read_text(encoding="utf-8")


def prompt_hash(name: str) -> str:
    return hashlib.sha256(prompt_path(name).read_bytes()).hexdigest()
