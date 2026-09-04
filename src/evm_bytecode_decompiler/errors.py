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


class AIProviderError(DecompilerError):
    """An AI transport or provider response failed."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AIResponseValidationError(AIProviderError):
    """An AI response did not satisfy its requested structured schema."""


class SynthesisValidationError(DecompilerError):
    """Structured pseudocode did not preserve deterministic evidence."""
