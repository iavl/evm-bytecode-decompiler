class DecompilerError(Exception):
    """Base class for expected user-facing failures."""


class InvalidBytecodeError(DecompilerError):
    """The input is not non-empty hexadecimal EVM bytecode."""


class RPCError(DecompilerError):
    """An RPC request failed or returned an invalid response."""


class GigahorseTimeoutError(DecompilerError):
    """Gigahorse exceeded its configured timeout."""


class GigahorseAnalysisError(DecompilerError):
    """Gigahorse returned a failed analysis."""


class IRBuildError(DecompilerError):
    """Relations could not be converted into canonical IR."""


class ValidationError(DecompilerError):
    """Generated deterministic output failed validation."""
