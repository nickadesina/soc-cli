from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from .graph import SocGraph
from .models import PersonNode


@dataclass
class PersonEvent:
    person: PersonNode
    overwrite: bool = False


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

    def __init__(self, graph: SocGraph) -> None:
        self.graph = graph

    def apply(self, events: Iterable[GraphEvent]) -> None:
        for event in events:
            self._apply_event(event)

    def apply_person(self, person: PersonNode, overwrite: bool = False) -> None:
        """Helper for manual single-person updates."""

        self.graph.add_person(person, overwrite=overwrite)

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
            self.graph.add_person(event.person, overwrite=event.overwrite)
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
