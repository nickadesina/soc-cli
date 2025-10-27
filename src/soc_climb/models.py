from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class PersonNode:
    """Represents a person in the social graph."""

    id: str
    name: Optional[str] = None
    school: List[str] = field(default_factory=list)
    employers: List[str] = field(default_factory=list)
    societies: List[str] = field(default_factory=list)
    location: Optional[str] = None
    grad_year: Optional[int] = None
    platforms: Dict[str, str] = field(default_factory=dict)
    status_score: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        """Return a serialisable representation."""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "PersonNode":
        """Create a node from a dictionary representation."""

        return cls(**payload)
