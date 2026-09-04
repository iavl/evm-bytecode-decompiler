import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ..errors import RPCError

MAX_RPC_RESPONSE_BYTES = 16 * 1024 * 1024


def block_tag(block: int | str | None) -> str:
    if block is None:
        return "latest"
    if isinstance(block, int):
        if block < 0:
            raise RPCError("block number cannot be negative")
        return hex(block)
    value = block.strip()
    if not value:
        raise RPCError("block tag cannot be empty")
    if value.isdigit():
        return hex(int(value))
    if value.startswith("0x"):
        try:
            int(value, 16)
        except ValueError as exc:
            raise RPCError(f"invalid hexadecimal block tag: {value}") from exc
        return value
    if value in {"latest", "earliest", "pending", "safe", "finalized"}:
        return value
    raise RPCError(f"invalid block tag: {value}")


def redact_rpc_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.password and not parsed.username:
        return url
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit(
        (parsed.scheme, f"***:***@{host}", parsed.path, parsed.query, parsed.fragment)
    )


@dataclass(frozen=True)
class RPCClient:
    url: str
    timeout: float = 15.0

    def get_code(self, address: str, block: int | str | None = None) -> str:
        tag = block_tag(block)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getCode",
            "params": [address, tag],
        }
        request = Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read(MAX_RPC_RESPONSE_BYTES + 1)
        except Exception as exc:
            raise RPCError(
                f"eth_getCode request failed for {redact_rpc_url(self.url)}: {exc}"
            ) from exc
        if len(body) > MAX_RPC_RESPONSE_BYTES:
            raise RPCError("RPC response exceeded the 16 MiB limit")
        try:
            result: Any = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RPCError("RPC returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise RPCError("RPC returned a non-object response")
        if result.get("error") is not None:
            raise RPCError(f"eth_getCode returned an RPC error: {result['error']}")
        code = result.get("result")
        if not isinstance(code, str):
            raise RPCError("eth_getCode response has no hexadecimal result")
        return code
