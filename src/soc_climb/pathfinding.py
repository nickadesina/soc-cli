from __future__ import annotations

import heapq
from dataclasses import dataclass
from math import inf, isfinite
from typing import Dict, List, Optional, Sequence

from .graph import SocGraph


@dataclass
class PathNode:
    id: str
    name: str
    degree: int
    tier: int | None
    dependency_weight: int
    metadata: Dict[str, object]


@dataclass
class PathEdge:
    source: str
    target: str
    weight: float
    cost: float
    contexts: Dict[str, float]


@dataclass
class PathResult:
    node_ids: List[str]
    nodes: List[PathNode]
    edges: List[PathEdge]
    total_cost: float
    total_strength: float

    def as_dict(self) -> Dict[str, object]:
        return {
            "nodes": [node.__dict__ for node in self.nodes],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "weight": edge.weight,
                    "cost": edge.cost,
                    "contexts": edge.contexts,
                }
                for edge in self.edges
            ],
            "total_cost": self.total_cost,
            "total_strength": self.total_strength,
        }


def dijkstra_shortest_path(
    graph: SocGraph,
    start: str,
    goal: str,
) -> Optional[PathResult]:
    """Weighted shortest path where lower edge distances are cheaper to traverse.

    Person metadata (for example tier/dependency_weight) is descriptive-only
    and does not change traversal cost.
    """

    graph.ensure_person(start)
    graph.ensure_person(goal)
    queue: List[tuple[float, str]] = [(0.0, start)]
    best_cost: Dict[str, float] = {start: 0.0}
    predecessor: Dict[str, str] = {}

    while queue:
        cost_so_far, node = heapq.heappop(queue)
        if cost_so_far > best_cost.get(node, inf):
            continue
        if node == goal:
            break
        for neighbor, weight in graph.adjacency.get(node, {}).items():
            edge_cost = _edge_cost(weight)
            if edge_cost == inf:
                continue
            new_cost = cost_so_far + edge_cost
            if new_cost < best_cost.get(neighbor, inf):
                best_cost[neighbor] = new_cost
                predecessor[neighbor] = node
                heapq.heappush(queue, (new_cost, neighbor))
    else:
        return None

    node_path: List[str] = [goal]
    while node_path[-1] != start:
        parent = predecessor.get(node_path[-1])
        if parent is None:
            return None
        node_path.append(parent)
    node_path.reverse()
    return _build_path_result(graph, node_path)


def _edge_cost(weight: float) -> float:
    if not isfinite(weight) or weight <= 0:
        return inf
    return float(weight)


def _build_path_result(graph: SocGraph, nodes: Sequence[str]) -> PathResult:
    edges: List[PathEdge] = []
    total_cost = 0.0
    total_strength = 0.0
    for i in range(len(nodes) - 1):
        source = nodes[i]
        target = nodes[i + 1]
        weight = graph.get_edge_weight(source, target)
        if weight is None:
            raise ValueError(f"Missing edge from {source} to {target}")
        cost = _edge_cost(weight)
        total_cost += cost
        total_strength += weight
        edges.append(
            PathEdge(
                source=source,
                target=target,
                weight=weight,
                cost=cost,
                contexts=graph.edge_contexts(source, target),
            )
        )
    payload_nodes: List[PathNode] = []
    for node_id in nodes:
        person = graph.get_person(node_id)
        payload_nodes.append(
            PathNode(
                id=node_id,
                name=person.name,
                degree=graph.degree(node_id),
                tier=person.tier,
                dependency_weight=person.dependency_weight,
                metadata={
                    "schools": list(person.schools),
                    "employers": list(person.employers),
                    "societies": dict(person.societies),
                    "location": person.location,
                    "decision_nodes": [node.__dict__ for node in person.decision_nodes],
                    "platforms": dict(person.platforms),
                    "ecosystems": list(person.ecosystems),
                    "family_friends_links": [node.__dict__ for node in person.family_friends_links],
                    "notes": person.notes,
                },
            )
        )
    return PathResult(
        node_ids=list(nodes),
        nodes=payload_nodes,
        edges=edges,
        total_cost=total_cost,
        total_strength=total_strength,
    )
