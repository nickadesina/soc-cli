from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Dict, List, Optional


@dataclass
class DecisionNode:
    org: str
    role: str
    scope: str
    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        _validate_iso_date(self.start, "decision_nodes.start")
        _validate_iso_date(self.end, "decision_nodes.end")


@dataclass
class FamilyLink:
    person_id: str | None
    relationship: str
    alliance_signal: bool  # true if socially or strategically active


@dataclass
class PersonNode:
    """Represents a person in the social graph."""

    id: str
    name: str = ""
    family: str = ""
    schools: List[str] = field(default_factory=list)
    employers: List[str] = field(default_factory=list)
    location: str = ""
    tier: int | None = None  # 1 is highest, 4 is lowest
    dependency_weight: int = 3
    decision_nodes: List[DecisionNode] = field(default_factory=list)
    platforms: Dict[str, str] = field(default_factory=dict)
    societies: Dict[str, int] = field(default_factory=dict)
    ecosystems: List[str] = field(default_factory=list)
    close_connections: List[str] = field(default_factory=list)
    family_links: List[FamilyLink] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.decision_nodes = [
            node if isinstance(node, DecisionNode) else DecisionNode(**node)
            for node in self.decision_nodes
        ]
        self.family_links = [
            link if isinstance(link, FamilyLink) else FamilyLink(**link)
            for link in self.family_links
        ]
        if self.tier is not None and not 1 <= self.tier <= 4:
            raise ValueError(f"tier must be between 1 and 4, got {self.tier!r}")
        if not 1 <= self.dependency_weight <= 5:
            raise ValueError(
                f"dependency_weight must be between 1 and 5, got {self.dependency_weight!r}"
            )
        for society, rank in self.societies.items():
            if not isinstance(rank, int):
                raise ValueError(f"societies[{society!r}] must be an int rank")
            if not 1 <= rank <= 5:
                raise ValueError(
                    f"societies[{society!r}] must be between 1 and 5, got {rank!r}"
                )

    def to_dict(self) -> Dict[str, object]:
        """Return a serialisable representation."""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "PersonNode":
        """Create a node from a dictionary representation."""

        decision_nodes = [
            node if isinstance(node, DecisionNode) else DecisionNode(**node)
            for node in payload.get("decision_nodes", [])
        ]
        family_links = [
            link if isinstance(link, FamilyLink) else FamilyLink(**link)
            for link in payload.get("family_links", [])
        ]
        merged_payload = dict(payload)
        merged_payload["decision_nodes"] = decision_nodes
        merged_payload["family_links"] = family_links
        return cls(**merged_payload)


def _validate_iso_date(value: str | None, field_name: str) -> None:
    if value is None or value == "":
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string, got {value!r}") from exc
