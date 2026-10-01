"""
Closure-Gap Vector: C_t = (C_sem,t, C_evid,t, C_proc,t, C_inst,t)

Each component quantifies a distinct vulnerability category that must be
resolved before an intent can be safely compiled into actuation parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class ClosureStatus(str, Enum):
    """Resolution status of a single gap dimension."""
    OPEN = "open"           # Gap not yet assessed
    PARTIAL = "partial"     # Gap reduced but not closed
    CLOSED = "closed"       # Gap fully resolved
    OVERCLOSED = "overclosed"  # Forced closure — risk of misdelegation


@dataclass
class ClosureGapVector:
    """
    Multidimensional closure-gap vector C_t.

    Each dimension is a float in [0.0, 1.0]:
        0.0 = fully closed (no uncertainty)
        1.0 = fully open   (maximum uncertainty / unresolved)

    Reference:
        C_t = (C_sem,t, C_evid,t, C_proc,t, C_inst,t)
    """

    # Semantic closure gap — ambiguity in task acceptance criteria
    c_sem: float = 1.0
    # Evidentiary closure gap — staleness / integrity of context sources
    c_evid: float = 1.0
    # Procedural closure gap — validated execution path / tool chain availability
    c_proc: float = 1.0
    # Institutional closure gap — role authorization and policy clearance
    c_inst: float = 1.0

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #

    def __post_init__(self) -> None:
        for name in ("c_sem", "c_evid", "c_proc", "c_inst"):
            v = getattr(self, name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(
                    f"Gap component '{name}' must be in [0.0, 1.0], got {v}"
                )

    # ------------------------------------------------------------------ #
    # Vector arithmetic                                                    #
    # ------------------------------------------------------------------ #

    def as_array(self) -> np.ndarray:
        """Return gap vector as a 4-D numpy array."""
        return np.array([self.c_sem, self.c_evid, self.c_proc, self.c_inst])

    def l2_norm(self) -> float:
        """Euclidean magnitude of the gap vector."""
        return float(np.linalg.norm(self.as_array()))

    def weighted_norm(self, weights: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)) -> float:
        """Weighted magnitude — allows domain-specific gap prioritization."""
        w = np.array(weights)
        return float(np.sqrt(np.dot(w * self.as_array(), self.as_array())))

    def is_closed(self, threshold: float = 0.1) -> bool:
        """True when all gap components are below the closure threshold."""
        return bool(np.all(self.as_array() <= threshold))

    def dominant_gap(self) -> str:
        """Return the name of the largest unresolved gap component."""
        components = {
            "semantic": self.c_sem,
            "evidentiary": self.c_evid,
            "procedural": self.c_proc,
            "institutional": self.c_inst,
        }
        return max(components, key=lambda k: components[k])

    def closure_statuses(self, threshold: float = 0.1) -> dict[str, ClosureStatus]:
        """Per-component closure status evaluation."""
        statuses: dict[str, ClosureStatus] = {}
        mapping = {
            "semantic": self.c_sem,
            "evidentiary": self.c_evid,
            "procedural": self.c_proc,
            "institutional": self.c_inst,
        }
        for name, val in mapping.items():
            if val <= threshold:
                statuses[name] = ClosureStatus.CLOSED
            elif val <= 0.4:
                statuses[name] = ClosureStatus.PARTIAL
            else:
                statuses[name] = ClosureStatus.OPEN
        return statuses

    # ------------------------------------------------------------------ #
    # Serialization                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "c_sem": self.c_sem,
            "c_evid": self.c_evid,
            "c_proc": self.c_proc,
            "c_inst": self.c_inst,
            "l2_norm": self.l2_norm(),
            "is_closed": self.is_closed(),
            "dominant_gap": self.dominant_gap(),
            "statuses": {k: v.value for k, v in self.closure_statuses().items()},
        }

    def __repr__(self) -> str:
        return (
            f"ClosureGapVector("
            f"sem={self.c_sem:.3f}, "
            f"evid={self.c_evid:.3f}, "
            f"proc={self.c_proc:.3f}, "
            f"inst={self.c_inst:.3f} | "
            f"‖Ct‖={self.l2_norm():.3f})"
        )
