import hashlib
import json
from typing import Any


def cache_key(
    value: Any,
    *,
    prompt_version: str,
    model: str,
    schema_version: int = 1,
) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    material = f"{schema_version}\n{prompt_version}\n{model}\n{payload}".encode()
    return hashlib.sha256(material).hexdigest()
