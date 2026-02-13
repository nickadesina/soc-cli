from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Dict, List


@dataclass
class DecisionNode:
    org: str
    role: str
    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        _validate_iso_date(self.start, "decision_nodes.start")
        _validate_iso_date(self.end, "decision_nodes.end")


@dataclass
class FamilyFriendLink:
    person_id: str | None
    relationship: str
    alliance_signal: bool  # true if socially or strategically active


@dataclass
class PersonNode:
    """Represents a person in the social graph."""

    id: str
    name: str = ""
    schools: List[str] = field(default_factory=list)
    employers: List[str] = field(default_factory=list)
    location: str = ""
    tier: int | None = None  # 1 is highest, 4 is lowest
    dependency_weight: int = 3
    decision_nodes: List[DecisionNode] = field(default_factory=list)
    platforms: Dict[str, str] = field(default_factory=dict)
    societies: Dict[str, int] = field(default_factory=dict)
    ecosystems: List[str] = field(default_factory=list)
    family_friends_links: List[FamilyFriendLink] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.decision_nodes = [
            _coerce_decision_node(node)
            for node in self.decision_nodes
        ]
        self.family_friends_links = [
            link if isinstance(link, FamilyFriendLink) else FamilyFriendLink(**link)
            for link in self.family_friends_links
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
            _coerce_decision_node(node)
            for node in payload.get("decision_nodes", [])
        ]
        links_payload = payload.get("family_friends_links", [])
        family_friends_links = _coerce_family_friends_links(links_payload)
        if not family_friends_links:
            # Backward compatibility for legacy schema:
            # - family_links -> family_friends_links
            # - close_connections -> family_friends_links (relationship="close_connection")
            legacy_links = payload.get("family_links", [])
            family_friends_links.extend(_coerce_family_friends_links(legacy_links))
            for connection_id in payload.get("close_connections", []) or []:
                if not isinstance(connection_id, str) or not connection_id.strip():
                    continue
                family_friends_links.append(
                    FamilyFriendLink(
                        person_id=connection_id.strip(),
                        relationship="close_connection",
                        alliance_signal=True,
                    )
                )
            family_friends_links = _dedupe_family_friends_links(family_friends_links)
        merged_payload = dict(payload)
        merged_payload["decision_nodes"] = decision_nodes
        merged_payload.pop("family", None)
        merged_payload.pop("close_connections", None)
        merged_payload.pop("family_links", None)
        merged_payload["family_friends_links"] = family_friends_links
        return cls(**merged_payload)


def _validate_iso_date(value: str | None, field_name: str) -> None:
    if value is None or value == "":
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date string, got {value!r}") from exc


def _coerce_decision_node(node: DecisionNode | Dict[str, object]) -> DecisionNode:
    if isinstance(node, DecisionNode):
        return node
    if not isinstance(node, dict):
        raise ValueError("decision_nodes entries must be DecisionNode objects or dict payloads")
    payload = dict(node)
    payload.pop("scope", None)
    return DecisionNode(**payload)


def _coerce_family_friends_links(
    links_payload: List[FamilyFriendLink] | List[Dict[str, object]] | object,
) -> List[FamilyFriendLink]:
    if not isinstance(links_payload, list):
        return []
    links: List[FamilyFriendLink] = []
    for raw_link in links_payload:
        if isinstance(raw_link, FamilyFriendLink):
            links.append(raw_link)
            continue
        if not isinstance(raw_link, dict):
            continue
        links.append(FamilyFriendLink(**raw_link))
    return _dedupe_family_friends_links(links)


def _dedupe_family_friends_links(
    links: List[FamilyFriendLink],
) -> List[FamilyFriendLink]:
    deduped: List[FamilyFriendLink] = []
    seen: set[tuple[str | None, str, bool]] = set()
    for link in links:
        relationship = (link.relationship or "").strip()
        person_id = link.person_id.strip() if isinstance(link.person_id, str) else None
        dedupe_key = (person_id, relationship, bool(link.alliance_signal))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(
            FamilyFriendLink(
                person_id=person_id,
                relationship=relationship,
                alliance_signal=bool(link.alliance_signal),
            )
        )
    return deduped
