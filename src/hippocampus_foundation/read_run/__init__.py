"""Preregistered synthetic READ experiment.

The package is intentionally separate from the frozen Phase 0--2 governance
CLIs. Importing it does not import an ML framework or authorize training.
"""

from .generator import (
    BUDGET_CANDIDATES,
    GAMMA_BUCKETS,
    generate_episode,
    generate_split,
)
from .oracle import independently_solve

__all__ = [
    "BUDGET_CANDIDATES",
    "GAMMA_BUCKETS",
    "generate_episode",
    "generate_split",
    "independently_solve",
]
