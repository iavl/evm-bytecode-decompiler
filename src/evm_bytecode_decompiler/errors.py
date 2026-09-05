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


class BackendUnavailableError(DecompilerError):
    """The explicitly requested analysis backend is not available."""


class ArtifactError(DecompilerError):
    """A saved run is incomplete, inconsistent, or does not match its input."""


class IRBuildError(DecompilerError):
    """Relations could not be converted into canonical IR."""


class ValidationError(DecompilerError):
    """Generated deterministic output failed validation."""


class AnnotationError(DecompilerError):
    """An agent semantic overlay is invalid or does not match its run."""
