from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .models import PersonNode


@dataclass
class Edge:
    target: str
    weight: float


class SocGraph:
    """In-memory adjacency representation of the social graph."""

    def __init__(self) -> None:
        self._people: Dict[str, PersonNode] = {}
        self._adjacency: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._edge_contexts: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(dict)
        self._max_weight: float = 0.0
        self._max_weight_stale: bool = False

    @property
    def people(self) -> Dict[str, PersonNode]:
        return self._people

    @property
    def adjacency(self) -> Dict[str, Dict[str, float]]:
        return self._adjacency

    def add_person(self, person: PersonNode, overwrite: bool = False) -> None:
        existing = self._people.get(person.id)
        if existing and not overwrite:
            raise ValueError(f"Person with id {person.id!r} already exists")
        self._people[person.id] = person
        self._adjacency.setdefault(person.id, {})

    def ensure_person(self, person_id: str) -> None:
        if person_id not in self._people:
            raise KeyError(f"Unknown person id: {person_id}")

    def add_connection(
        self,
        person_a: str,
        person_b: str,
        weight_delta: float,
        contexts: Optional[Dict[str, float]] = None,
        symmetric: bool = True,
    ) -> None:
        if person_a == person_b:
            raise ValueError("Self-loops are not allowed")
        self.ensure_person(person_a)
        self.ensure_person(person_b)
        self._increment_edge(person_a, person_b, weight_delta, contexts)
        if symmetric:
            self._increment_edge(person_b, person_a, weight_delta, contexts)

    def _increment_edge(
        self,
        source: str,
        target: str,
        weight_delta: float,
        contexts: Optional[Dict[str, float]],
    ) -> None:
        current = self._adjacency[source].get(target, 0.0)
        weight = current + weight_delta
        if weight <= 0:
            # Drop non-positive ties to keep traversal semantics clean.
            self._adjacency[source].pop(target, None)
            self._edge_contexts.pop((source, target), None)
            self._max_weight_stale = True
            return
        self._adjacency[source][target] = weight
        if weight > self._max_weight:
            self._max_weight = weight
        if contexts:
            context_map = self._edge_contexts[(source, target)]
            for name, delta in contexts.items():
                context_map[name] = context_map.get(name, 0.0) + delta

    def get_person(self, person_id: str) -> PersonNode:
        self.ensure_person(person_id)
        return self._people[person_id]

    def get_edge_weight(self, person_a: str, person_b: str) -> Optional[float]:
        return self._adjacency.get(person_a, {}).get(person_b)

    def neighbors(self, person_id: str) -> List[Edge]:
        self.ensure_person(person_id)
        return [Edge(target=target, weight=weight) for target, weight in self._adjacency[person_id].items()]

    def filter_people(self, **criteria: object) -> List[PersonNode]:
        results: List[PersonNode] = []
        for person in self._people.values():
            if self._matches(person, criteria.items()):
                results.append(person)
        return results

    def _matches(self, person: PersonNode, criteria: Iterable[Tuple[str, object]]) -> bool:
        for attr, expected in criteria:
            actual = getattr(person, attr)
            if isinstance(actual, list):
                if expected not in actual:
                    return False
            else:
                if actual != expected:
                    return False
        return True

    def as_dict(self) -> Dict[str, Dict[str, float]]:
        return {source: dict(targets) for source, targets in self._adjacency.items()}

    def edge_contexts(self, source: str, target: str) -> Dict[str, float]:
        return dict(self._edge_contexts.get((source, target), {}))

    def degree(self, person_id: str) -> int:
        return len(self._adjacency.get(person_id, {}))

    def max_weight(self) -> float:
        if self._max_weight_stale:
            self._max_weight = max(self._iter_weights(), default=0.0)
            self._max_weight_stale = False
        return self._max_weight

    def _iter_weights(self) -> Iterator[float]:
        for targets in self._adjacency.values():
            for weight in targets.values():
                yield weight
