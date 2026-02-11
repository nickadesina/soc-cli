from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from math import isfinite
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
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

    @app.post("/api/extract-person")
    async def extract_person(image: UploadFile = File(...)) -> Dict[str, object]:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="image must be an image upload")
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="image cannot be empty")
        if len(image_bytes) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="image must be <= 8MB")
        extracted = _extract_person_fields_from_image(image_bytes, image.content_type)
        return {"status": "ok", "fields": extracted}

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


def _extract_person_fields_from_image(image_bytes: bytes, image_mime: str) -> Dict[str, object]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_data_url = f"data:{image_mime};base64,{image_b64}"
    schema = {
        "name": "person_extract",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "id": {"type": ["string", "null"]},
                "name": {"type": ["string", "null"]},
                "family": {"type": ["string", "null"]},
                "location": {"type": ["string", "null"]},
                "tier": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
                "dependency_weight": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
            },
            "required": ["id", "name", "family", "location", "tier", "dependency_weight"],
        },
        "strict": True,
    }
    body = {
        "model": "gpt-5-nano-2025-08-07",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract a person profile from an image. Use null for unknown fields. "
                    "If id is unknown, create a lowercase snake_case id from the best full name guess."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read this image and extract person fields."},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            response_json = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail="Failed to connect to OpenAI API") from exc

    try:
        content = response_json["choices"][0]["message"]["content"]
        extracted = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="OpenAI response parsing failed") from exc

    return {
        "id": _clean_optional_string(extracted.get("id")),
        "name": _clean_optional_string(extracted.get("name")),
        "family": _clean_optional_string(extracted.get("family")),
        "location": _clean_optional_string(extracted.get("location")),
        "tier": extracted.get("tier"),
        "dependency_weight": extracted.get("dependency_weight"),
    }


def _clean_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


app = create_app()
