import hashlib
import json
from typing import Any


def schema_hash(schema: type[Any]) -> str:
    value = schema.model_json_schema()
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def cache_key(
    value: Any,
    *,
    prompt_version: str,
    model: str,
    schema_version: int = 1,
    schema_hash: str = "",
) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    material = f"{schema_version}\n{schema_hash}\n{prompt_version}\n{model}\n{payload}".encode()
    return hashlib.sha256(material).hexdigest()
