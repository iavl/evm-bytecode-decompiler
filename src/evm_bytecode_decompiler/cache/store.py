import json
import os
import tempfile
from pathlib import Path
from typing import Any


class CacheStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.root / f"{key}.json")
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def stats(self) -> dict[str, int]:
        try:
            files = list(self.root.glob("*.json"))
        except OSError:
            files = []
        return {"entries": len(files)}

    def clear(self) -> int:
        removed = 0
        for path in self.root.glob("*.json"):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed += 1
        return removed
