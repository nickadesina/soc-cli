from __future__ import annotations

import csv
import json
from math import isfinite
from pathlib import Path
from typing import Dict, List

from .graph import SocGraph
from .models import PersonNode


def save_graph_json(path: str | Path, graph: SocGraph) -> None:
    path = Path(path)
    payload = {
        "people": [person.to_dict() for person in graph.people.values()],
        "edges": [
            {
                "source": source,
                "target": target,
                "weight": weight,
                "contexts": graph.edge_contexts(source, target),
            }
            for source, neighbors in graph.adjacency.items()
            for target, weight in neighbors.items()
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_graph_json(path: str | Path) -> SocGraph:
    path = Path(path)
    graph = SocGraph()
    if not path.exists():
        return graph
    data = json.loads(path.read_text(encoding="utf-8"))
    for person_payload in data.get("people", []):
        graph.add_person(PersonNode.from_dict(person_payload))
    for edge_payload in data.get("edges", []):
        graph.add_connection(
            edge_payload["source"],
            edge_payload["target"],
            edge_payload["weight"],
            contexts=edge_payload.get("contexts"),
            symmetric=False,
        )
    return graph


def save_graph_csv(
    nodes_path: str | Path,
    edges_path: str | Path,
    graph: SocGraph,
    list_delimiter: str = "|",
    kv_delimiter: str = "=",
) -> None:
    nodes_file = Path(nodes_path)
    edges_file = Path(edges_path)
    with nodes_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "name",
                "family",
                "schools",
                "employers",
                "societies",
                "location",
                "tier",
                "dependency_weight",
                "decision_nodes",
                "platforms",
                "ecosystems",
                "close_connections",
                "family_links",
                "notes",
            ],
        )
        writer.writeheader()
        for person in graph.people.values():
            writer.writerow(
                {
                    "id": person.id,
                    "name": person.name,
                    "family": person.family,
                    "schools": list_delimiter.join(person.schools),
                    "employers": list_delimiter.join(person.employers),
                    "societies": list_delimiter.join(
                        f"{key}{kv_delimiter}{value}" for key, value in person.societies.items()
                    ),
                    "location": person.location,
                    "tier": person.tier if person.tier is not None else "",
                    "dependency_weight": person.dependency_weight,
                    "decision_nodes": json.dumps([node.__dict__ for node in person.decision_nodes]),
                    "platforms": list_delimiter.join(
                        f"{key}{kv_delimiter}{value}" for key, value in person.platforms.items()
                    ),
                    "ecosystems": list_delimiter.join(person.ecosystems),
                    "close_connections": list_delimiter.join(person.close_connections),
                    "family_links": json.dumps([link.__dict__ for link in person.family_links]),
                    "notes": person.notes,
                }
            )
    with edges_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "target", "weight", "contexts"])
        writer.writeheader()
        for source, neighbors in graph.adjacency.items():
            for target, weight in neighbors.items():
                contexts = graph.edge_contexts(source, target)
                context_blob = list_delimiter.join(
                    f"{key}{kv_delimiter}{value}" for key, value in contexts.items()
                )
                writer.writerow(
                    {
                        "source": source,
                        "target": target,
                        "weight": weight,
                        "contexts": context_blob,
                    }
                )


def load_graph_csv(
    nodes_path: str | Path,
    edges_path: str | Path,
    list_delimiter: str = "|",
    kv_delimiter: str = "=",
) -> SocGraph:
    graph = SocGraph()
    nodes_file = Path(nodes_path)
    edges_file = Path(edges_path)
    if nodes_file.exists():
        with nodes_file.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                graph.add_person(
                    PersonNode(
                        id=row["id"],
                        name=row.get("name") or "",
                        family=row.get("family") or "",
                        schools=_split_list(row.get("schools"), list_delimiter),
                        employers=_split_list(row.get("employers"), list_delimiter),
                        societies=_parse_int_map(row.get("societies"), list_delimiter, kv_delimiter),
                        location=row.get("location") or "",
                        tier=int(row["tier"]) if row.get("tier") else None,
                        dependency_weight=int(row["dependency_weight"])
                        if row.get("dependency_weight")
                        else 3,
                        decision_nodes=_parse_json_list(row.get("decision_nodes"), field_name="decision_nodes"),
                        platforms=_parse_platforms(row.get("platforms"), list_delimiter, kv_delimiter),
                        ecosystems=_split_list(row.get("ecosystems"), list_delimiter),
                        close_connections=_split_list(row.get("close_connections"), list_delimiter),
                        family_links=_parse_json_list(
                            row.get("family_links"), field_name="family_links"
                        ),
                        notes=row.get("notes") or "",
                    )
                )
    if edges_file.exists():
        with edges_file.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                weight = _parse_required_float(row.get("weight"), field_name="weight")
                graph.add_connection(
                    row["source"],
                    row["target"],
                    weight,
                    contexts=_parse_contexts(row.get("contexts"), list_delimiter, kv_delimiter),
                    symmetric=False,
                )
    return graph


def _split_list(value: str | None, delimiter: str) -> List[str]:
    if not value:
        return []
    return [item for item in value.split(delimiter) if item]


def _parse_platforms(value: str | None, list_delimiter: str, kv_delimiter: str) -> Dict[str, str]:
    platforms: Dict[str, str] = {}
    if not value:
        return platforms
    for entry in value.split(list_delimiter):
        if kv_delimiter not in entry:
            continue
        key, val = entry.split(kv_delimiter, 1)
        if key:
            platforms[key] = val
    return platforms


def _parse_contexts(value: str | None, list_delimiter: str, kv_delimiter: str) -> Dict[str, float]:
    return _parse_float_map(value, list_delimiter, kv_delimiter, field_name_prefix="context")


def _parse_int_map(value: str | None, list_delimiter: str, kv_delimiter: str) -> Dict[str, int]:
    items: Dict[str, int] = {}
    if not value:
        return items
    for entry in value.split(list_delimiter):
        if kv_delimiter not in entry:
            continue
        key, val = entry.split(kv_delimiter, 1)
        if not key:
            continue
        try:
            items[key] = int(val)
        except ValueError as exc:
            raise ValueError(f"Invalid int for map[{key}]: {val!r}") from exc
    return items


def _parse_float_map(
    value: str | None,
    list_delimiter: str,
    kv_delimiter: str,
    field_name_prefix: str,
) -> Dict[str, float]:
    contexts: Dict[str, float] = {}
    if not value:
        return contexts
    for entry in value.split(list_delimiter):
        if kv_delimiter not in entry:
            continue
        key, val = entry.split(kv_delimiter, 1)
        if key:
            contexts[key] = _parse_required_float(val, field_name=f"{field_name_prefix}[{key}]")
    return contexts


def _parse_required_float(value: str | None, field_name: str) -> float:
    if value is None or value == "":
        raise ValueError(f"Missing required numeric value for {field_name}")
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid float for {field_name}: {value!r}") from exc
    if not isfinite(number):
        raise ValueError(f"Non-finite float for {field_name}: {value!r}")
    return number


def _parse_optional_float(value: str | None, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    return _parse_required_float(value, field_name=field_name)


def _parse_json_list(value: str | None, field_name: str) -> List[dict]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {field_name}: {value!r}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} must be a JSON list")
    if not all(isinstance(item, dict) for item in parsed):
        raise ValueError(f"{field_name} entries must be JSON objects")
    return parsed
