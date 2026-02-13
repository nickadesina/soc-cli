from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path
from typing import Dict, Optional

from .auto_edges import upsert_person_with_auto_edges
from .graph import SocGraph
from .models import PersonNode
from .pathfinding import dijkstra_shortest_path
from .storage import load_graph_csv, load_graph_json, save_graph_csv, save_graph_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Soc-Climb graph")
    parser.add_argument(
        "command",
        choices=[
            "add-person",
            "remove-person",
            "add-connection",
            "remove-connection",
            "shortest-path",
            "filter",
        ],
        help="Operation to run",
    )
    parser.add_argument("--json", dest="json_path", help="Path to JSON graph snapshot")
    parser.add_argument("--nodes-csv", dest="nodes_csv", help="Path to CSV file containing people")
    parser.add_argument("--edges-csv", dest="edges_csv", help="Path to CSV file containing edges")
    parser.add_argument("--no-persist", action="store_true", help="Skip persisting changes")
    parser.add_argument("--id", dest="person_id", help="Person identifier")
    parser.add_argument("--name", default="", help="Person name")
    parser.add_argument("--school", action="append", help="School affiliation (repeatable)")
    parser.add_argument("--employer", action="append", help="Employer affiliation (repeatable)")
    parser.add_argument(
        "--society-rank",
        action="append",
        help="Society rank in society=rank format (rank 1-5, 1 strongest)",
    )
    parser.add_argument("--location", default="", help="Location label")
    parser.add_argument("--tier", type=int, help="Tier value (1 highest, 4 lowest)")
    parser.add_argument(
        "--dependency-weight",
        type=int,
        default=3,
        help="Dependency weight (1 strongest, 5 weakest)",
    )
    parser.add_argument(
        "--decision-node",
        action="append",
        help="Decision node JSON object with org/role/start/end",
    )
    parser.add_argument("--platform", action="append", help="Platform handle in platform=value format")
    parser.add_argument("--ecosystem", action="append", help="Ecosystem label (repeatable)")
    parser.add_argument(
        "--family-friends-link",
        action="append",
        help="Family/friends link JSON object with person_id/relationship/alliance_signal",
    )
    parser.add_argument("--notes", default="", help="Free-form notes")
    parser.add_argument(
        "--auto-top-k",
        type=int,
        help="Optional cap for inferred auto-edges during add-person",
    )
    parser.add_argument("--source", help="Source node id for edges and path queries")
    parser.add_argument("--target", help="Target node id for edges and path queries")
    parser.add_argument("--weight", type=float, help="Weight delta for connections")
    parser.add_argument("--context", action="append", help="Edge context in key=value format (repeatable)")
    parser.add_argument("--asymmetric", action="store_true", help="Create a directed edge only")
    parser.add_argument("--filter-school", help="Filter by school membership")
    parser.add_argument("--filter-employer", help="Filter by employer membership")
    parser.add_argument("--filter-society", help="Filter by society membership key")
    parser.add_argument("--filter-location", help="Filter by location")
    parser.add_argument("--filter-tier", type=int, help="Filter by tier value")
    parser.add_argument("--filter-name", help="Filter by exact name match")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        graph = _load_graph(args)

        if args.command == "add-person":
            _handle_add_person(graph, args)
        elif args.command == "remove-person":
            _handle_remove_person(graph, args)
        elif args.command == "add-connection":
            _handle_add_connection(graph, args)
        elif args.command == "remove-connection":
            _handle_remove_connection(graph, args)
        elif args.command == "shortest-path":
            _handle_shortest_path(graph, args)
        elif args.command == "filter":
            _handle_filter(graph, args)

        if not args.no_persist and args.command in {
            "add-person",
            "remove-person",
            "add-connection",
            "remove-connection",
        }:
            _persist_graph(graph, args)
    except (KeyError, ValueError) as exc:
        raise SystemExit(_format_user_error(exc)) from exc


def _load_graph(args: argparse.Namespace) -> SocGraph:
    if args.json_path and Path(args.json_path).exists():
        return load_graph_json(args.json_path)
    if (
        args.nodes_csv
        and args.edges_csv
        and Path(args.nodes_csv).exists()
        and Path(args.edges_csv).exists()
    ):
        return load_graph_csv(args.nodes_csv, args.edges_csv)
    return SocGraph()


def _persist_graph(graph: SocGraph, args: argparse.Namespace) -> None:
    if args.json_path:
        save_graph_json(args.json_path, graph)
    if args.nodes_csv and args.edges_csv:
        save_graph_csv(args.nodes_csv, args.edges_csv, graph)


def _handle_add_person(graph: SocGraph, args: argparse.Namespace) -> None:
    if not args.person_id:
        raise SystemExit("--id is required for add-person")
    person = PersonNode(
        id=args.person_id,
        name=args.name,
        schools=args.school or [],
        employers=args.employer or [],
        societies=_parse_society_rank_map(args.society_rank),
        location=args.location,
        tier=args.tier,
        dependency_weight=args.dependency_weight,
        decision_nodes=_parse_json_object_list(args.decision_node, "decision node"),
        platforms=_parse_kv_list(args.platform),
        ecosystems=args.ecosystem or [],
        family_friends_links=_parse_json_object_list(
            args.family_friends_link,
            "family/friends link",
        ),
        notes=args.notes,
    )
    auto_edges = upsert_person_with_auto_edges(
        graph,
        person,
        overwrite=True,
        top_k=args.auto_top_k,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "person": person.to_dict(),
                "auto_edges": auto_edges,
            },
            indent=2,
        )
    )


def _handle_remove_person(graph: SocGraph, args: argparse.Namespace) -> None:
    if not args.person_id:
        raise SystemExit("--id is required for remove-person")
    graph.remove_person(args.person_id)
    print(json.dumps({"status": "ok", "person_id": args.person_id}, indent=2))


def _handle_add_connection(graph: SocGraph, args: argparse.Namespace) -> None:
    if not args.source or not args.target or args.weight is None:
        raise SystemExit("--source, --target and --weight are required for add-connection")
    contexts = _parse_contexts(args.context)
    graph.add_connection(
        args.source,
        args.target,
        args.weight,
        contexts=contexts,
        symmetric=not args.asymmetric,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "edge": {
                    "source": args.source,
                    "target": args.target,
                    "weight": graph.get_edge_weight(args.source, args.target),
                    "contexts": graph.edge_contexts(args.source, args.target),
                },
            },
            indent=2,
        )
    )


def _handle_remove_connection(graph: SocGraph, args: argparse.Namespace) -> None:
    if not args.source or not args.target:
        raise SystemExit("--source and --target are required for remove-connection")
    graph.remove_connection(args.source, args.target, symmetric=not args.asymmetric)
    print(
        json.dumps(
            {
                "status": "ok",
                "source": args.source,
                "target": args.target,
                "symmetric": not args.asymmetric,
            },
            indent=2,
        )
    )


def _handle_shortest_path(graph: SocGraph, args: argparse.Namespace) -> None:
    if not args.source or not args.target:
        raise SystemExit("--source and --target are required for shortest-path")
    result = dijkstra_shortest_path(graph, args.source, args.target)
    if not result:
        print(json.dumps({"status": "not_found"}, indent=2))
        return
    print(json.dumps(result.as_dict(), indent=2))


def _handle_filter(graph: SocGraph, args: argparse.Namespace) -> None:
    criteria: Dict[str, object] = {}
    if args.filter_school:
        criteria["schools"] = args.filter_school
    if args.filter_employer:
        criteria["employers"] = args.filter_employer
    if args.filter_society:
        criteria["societies"] = args.filter_society
    if args.filter_location:
        criteria["location"] = args.filter_location
    if args.filter_tier is not None:
        criteria["tier"] = args.filter_tier
    if args.filter_name:
        criteria["name"] = args.filter_name
    matches = [person.to_dict() for person in graph.filter_people(**criteria)]
    print(json.dumps(matches, indent=2))


def _parse_kv_list(entries: Optional[list[str]]) -> Dict[str, str]:
    if not entries:
        return {}
    result: Dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Invalid entry {entry!r}; expected key=value format")
        key, value = entry.split("=", 1)
        if not key:
            raise ValueError(f"Invalid entry {entry!r}; key cannot be empty")
        result[key] = value
    return result


def _parse_contexts(entries: Optional[list[str]]) -> Dict[str, float]:
    if not entries:
        return {}
    contexts: Dict[str, float] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Invalid context {entry!r}; expected key=value format")
        key, value = entry.split("=", 1)
        if not key:
            raise ValueError(f"Invalid context {entry!r}; key cannot be empty")
        try:
            context_value = float(value)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric context value for {key!r}: {value!r}") from exc
        if not isfinite(context_value):
            raise ValueError(f"Non-finite context value for {key!r}: {value!r}")
        contexts[key] = context_value
    return contexts


def _parse_society_rank_map(entries: Optional[list[str]]) -> Dict[str, int]:
    if not entries:
        return {}
    societies: Dict[str, int] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Invalid society rank {entry!r}; expected key=value format")
        key, value = entry.split("=", 1)
        if not key:
            raise ValueError(f"Invalid society rank {entry!r}; key cannot be empty")
        try:
            rank = int(value)
        except ValueError as exc:
            raise ValueError(f"Invalid rank for {key!r}: {value!r}") from exc
        if not 1 <= rank <= 5:
            raise ValueError(f"Rank for {key!r} must be between 1 and 5, got {rank!r}")
        societies[key] = rank
    return societies


def _parse_json_object_list(entries: Optional[list[str]], label: str) -> list[dict]:
    if not entries:
        return []
    parsed: list[dict] = []
    for entry in entries:
        try:
            value = json.loads(entry)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid {label} JSON: {entry!r}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Invalid {label}; expected a JSON object")
        parsed.append(value)
    return parsed


def _format_user_error(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


if __name__ == "__main__":
    main()
