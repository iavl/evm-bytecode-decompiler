from pydantic import BaseModel, ConfigDict, Field


class ProxyDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected: bool
    kind: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    implementation_address: str | None = None


EIP1967_SLOTS = {
    "eip1967": "360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
    "eip1967_admin": "b53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103",
    "eip1967_beacon": "a3f0ad74e5423aebfd80d3ef4346578335a9a72aeaeea4f3b0d9d5d3f5f3f3f3",
}


def detect_proxy(code: bytes) -> ProxyDetection:
    text = code.hex()
    for kind, slot in EIP1967_SLOTS.items():
        if slot in text:
            return ProxyDetection(detected=True, kind=kind, confidence=0.98)
    code_hex = code.hex()
    if (
        len(code) == 45
        and code_hex.startswith("363d3d373d3d3d363d73")
        and code_hex.endswith("5af43d82803e903d91602b57fd5bf3")
    ):
        address = "0x" + code.hex()[20:60]
        return ProxyDetection(
            detected=True,
            kind="eip1167",
            confidence=0.99,
            implementation_address=address,
        )
    if 0xF4 in code:
        return ProxyDetection(detected=True, kind="delegatecall_fallback", confidence=0.60)
    return ProxyDetection(detected=False, confidence=1.0)
