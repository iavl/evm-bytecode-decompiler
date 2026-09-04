import re

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RESERVED = {
    "break",
    "case",
    "catch",
    "contract",
    "else",
    "external",
    "false",
    "function",
    "if",
    "import",
    "internal",
    "mapping",
    "new",
    "private",
    "public",
    "return",
    "struct",
    "true",
    "uint256",
    "while",
}


def safe_identifier(value: str | None, fallback: str) -> str:
    return value if value and IDENTIFIER_RE.fullmatch(value) and value not in RESERVED else fallback
