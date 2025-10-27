from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional

from .graph import SocGraph
from .models import PersonNode
from .pathfinding import CostStrategy, depth_limited_path, dijkstra_shortest_path
from .storage import load_graph_csv, load_graph_json, save_graph_csv, save_graph_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Soc-Climb graph")
    parser.add_argument(
        "command",
        choices=["add-person", "add-connection", "shortest-path", "filter"],
        help="Operation to run",
    )
    parser.add_argument("--json", dest="json_path", help="Path to JSON graph snapshot")
    parser.add_argument("--nodes-csv", dest="nodes_csv", help="Path to CSV file containing people")
    parser.add_argument("--edges-csv", dest="edges_csv", help="Path to CSV file containing edges")
    parser.add_argument("--no-persist", action="store_true", help="Skip persisting changes")
    parser.add_argument("--algorithm", choices=["dfs", "dijkstra"], default="dijkstra", help="Shortest path algorithm")
    parser.add_argument("--depth-limit", type=int, default=23, help="Depth limit for DFS")
    parser.add_argument(
        "--strategy",
        choices=[s.value for s in CostStrategy],
        default=CostStrategy.DYNAMIC.value,
        help="Weight-to-cost conversion strategy",
    )
    parser.add_argument("--fixed-high", type=float, default=100.0, help="Upper bound when using fixed strategy")
    parser.add_argument("--id", dest="person_id", help="Person identifier")
    parser.add_argument("--name", help="Person name")
    parser.add_argument("--school", action="append", help="School affiliation (repeatable)")
    parser.add_argument("--employer", action="append", help="Employer affiliation (repeatable)")
    parser.add_argument("--society", action="append", help="Society affiliation (repeatable)")
    parser.add_argument("--location", help="Location label")
    parser.add_argument("--grad-year", type=int, help="Graduation year")
    parser.add_argument("--platform", action="append", help="Platform handle in platform=value format")
    parser.add_argument("--status-score", type=float, help="Status score override")
    parser.add_argument("--source", help="Source node id for edges and path queries")
    parser.add_argument("--target", help="Target node id for edges and path queries")
    parser.add_argument("--weight", type=float, help="Weight delta for connections")
    parser.add_argument("--context", action="append", help="Edge context in key=value format (repeatable)")
    parser.add_argument("--asymmetric", action="store_true", help="Create a directed edge only")
    parser.add_argument("--filter-school", help="Filter by school membership")
    parser.add_argument("--filter-employer", help="Filter by employer membership")
    parser.add_argument("--filter-society", help="Filter by society membership")
    parser.add_argument("--filter-location", help="Filter by location")
    parser.add_argument("--filter-grad-year", type=int, help="Filter by graduation year")
    parser.add_argument("--filter-name", help="Filter by exact name match")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    graph = _load_graph(args)

    if args.command == "add-person":
        _handle_add_person(graph, args)
    elif args.command == "add-connection":
        _handle_add_connection(graph, args)
    elif args.command == "shortest-path":
        _handle_shortest_path(graph, args)
    elif args.command == "filter":
        _handle_filter(graph, args)

    if not args.no_persist and args.command in {"add-person", "add-connection"}:
        _persist_graph(graph, args)


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
        school=args.school or [],
        employers=args.employer or [],
        societies=args.society or [],
        location=args.location,
        grad_year=args.grad_year,
        platforms=_parse_kv_list(args.platform),
        status_score=args.status_score,
    )
    graph.add_person(person, overwrite=True)
    print(json.dumps({"status": "ok", "person": person.to_dict()}, indent=2))


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


def _handle_shortest_path(graph: SocGraph, args: argparse.Namespace) -> None:
    if not args.source or not args.target:
        raise SystemExit("--source and --target are required for shortest-path")
    strategy = CostStrategy(args.strategy)
    if args.algorithm == "dfs":
        result = depth_limited_path(
            graph,
            args.source,
            args.target,
            depth_limit=args.depth_limit,
            strategy=strategy,
            fixed_high=args.fixed_high,
        )
    else:
        result = dijkstra_shortest_path(
            graph,
            args.source,
            args.target,
            strategy=strategy,
            fixed_high=args.fixed_high,
        )
    if not result:
        print(json.dumps({"status": "not_found"}, indent=2))
        return
    print(json.dumps(result.as_dict(), indent=2))


def _handle_filter(graph: SocGraph, args: argparse.Namespace) -> None:
    criteria: Dict[str, object] = {}
    if args.filter_school:
        criteria["school"] = args.filter_school
    if args.filter_employer:
        criteria["employers"] = args.filter_employer
    if args.filter_society:
        criteria["societies"] = args.filter_society
    if args.filter_location:
        criteria["location"] = args.filter_location
    if args.filter_grad_year is not None:
        criteria["grad_year"] = args.filter_grad_year
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
            continue
        key, value = entry.split("=", 1)
        if key:
            result[key] = value
    return result


def _parse_contexts(entries: Optional[list[str]]) -> Dict[str, float]:
    if not entries:
        return {}
    contexts: Dict[str, float] = {}
    for entry in entries:
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key:
            contexts[key] = float(value)
    return contexts


if __name__ == "__main__":
    main()
