import json
from pathlib import Path

import pytest

from evm_bytecode_decompiler.errors import InvalidBytecodeError
from evm_bytecode_decompiler.input.normalize import detect_metadata, normalize_target
from evm_bytecode_decompiler.input.rpc import block_tag


def test_normalize_file_and_detect_metadata(tmp_path: Path) -> None:
    trailer = b"\xa1\x01\x02" + (3).to_bytes(2, "big")
    path = tmp_path / "code.hex"
    path.write_text("0x6000" + trailer.hex(), encoding="ascii")

    normalized = normalize_target(str(path))

    assert normalized.code == b"\x60\x00" + trailer
    assert normalized.analysis_code == b"\x60\x00"
    assert normalized.metadata.metadata_trailer == detect_metadata(normalized.code)
    assert normalized.metadata.kind.value == "file"


@pytest.mark.parametrize("value", ["0x", "0", "0x123", "0xz1"])
def test_invalid_bytecode(value: str) -> None:
    with pytest.raises(InvalidBytecodeError):
        normalize_target(value)


def test_block_tag_preserves_explicit_history() -> None:
    assert block_tag(4660) == "0x1234"
    assert block_tag("20123456") == "0x1330f40"
    assert block_tag(None) == "latest"


def test_long_raw_hex_is_not_probed_as_a_filename() -> None:
    normalized = normalize_target("0x" + "60" * 600)
    assert normalized.metadata.kind.value == "raw"
    assert normalized.metadata.bytecode_size == 600


def test_historical_rpc_request_does_not_use_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, object]] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x6000"}).encode()

    def fake_urlopen(request: object, timeout: float) -> Response:
        requests.append(json.loads(request.data.decode()))  # type: ignore[attr-defined]
        return Response()

    monkeypatch.setattr("evm_bytecode_decompiler.input.rpc.urlopen", fake_urlopen)
    address = "0x" + "12" * 20
    normalized = normalize_target(address, rpc_url="https://rpc.example", block=4660)

    assert requests[0]["method"] == "eth_getCode"
    assert requests[0]["params"] == [address, "0x1234"]
    assert normalized.metadata.block == "0x1234"
