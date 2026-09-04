import hashlib
import re
from pathlib import Path

from ..errors import InvalidBytecodeError
from ..models.input import InputKind, InputMetadata, MetadataTrailer, NormalizedBytecode
from .rpc import RPCClient, block_tag

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def normalize_hex(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        code = value
    else:
        text = value.strip()
        if text.startswith(("0x", "0X")):
            text = text[2:]
        if not text:
            raise InvalidBytecodeError("bytecode is empty")
        if len(text) % 2:
            raise InvalidBytecodeError("hexadecimal bytecode must have an even number of digits")
        try:
            code = bytes.fromhex(text)
        except ValueError as exc:
            raise InvalidBytecodeError("bytecode contains non-hexadecimal characters") from exc
    if not code:
        raise InvalidBytecodeError("bytecode is empty")
    return code


def detect_metadata(code: bytes) -> MetadataTrailer | None:
    """Detect the common Solidity CBOR trailer without changing canonical bytes."""
    if len(code) < 4:
        return None
    length = int.from_bytes(code[-2:], "big")
    offset = len(code) - 2 - length
    if length <= 0 or offset < 0 or code[offset] & 0xE0 != 0xA0:
        return None
    return MetadataTrailer(offset=offset, length=length)


def normalize_bytecode(
    value: str | bytes,
    *,
    kind: InputKind = InputKind.RAW,
    target: str | None = None,
    chain: str | None = None,
    block: int | str | None = None,
) -> NormalizedBytecode:
    code = normalize_hex(value)
    trailer = detect_metadata(code)
    metadata = InputMetadata(
        kind=kind,
        target=target or (value if isinstance(value, str) else "<bytes>"),
        chain=chain,
        block=None if block is None else block_tag(block),
        bytecode_sha256=hashlib.sha256(code).hexdigest(),
        bytecode_size=len(code),
        metadata_trailer=trailer,
    )
    analysis_code = code[: trailer.offset] if trailer else code
    return NormalizedBytecode(code=code, analysis_code=analysis_code, metadata=metadata)


def normalize_target(
    target: str,
    *,
    rpc_url: str | None = None,
    chain: str | None = None,
    block: int | str | None = None,
    timeout: float = 15.0,
) -> NormalizedBytecode:
    candidate = target.strip()
    hex_text = candidate[2:] if candidate.startswith(("0x", "0X")) else candidate
    looks_like_hex = (
        bool(hex_text)
        and len(hex_text) % 2 == 0
        and all(character in "0123456789abcdefABCDEF" for character in hex_text)
    )
    path = (
        Path(target) if not looks_like_hex and len(target) < 4096 and "\x00" not in target else None
    )
    if path is not None and path.is_file():
        return normalize_bytecode(
            path.read_text(encoding="utf-8"),
            kind=InputKind.FILE,
            target=str(path),
            chain=chain,
            block=block,
        )
    if ADDRESS_RE.fullmatch(target):
        if not rpc_url:
            raise InvalidBytecodeError("an RPC URL is required when TARGET is an address")
        code = RPCClient(rpc_url, timeout).get_code(target, block)
        return normalize_bytecode(
            code,
            kind=InputKind.ADDRESS,
            target=target,
            chain=chain,
            block=block,
        )
    return normalize_bytecode(target, chain=chain, block=block)
