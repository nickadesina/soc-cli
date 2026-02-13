from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auto_edges import upsert_person_with_auto_edges
from .graph import SocGraph
from .models import DecisionNode, FamilyFriendLink, PersonNode
from .pathfinding import dijkstra_shortest_path
from .storage import load_graph_json, save_graph_json

IMAGE_EXTRACT_MODEL = "gpt-5-mini-2025-08-07"
WEB_SEARCH_EXTRACT_MODEL = "gpt-5-mini-2025-08-07"
CLEAN_FIELDS_MODEL = "gpt-5-mini-2025-08-07"
NOTES_CLEAN_FORMAT = """
Use this exact person format:
- id: string (snake_case preferred)
- name: string
- schools: list[string]
- employers: list[string]
- location: string | null (must be a geographic place, not nationality/ethnicity/role text)
- tier: int | null (1..4)
- dependency_weight: int | null (1..5)
- decision_nodes: list[{"org": str, "role": str, "start": str|null, "end": str|null}]
- platforms: map[string, string]
- societies: map[string, int] where each rank is 1..5
- ecosystems: list[string]
- family_friends_links: list[{"person_id": str|null, "relationship": str, "alliance_signal": bool}]
- notes: string | null

Cleaning rules:
- Keep only supported fields.
- Null unknown scalar values; use [] for unknown lists; use {} for unknown maps.
- Remove duplicates in lists.
- Do not infer family name fields.
- Preserve valid existing values when possible; normalize formatting.
"""
LOCATION_ROLE_WORDS = {
    "entrepreneur",
    "businessman",
    "businesswoman",
    "founder",
    "ceo",
    "cto",
    "investor",
    "author",
    "politician",
    "actor",
    "actress",
    "composer",
    "musician",
    "engineer",
    "former",
}
DEMONYM_SUFFIXES = (
    "american",
    "german",
    "british",
    "french",
    "italian",
    "spanish",
    "canadian",
    "russian",
    "chinese",
    "japanese",
    "indian",
)
logger = logging.getLogger(__name__)


class DecisionNodePayload(BaseModel):
    org: str
    role: str
    start: str | None = None
    end: str | None = None


class FamilyFriendLinkPayload(BaseModel):
    person_id: str | None = None
    relationship: str
    alliance_signal: bool  # true if socially or strategically active


class PersonPayload(BaseModel):
    id: str
    name: str = ""
    schools: List[str] = Field(default_factory=list)
    employers: List[str] = Field(default_factory=list)
    location: str = ""
    tier: int | None = None  # 1 is highest, 4 is lowest
    dependency_weight: int = 3
    decision_nodes: List[DecisionNodePayload] = Field(default_factory=list)
    platforms: Dict[str, str] = Field(default_factory=dict)
    societies: Dict[str, int] = Field(default_factory=dict)
    ecosystems: List[str] = Field(default_factory=list)
    family_friends_links: List[FamilyFriendLinkPayload] = Field(default_factory=list)
    notes: str = ""


class CleanFieldsPayload(BaseModel):
    fields: Dict[str, object] = Field(default_factory=dict)


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
            schools=payload.schools,
            employers=payload.employers,
            location=payload.location,
            tier=payload.tier,
            dependency_weight=payload.dependency_weight,
            decision_nodes=[DecisionNode(**node.model_dump()) for node in payload.decision_nodes],
            platforms=payload.platforms,
            societies=payload.societies,
            ecosystems=payload.ecosystems,
            family_friends_links=[
                FamilyFriendLink(**node.model_dump())
                for node in payload.family_friends_links
            ],
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
        image: UploadFile | None = File(None),
        name_query: str | None = Form(None),
        web_search: bool = Form(False),
    ) -> Dict[str, object]:
        cleaned_name_query = _clean_optional_string(name_query)
        if image is None and cleaned_name_query is None:
            raise HTTPException(
                status_code=400,
                detail="Provide an image upload or a name query",
            )

        if image is not None:
            if not image.content_type or not image.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="image must be an image upload")
            image_bytes = await image.read()
            if not image_bytes:
                raise HTTPException(status_code=400, detail="image cannot be empty")
            if len(image_bytes) > 8 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="image must be <= 8MB")
            extracted_payload = _extract_person_fields(
                image_bytes,
                image.content_type,
                web_search,
                name_hint=cleaned_name_query,
            )
        else:
            extracted_payload = _extract_person_fields_from_name_query(
                cleaned_name_query,
                web_search=web_search,
            )
        observability_flags = _extract_observability_flags(
            extracted_payload,
            image_used=image is not None,
            name_query_provided=cleaned_name_query is not None,
        )
        logger.info(
            (
                "extract_person_observability "
                "image_used=%s name_query_used=%s "
                "web_search_used=%s web_search_retry=%s web_search_fallback=%s"
            ),
            observability_flags["image_used"],
            observability_flags["name_query_used"],
            observability_flags["web_search_used"],
            observability_flags["web_search_retry"],
            observability_flags["web_search_fallback"],
        )
        return {"status": "ok", **extracted_payload}

    @app.post("/api/clean-fields")
    def clean_fields(payload: CleanFieldsPayload) -> Dict[str, object]:
        cleaned = _clean_fields_with_model(payload.fields or {})
        return {"status": "ok", "fields": cleaned}

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
    schema_payload = _person_extract_schema()
    schema = {
        "name": schema_payload["name"],
        "schema": schema_payload["schema"],
        "strict": schema_payload["strict"],
    }
    body = {
        "model": IMAGE_EXTRACT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract a person profile from an image. Use null for unknown fields. "
                    "Location must be a geographic place (city/state/country), never nationality. "
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
    *,
    name_hint: str | None = None,
) -> Dict[str, object]:
    image_only_fields = _extract_person_fields_from_image(image_bytes, image_mime)
    if not web_search:
        return {"fields": image_only_fields, "web_search_used": False}

    effective_name_hint = name_hint or _clean_optional_string(image_only_fields.get("name"))
    try:
        web_fields = _extract_person_fields_from_image_with_web_search(
            image_bytes,
            image_mime,
            name_hint=effective_name_hint,
            id_hint=image_only_fields.get("id"),
        )
        merged_fields = _merge_extracted_fields(primary=web_fields, fallback=image_only_fields)
        if _needs_name_follow_up(merged_fields):
            name_query = _best_name_query(primary=merged_fields, fallback=image_only_fields)
            if name_query:
                follow_up_fields = _extract_person_fields_from_name_with_web_search(name_query)
                merged_fields = _merge_extracted_fields(
                    primary=follow_up_fields,
                    fallback=merged_fields,
                )
        return {"fields": merged_fields, "web_search_used": True}
    except HTTPException as exc:
        # Web-search calls are more failure-prone (tool/network/policy availability).
        # Retry with name-based query before falling back to image-only.
        if exc.status_code not in {500, 502}:
            raise
        name_query = _best_name_query(primary=image_only_fields, fallback=image_only_fields)
        if name_query:
            try:
                retry_fields = _extract_person_fields_from_name_with_web_search(name_query)
                merged_retry_fields = _merge_extracted_fields(
                    primary=retry_fields,
                    fallback=image_only_fields,
                )
                return {
                    "fields": merged_retry_fields,
                    "web_search_used": True,
                    "web_search_retry": True,
                }
            except HTTPException as retry_exc:
                if retry_exc.status_code not in {500, 502}:
                    raise
        return {
            "fields": image_only_fields,
            "web_search_used": False,
            "web_search_fallback": True,
            "warning": (
                "Web search extraction is temporarily unavailable. "
                "Used image-only extraction instead."
            ),
        }


def _extract_person_fields_from_name_query(
    name_query: str | None,
    *,
    web_search: bool,
) -> Dict[str, object]:
    cleaned_name = _clean_optional_string(name_query)
    if cleaned_name is None:
        raise HTTPException(status_code=400, detail="name_query cannot be empty")

    if not web_search:
        return {
            "fields": _fallback_fields_for_name(cleaned_name),
            "web_search_used": False,
            "web_search_fallback": True,
            "warning": "Web Search is off. Returned name-only fallback fields.",
            "name_query_used": True,
        }

    try:
        web_fields = _extract_person_fields_from_name_with_web_search(cleaned_name)
        merged_fields = _merge_extracted_fields(
            primary=web_fields,
            fallback=_fallback_fields_for_name(cleaned_name),
        )
        return {
            "fields": merged_fields,
            "web_search_used": True,
            "name_query_used": True,
        }
    except HTTPException as exc:
        if exc.status_code not in {500, 502}:
            raise
        return {
            "fields": _fallback_fields_for_name(cleaned_name),
            "web_search_used": False,
            "web_search_fallback": True,
            "warning": "Web search failed. Returned name-only fallback fields.",
            "name_query_used": True,
        }


def _extract_observability_flags(
    payload: Dict[str, object],
    *,
    image_used: bool,
    name_query_provided: bool,
) -> Dict[str, bool]:
    return {
        "image_used": bool(image_used),
        "name_query_used": bool(name_query_provided or payload.get("name_query_used")),
        "web_search_used": bool(payload.get("web_search_used")),
        "web_search_retry": bool(payload.get("web_search_retry")),
        "web_search_fallback": bool(payload.get("web_search_fallback")),
    }


def _clean_fields_with_model(fields: Dict[str, object]) -> Dict[str, object]:
    api_key = _get_openai_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    schema = _clean_fields_schema()
    body = {
        "model": CLEAN_FIELDS_MODEL,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Clean and normalize the payload to the required schema exactly.\n"
                            f"{NOTES_CLEAN_FORMAT}"
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Clean this payload to match the required format exactly. "
                            f"Input JSON:\n{json.dumps(fields, ensure_ascii=True)}"
                        ),
                    }
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
        cleaned_raw = json.loads(text_output)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OpenAI response parsing failed") from exc
    if not isinstance(cleaned_raw, dict):
        raise HTTPException(status_code=502, detail="OpenAI response parsing failed")
    return _normalise_cleaned_person_fields(cleaned_raw)


def _extract_person_fields_from_image_with_web_search(
    image_bytes: bytes,
    image_mime: str,
    *,
    name_hint: str | None = None,
    id_hint: str | None = None,
) -> Dict[str, object]:
    api_key = _get_openai_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_data_url = f"data:{image_mime};base64,{image_b64}"
    schema = _person_extract_schema()
    body = {
        "model": WEB_SEARCH_EXTRACT_MODEL,
        "tools": [{"type": "web_search"}],
        "tool_choice": "required",
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": _web_search_system_instruction(name_hint=name_hint, id_hint=id_hint),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Read this image, identify the person name visible in the image, "
                            "run a quick web search for that person, and return the final fields."
                        ),
                    },
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

    if not _response_used_web_search(response_json):
        raise HTTPException(
            status_code=502,
            detail="Web search extraction did not use web_search tool",
        )
    text_output = _response_output_text(response_json)
    if not text_output:
        raise HTTPException(status_code=502, detail="OpenAI response parsing failed")
    try:
        extracted = json.loads(text_output)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OpenAI response parsing failed") from exc
    return _normalise_extracted_fields(extracted)


def _extract_person_fields_from_name_with_web_search(name_query: str) -> Dict[str, object]:
    api_key = _get_openai_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    schema = _person_extract_schema()
    body = {
        "model": WEB_SEARCH_EXTRACT_MODEL,
        "tools": [{"type": "web_search"}],
        "tool_choice": "required",
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Perform a quick web search to build a basic person profile. "
                            "Location must be a geographic place (city/state/country), never nationality. "
                            "Use null for uncertain fields."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f'Search for "{name_query}" and return profile fields from reliable sources. '
                            "Prioritize known biography/profile pages."
                        ),
                    }
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

    if not _response_used_web_search(response_json):
        raise HTTPException(status_code=502, detail="Name-only search did not use web_search tool")
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
                "location": {"type": ["string", "null"]},
                "schools": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "maxItems": 6,
                },
                "employers": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "maxItems": 6,
                },
                "notes": {"type": ["string", "null"]},
                "tier": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
                "dependency_weight": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
            },
            "required": [
                "id",
                "name",
                "location",
                "schools",
                "employers",
                "notes",
                "tier",
                "dependency_weight",
            ],
        },
        "strict": True,
    }


def _clean_fields_schema() -> Dict[str, object]:
    return {
        "type": "json_schema",
        "name": "person_clean",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "id": {"type": ["string", "null"]},
                "name": {"type": ["string", "null"]},
                "schools": {"type": ["array", "null"], "items": {"type": "string"}},
                "employers": {"type": ["array", "null"], "items": {"type": "string"}},
                "location": {"type": ["string", "null"]},
                "tier": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
                "dependency_weight": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                "decision_nodes": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "org": {"type": "string"},
                            "role": {"type": "string"},
                            "start": {"type": ["string", "null"]},
                            "end": {"type": ["string", "null"]},
                        },
                        "required": ["org", "role", "start", "end"],
                    },
                },
                "platforms": {
                    "type": ["object", "null"],
                    "additionalProperties": {"type": "string"},
                },
                "societies": {
                    "type": ["object", "null"],
                    "additionalProperties": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "ecosystems": {"type": ["array", "null"], "items": {"type": "string"}},
                "family_friends_links": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "person_id": {"type": ["string", "null"]},
                            "relationship": {"type": "string"},
                            "alliance_signal": {"type": "boolean"},
                        },
                        "required": ["person_id", "relationship", "alliance_signal"],
                    },
                },
                "notes": {"type": ["string", "null"]},
            },
            "required": [
                "id",
                "name",
                "schools",
                "employers",
                "location",
                "tier",
                "dependency_weight",
                "decision_nodes",
                "platforms",
                "societies",
                "ecosystems",
                "family_friends_links",
                "notes",
            ],
        },
        "strict": True,
    }


def _merge_extracted_fields(
    *,
    primary: Dict[str, object],
    fallback: Dict[str, object],
) -> Dict[str, object]:
    merged: Dict[str, object] = {}
    for key in (
        "id",
        "name",
        "location",
        "schools",
        "employers",
        "notes",
        "tier",
        "dependency_weight",
    ):
        value = primary.get(key)
        if key in {"schools", "employers"}:
            merged[key] = fallback.get(key) if not value else value
        else:
            merged[key] = fallback.get(key) if value is None else value
    return merged


def _web_search_system_instruction(*, name_hint: str | None, id_hint: str | None) -> str:
    query_lines = _name_query_lines(name_hint=name_hint, id_hint=id_hint)
    query_plan = "\n".join(f"- {line}" for line in query_lines)
    return (
        "Extract a person profile from an image. Use null for unknown fields. "
        "Location must be a geographic place (city/state/country), never nationality, ethnicity, or a role. "
        "If id is unknown, create a lowercase snake_case id from the best full name guess.\n"
        "When web search is enabled, use this process:\n"
        "1) Read the visible name and any organization/location clues from the image.\n"
        "2) Use web_search to look up that person by name first.\n"
        "3) Run up to three quick targeted queries in this order:\n"
        f"{query_plan}\n"
        "4) Prefer authoritative profile pages and well-known publications.\n"
        "5) Populate schools and employers when sources clearly support them.\n"
        "6) Only fill fields supported by evidence from the image or search results.\n"
        "7) If identity is ambiguous, keep uncertain fields null."
    )


def _name_query_lines(*, name_hint: str | None, id_hint: str | None) -> List[str]:
    candidates: List[str] = []
    if name_hint and name_hint.strip():
        candidates.append(name_hint.strip())
    if id_hint and id_hint.strip():
        id_as_name = id_hint.replace("_", " ").strip()
        if id_as_name and id_as_name not in candidates:
            candidates.append(id_as_name)

    if not candidates:
        return [
            'If no name is visible, search only if there is a unique organization clue from the image',
            "If identity is still unclear after one query, return nulls for uncertain fields",
            "Do not guess identity when multiple people match",
        ]

    seed = candidates[0]
    return [
        f'"{seed}"',
        f'"{seed}" biography profile',
        f'"{seed}" location',
    ]


def _response_used_web_search(response_json: Dict[str, object]) -> bool:
    output_items = response_json.get("output")
    if not isinstance(output_items, list):
        return False
    for item in output_items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if isinstance(item_type, str) and "web_search" in item_type:
            return True
        content_items = item.get("content")
        if not isinstance(content_items, list):
            continue
        for content_item in content_items:
            if not isinstance(content_item, dict):
                continue
            annotations = content_item.get("annotations")
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue
                annotation_type = annotation.get("type")
                if isinstance(annotation_type, str) and "url_citation" in annotation_type:
                    return True
    return False


def _needs_name_follow_up(fields: Dict[str, object]) -> bool:
    location = fields.get("location")
    schools = fields.get("schools")
    employers = fields.get("employers")
    has_location = isinstance(location, str) and bool(location.strip())
    has_schools = isinstance(schools, list) and len(schools) > 0
    has_employers = isinstance(employers, list) and len(employers) > 0
    return not has_location or (not has_schools and not has_employers)


def _best_name_query(*, primary: Dict[str, object], fallback: Dict[str, object]) -> str | None:
    candidates = [
        primary.get("name"),
        fallback.get("name"),
        primary.get("id"),
        fallback.get("id"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = candidate.strip()
        if not cleaned:
            continue
        if "_" in cleaned and cleaned.lower() == cleaned:
            cleaned = cleaned.replace("_", " ")
        return cleaned
    return None


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
    raw_name = _clean_optional_string(extracted.get("name"))
    raw_id = _clean_optional_string(extracted.get("id"))
    return {
        "id": raw_id,
        "name": raw_name,
        "location": _clean_location(extracted.get("location")),
        "schools": _clean_optional_string_list(extracted.get("schools")),
        "employers": _clean_optional_string_list(extracted.get("employers")),
        "notes": _clean_optional_string(extracted.get("notes")),
        "tier": extracted.get("tier"),
        "dependency_weight": extracted.get("dependency_weight"),
    }


def _normalise_cleaned_person_fields(extracted: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": _clean_optional_string(extracted.get("id")),
        "name": _clean_optional_string(extracted.get("name")),
        "schools": _clean_optional_string_list(extracted.get("schools")),
        "employers": _clean_optional_string_list(extracted.get("employers")),
        "location": _clean_location(extracted.get("location")),
        "tier": _clean_optional_int_in_range(extracted.get("tier"), low=1, high=4),
        "dependency_weight": _clean_optional_int_in_range(
            extracted.get("dependency_weight"),
            low=1,
            high=5,
        ),
        "decision_nodes": _clean_decision_nodes(extracted.get("decision_nodes")),
        "platforms": _clean_string_map(extracted.get("platforms")),
        "societies": _clean_societies_map(extracted.get("societies")),
        "ecosystems": _clean_optional_string_list(extracted.get("ecosystems")),
        "family_friends_links": _clean_family_friends_links(extracted.get("family_friends_links")),
        "notes": _clean_optional_string(extracted.get("notes")),
    }


def _clean_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_optional_int_in_range(value: object, *, low: int, high: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed < low or parsed > high:
        return None
    return parsed


def _clean_decision_nodes(value: object) -> List[Dict[str, object]]:
    if not isinstance(value, list):
        return []
    cleaned: List[Dict[str, object]] = []
    for node in value:
        if not isinstance(node, dict):
            continue
        org = _clean_optional_string(node.get("org"))
        role = _clean_optional_string(node.get("role"))
        start = _clean_optional_string(node.get("start"))
        end = _clean_optional_string(node.get("end"))
        if start:
            try:
                date.fromisoformat(start)
            except ValueError:
                start = None
        if end:
            try:
                date.fromisoformat(end)
            except ValueError:
                end = None
        if not org or not role:
            continue
        cleaned.append({"org": org, "role": role, "start": start, "end": end})
    return cleaned


def _clean_string_map(value: object) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    cleaned: Dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        clean_key = key.strip()
        clean_value = _clean_optional_string(raw)
        if not clean_key or clean_value is None:
            continue
        cleaned[clean_key] = clean_value
    return cleaned


def _clean_societies_map(value: object) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    cleaned: Dict[str, int] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        clean_key = key.strip()
        rank = _clean_optional_int_in_range(raw, low=1, high=5)
        if not clean_key or rank is None:
            continue
        cleaned[clean_key] = rank
    return cleaned


def _clean_family_friends_links(value: object) -> List[Dict[str, object]]:
    if not isinstance(value, list):
        return []
    cleaned: List[Dict[str, object]] = []
    seen: set[tuple[str | None, str, bool]] = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        person_id = _clean_optional_string(entry.get("person_id"))
        relationship = _clean_optional_string(entry.get("relationship"))
        alliance_signal = bool(entry.get("alliance_signal"))
        if relationship is None:
            continue
        key = (person_id, relationship, alliance_signal)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "person_id": person_id,
                "relationship": relationship,
                "alliance_signal": alliance_signal,
            }
        )
    return cleaned


def _fallback_fields_for_name(name_query: str) -> Dict[str, object]:
    cleaned_name = _clean_optional_string(name_query) or ""
    return {
        "id": _slugify_name(cleaned_name) if cleaned_name else None,
        "name": cleaned_name or None,
        "location": None,
        "schools": [],
        "employers": [],
        "notes": None,
        "tier": None,
        "dependency_weight": None,
    }


def _clean_optional_string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    cleaned_values: List[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_values.append(cleaned)
    return cleaned_values


def _clean_location(value: object) -> str | None:
    cleaned = _clean_optional_string(value)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    tokens = re.findall(r"[a-zA-Z]+", lowered)
    if any(token in LOCATION_ROLE_WORDS for token in tokens):
        return None
    if "-" in lowered and any(lowered.endswith(suffix) for suffix in DEMONYM_SUFFIXES):
        return None
    if any(lowered == suffix for suffix in DEMONYM_SUFFIXES):
        return None
    return cleaned


def _slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "unknown_person"


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
