"""Expected failures for the preregistered READ experiment."""


class ReadRunError(Exception):
    """Base class for an expected READ-run failure."""


class GenerationError(ReadRunError):
    """A requested procedural episode could not be generated safely."""


class IntegrityGateError(ReadRunError):
    """A preregistered integrity gate failed."""


class TrainingBlocked(ReadRunError):
    """Training was attempted before the frozen preconditions were met."""
