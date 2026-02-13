from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auto_edges import upsert_person_with_auto_edges
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
        return FileResponse(
            static_dir / "index.html",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

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
        auto_edges = upsert_person_with_auto_edges(
            graph,
            person,
            overwrite=True,
            top_k=None,
        )
        _persist()
        return {
            "status": "ok",
            "person": person.to_dict(),
            "auto_edges": auto_edges,
        }

    @app.post("/api/extract-person")
    async def extract_person(
        image: UploadFile = File(...),
        web_search: bool = Form(False),
    ) -> Dict[str, object]:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="image must be an image upload")
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="image cannot be empty")
        if len(image_bytes) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="image must be <= 8MB")
        extracted_payload = _extract_person_fields(image_bytes, image.content_type, web_search)
        return {"status": "ok", **extracted_payload}

    @app.delete("/api/people/{person_id}")
    def delete_person(person_id: str) -> Dict[str, object]:
        try:
            graph.remove_person(person_id)
        except KeyError as exc:
            _raise_graph_error(exc)
        _persist()
        return {"status": "ok", "person_id": person_id}

    @app.post("/api/connections", deprecated=True)
    def add_connection() -> Dict[str, object]:
        raise HTTPException(
            status_code=410,
            detail=(
                "Manual connection creation is deprecated and currently disabled. "
                "This flow may be reopened in a future update."
            ),
        )

    @app.delete("/api/connections", deprecated=True)
    def delete_connection() -> Dict[str, object]:
        raise HTTPException(
            status_code=410,
            detail=(
                "Manual connection deletion is deprecated and currently disabled. "
                "This flow may be reopened in a future update."
            ),
        )

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
    api_key = _get_openai_api_key()
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

    return _normalise_extracted_fields(extracted)


def _extract_person_fields(
    image_bytes: bytes,
    image_mime: str,
    web_search: bool,
) -> Dict[str, object]:
    if not web_search:
        extracted = _extract_person_fields_from_image(image_bytes, image_mime)
        return {"fields": extracted, "web_search_used": False}

    try:
        extracted = _extract_person_fields_from_image_with_web_search(image_bytes, image_mime)
        return {"fields": extracted, "web_search_used": True}
    except HTTPException as exc:
        # Web-search calls are more failure-prone (tool/network/policy availability).
        # Fall back to image-only extraction so the user can still continue.
        if exc.status_code not in {500, 502}:
            raise
        extracted = _extract_person_fields_from_image(image_bytes, image_mime)
        return {
            "fields": extracted,
            "web_search_used": False,
            "web_search_fallback": True,
            "warning": (
                "Web search extraction is temporarily unavailable. "
                "Used image-only extraction instead."
            ),
        }


def _extract_person_fields_from_image_with_web_search(
    image_bytes: bytes,
    image_mime: str,
) -> Dict[str, object]:
    api_key = _get_openai_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_data_url = f"data:{image_mime};base64,{image_b64}"
    schema = _person_extract_schema()
    body = {
        "model": "gpt-5-nano-2025-08-07",
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Extract a person profile from an image. Use null for unknown fields. "
                            "If id is unknown, create a lowercase snake_case id from the best full name guess. "
                            "Use web search only when needed to verify/complete visible details."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Read this image and extract person fields."},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            },
        ],
        "text": {"format": schema},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_json = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail="Failed to connect to OpenAI API") from exc

    text_output = _response_output_text(response_json)
    if not text_output:
        raise HTTPException(status_code=502, detail="OpenAI response parsing failed")
    try:
        extracted = json.loads(text_output)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OpenAI response parsing failed") from exc
    return _normalise_extracted_fields(extracted)


def _person_extract_schema() -> Dict[str, object]:
    return {
        "type": "json_schema",
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


def _response_output_text(response_json: Dict[str, object]) -> str | None:
    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    output_items = response_json.get("output")
    if not isinstance(output_items, list):
        return None
    for item in output_items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return None


def _normalise_extracted_fields(extracted: Dict[str, object]) -> Dict[str, object]:
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


def _get_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != "OPENAI_API_KEY":
            continue
        parsed = value.strip().strip("'").strip('"')
        if parsed:
            return parsed
    return ""


app = create_app()
