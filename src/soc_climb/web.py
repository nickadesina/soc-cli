from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .graph import SocGraph
from .models import DecisionNode, FamilyLink, PersonNode
from .pathfinding import dijkstra_shortest_path
from .storage import load_graph_json, save_graph_json


class DecisionNodePayload(BaseModel):
    org: str
    role: str
    start: str | None = None
    end: str | None = None


class FamilyLinkPayload(BaseModel):
    person_id: str | None = None
    relationship: str
    alliance_signal: bool  # true if socially or strategically active


class PersonPayload(BaseModel):
    id: str
    name: str = ""
    family: str = ""
    schools: List[str] = Field(default_factory=list)
    employers: List[str] = Field(default_factory=list)
    location: str = ""
    tier: int | None = None  # 1 is highest, 4 is lowest
    dependency_weight: int = 3
    decision_nodes: List[DecisionNodePayload] = Field(default_factory=list)
    platforms: Dict[str, str] = Field(default_factory=dict)
    societies: Dict[str, int] = Field(default_factory=dict)
    ecosystems: List[str] = Field(default_factory=list)
    close_connections: List[str] = Field(default_factory=list)
    family_links: List[FamilyLinkPayload] = Field(default_factory=list)
    notes: str = ""


class ConnectionPayload(BaseModel):
    source: str
    target: str
    weight: float
    contexts: Dict[str, float] = Field(default_factory=dict)
    symmetric: bool = True


def create_app(snapshot_path: str | Path = "data/graph.json") -> FastAPI:
    app = FastAPI(title="Soc Climb Web")
    data_path = Path(snapshot_path)
    graph = load_graph_json(data_path) if data_path.exists() else SocGraph()

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def _persist() -> None:
        data_path.parent.mkdir(parents=True, exist_ok=True)
        save_graph_json(data_path, graph)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/graph")
    def get_graph() -> Dict[str, object]:
        return {
            "people": [person.to_dict() for person in graph.people.values()],
            "edges": _serialise_edges(graph),
        }

    @app.post("/api/people")
    def upsert_person(payload: PersonPayload) -> Dict[str, object]:
        _ensure_non_empty(payload.id, "id")
        if payload.tier is not None and not 1 <= payload.tier <= 4:
            raise HTTPException(status_code=400, detail="tier must be between 1 and 4")
        if not 1 <= payload.dependency_weight <= 5:
            raise HTTPException(status_code=400, detail="dependency_weight must be between 1 and 5")
        _ensure_int_rank_map(payload.societies, "societies")
        person = PersonNode(
            id=payload.id,
            name=payload.name,
            family=payload.family,
            schools=payload.schools,
            employers=payload.employers,
            location=payload.location,
            tier=payload.tier,
            dependency_weight=payload.dependency_weight,
            decision_nodes=[DecisionNode(**node.model_dump()) for node in payload.decision_nodes],
            platforms=payload.platforms,
            societies=payload.societies,
            ecosystems=payload.ecosystems,
            close_connections=payload.close_connections,
            family_links=[FamilyLink(**node.model_dump()) for node in payload.family_links],
            notes=payload.notes,
        )
        graph.add_person(person, overwrite=True)
        _persist()
        return {"status": "ok", "person": person.to_dict()}

    @app.delete("/api/people/{person_id}")
    def delete_person(person_id: str) -> Dict[str, object]:
        try:
            graph.remove_person(person_id)
        except KeyError as exc:
            _raise_graph_error(exc)
        _persist()
        return {"status": "ok", "person_id": person_id}

    @app.post("/api/connections")
    def add_connection(payload: ConnectionPayload) -> Dict[str, object]:
        _ensure_finite(payload.weight, "weight")
        _ensure_finite_map(payload.contexts, "context")
        try:
            graph.add_connection(
                payload.source,
                payload.target,
                payload.weight,
                contexts=payload.contexts,
                symmetric=payload.symmetric,
            )
        except (KeyError, ValueError) as exc:
            _raise_graph_error(exc)
        _persist()
        return {"status": "ok"}

    @app.delete("/api/connections")
    def delete_connection(
        source: str = Query(...),
        target: str = Query(...),
        symmetric: bool = Query(True),
    ) -> Dict[str, object]:
        try:
            graph.remove_connection(source, target, symmetric=symmetric)
        except KeyError as exc:
            _raise_graph_error(exc)
        _persist()
        return {"status": "ok"}

    @app.get("/api/path")
    def shortest_path(
        source: str = Query(...),
        target: str = Query(...),
    ) -> Dict[str, Any]:
        try:
            result = dijkstra_shortest_path(graph, source, target)
        except (KeyError, ValueError) as exc:
            _raise_graph_error(exc)
        if not result:
            return {"status": "not_found"}
        return result.as_dict()

    return app


def _serialise_edges(graph: SocGraph) -> List[Dict[str, object]]:
    edges: List[Dict[str, object]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for source, neighbors in graph.adjacency.items():
        for target, weight in neighbors.items():
            reverse_weight = graph.get_edge_weight(target, source)
            forward_contexts = graph.edge_contexts(source, target)
            reverse_contexts = graph.edge_contexts(target, source)
            pair_key = tuple(sorted((source, target)))

            if (
                reverse_weight is not None
                and reverse_weight == weight
                and reverse_contexts == forward_contexts
            ):
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                edges.append(
                    {
                        "id": f"{pair_key[0]}--{pair_key[1]}",
                        "source": pair_key[0],
                        "target": pair_key[1],
                        "weight": weight,
                        "contexts": forward_contexts,
                        "symmetric": True,
                    }
                )
                continue

            edges.append(
                {
                    "id": f"{source}->{target}",
                    "source": source,
                    "target": target,
                    "weight": weight,
                    "contexts": forward_contexts,
                    "symmetric": False,
                }
            )
    return edges


def _ensure_non_empty(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")


def _ensure_finite(value: float, field_name: str) -> None:
    if not isfinite(value):
        raise HTTPException(status_code=400, detail=f"{field_name} must be finite")


def _ensure_finite_map(values: Dict[str, float], field_prefix: str) -> None:
    for key, value in values.items():
        if not isfinite(value):
            raise HTTPException(status_code=400, detail=f"{field_prefix}[{key}] must be finite")


def _ensure_int_rank_map(values: Dict[str, int], field_name: str) -> None:
    for key, value in values.items():
        if not isinstance(value, int):
            raise HTTPException(status_code=400, detail=f"{field_name}[{key}] must be an int")
        if not 1 <= value <= 5:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name}[{key}] must be between 1 and 5",
            )


def _raise_graph_error(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        message = str(exc.args[0]) if exc.args else str(exc)
        raise HTTPException(status_code=404, detail=message) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


app = create_app()
