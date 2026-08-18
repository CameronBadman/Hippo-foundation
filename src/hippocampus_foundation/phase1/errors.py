"""Expected failures from Phase 1 preparation tooling."""


class Phase1Error(Exception):
    """Base class for a user-actionable Phase 1 failure."""


class Phase1ValidationError(Phase1Error):
    """A record violates a frozen Phase 1 contract."""


class Phase1IntegrityError(Phase1Error):
    """Bytes or detached evidence do not match their registered identity."""


class Phase1GateBlocked(Phase1Error):
    """A prerequisite gate has not authorized data preparation."""
