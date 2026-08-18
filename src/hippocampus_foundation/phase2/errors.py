"""Expected failures from Phase 2 procedural-data tooling."""


class Phase2Error(Exception):
    """Base class for a user-actionable Phase 2 failure."""


class Phase2ValidationError(Phase2Error):
    """An input violates a frozen Phase 2 contract or semantic invariant."""


class Phase2IntegrityError(Phase2Error):
    """Artifact bytes, provenance, or split identities do not agree."""


class Phase2QuarantineError(Phase2Error):
    """A candidate cannot be shown to be clear of evaluation quarantine."""


class Phase2OracleDisagreement(Phase2Error):
    """The independent policy-label oracles disagree."""
