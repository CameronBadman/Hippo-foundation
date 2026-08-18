"""Typed failures used by Phase 0 tooling."""


class Phase0Error(Exception):
    """Base class for an expected Phase 0 failure."""


class ValidationError(Phase0Error):
    """A manifest or record violates a frozen contract."""


class IntegrityError(Phase0Error):
    """Bytes or provenance do not match the registered artifact."""


class QuarantineError(Phase0Error):
    """A quarantine cannot be compiled or safely evaluated."""


class SealError(Phase0Error):
    """A confirmatory bundle or access log is invalid."""


class GateBlocked(Phase0Error):
    """The Phase 0 readiness gate has blockers."""
