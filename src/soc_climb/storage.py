from __future__ import annotations

import csv
import json
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
                "school",
                "employers",
                "societies",
                "location",
                "grad_year",
                "platforms",
                "status_score",
            ],
        )
        writer.writeheader()
        for person in graph.people.values():
            writer.writerow(
                {
                    "id": person.id,
                    "name": person.name or "",
                    "school": list_delimiter.join(person.school),
                    "employers": list_delimiter.join(person.employers),
                    "societies": list_delimiter.join(person.societies),
                    "location": person.location or "",
                    "grad_year": person.grad_year if person.grad_year is not None else "",
                    "platforms": list_delimiter.join(
                        f"{key}{kv_delimiter}{value}" for key, value in person.platforms.items()
                    ),
                    "status_score": person.status_score if person.status_score is not None else "",
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
                        name=row.get("name") or None,
                        school=_split_list(row.get("school"), list_delimiter),
                        employers=_split_list(row.get("employers"), list_delimiter),
                        societies=_split_list(row.get("societies"), list_delimiter),
                        location=row.get("location") or None,
                        grad_year=int(row["grad_year"]) if row.get("grad_year") else None,
                        platforms=_parse_platforms(row.get("platforms"), list_delimiter, kv_delimiter),
                        status_score=float(row["status_score"]) if row.get("status_score") else None,
                    )
                )
    if edges_file.exists():
        with edges_file.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                graph.add_connection(
                    row["source"],
                    row["target"],
                    float(row["weight"]),
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
    contexts: Dict[str, float] = {}
    if not value:
        return contexts
    for entry in value.split(list_delimiter):
        if kv_delimiter not in entry:
            continue
        key, val = entry.split(kv_delimiter, 1)
        if key:
            contexts[key] = float(val)
    return contexts
