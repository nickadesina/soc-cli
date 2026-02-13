from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from .auto_edges import upsert_person_with_auto_edges
from .graph import SocGraph
from .models import PersonNode


@dataclass
class PersonEvent:
    person: PersonNode
    overwrite: bool = False
    auto_top_k: int | None = None


@dataclass
class EdgeEvent:
    source: str
    target: str
    weight_delta: float
    contexts: Optional[Dict[str, float]] = None
    symmetric: bool = True


GraphEvent = PersonEvent | EdgeEvent


class GraphIngestionService:
    """Applies node and edge events to a graph in batch mode."""

    def __init__(
        self,
        graph: SocGraph,
        *,
        auto_connect_people: bool = True,
        auto_top_k: int | None = None,
    ) -> None:
        self.graph = graph
        self.auto_connect_people = auto_connect_people
        self.auto_top_k = auto_top_k

    def apply(self, events: Iterable[GraphEvent]) -> None:
        for event in events:
            self._apply_event(event)

    def apply_person(self, person: PersonNode, overwrite: bool = False) -> None:
        """Helper for manual single-person updates."""

        if not self.auto_connect_people:
            self.graph.add_person(person, overwrite=overwrite)
            return
        upsert_person_with_auto_edges(
            self.graph,
            person,
            overwrite=overwrite,
            top_k=self.auto_top_k,
        )

    def apply_edge(
        self,
        source: str,
        target: str,
        weight_delta: float,
        contexts: Optional[Dict[str, float]] = None,
        symmetric: bool = True,
    ) -> None:
        """Helper for manual single-edge updates."""

        self.graph.add_connection(
            source,
            target,
            weight_delta,
            contexts=contexts,
            symmetric=symmetric,
        )

    def _apply_event(self, event: GraphEvent) -> None:
        if isinstance(event, PersonEvent):
            if not self.auto_connect_people:
                self.graph.add_person(event.person, overwrite=event.overwrite)
                return
            upsert_person_with_auto_edges(
                self.graph,
                event.person,
                overwrite=event.overwrite,
                top_k=event.auto_top_k if event.auto_top_k is not None else self.auto_top_k,
            )
            return
        if isinstance(event, EdgeEvent):
            self.graph.add_connection(
                event.source,
                event.target,
                event.weight_delta,
                contexts=event.contexts,
                symmetric=event.symmetric,
            )
            return
        raise TypeError(f"Unhandled event type: {type(event)!r}")
