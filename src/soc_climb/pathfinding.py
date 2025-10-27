from __future__ import annotations

import heapq
from dataclasses import dataclass
from enum import Enum
from math import inf
from typing import Dict, List, Optional, Sequence

from .graph import SocGraph


class CostStrategy(str, Enum):
    """Strategies for converting weights into traversal costs."""

    DYNAMIC = "dynamic"  # cost = max_w - weight + 1
    INVERTED = "inverted"  # cost = 1 / weight
    FIXED = "fixed"  # cost after normalising into [1, fixed_high]


@dataclass
class PathNode:
    id: str
    name: Optional[str]
    degree: int
    status_score: Optional[float]
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


class CostComputer:
    """Encapsulates weight-to-cost conversion for reuse across algorithms."""

    def __init__(self, graph: SocGraph, strategy: CostStrategy, fixed_high: float = 100.0) -> None:
        self.strategy = strategy
        self.fixed_high = fixed_high
        self.max_weight = max(graph.max_weight(), 1.0)

    def edge_cost(self, weight: float) -> float:
        if weight <= 0:
            return inf
        if self.strategy == CostStrategy.INVERTED:
            return 1.0 / weight
        if self.strategy == CostStrategy.FIXED:
            normalised = (weight / self.max_weight) * self.fixed_high
            clamped = min(self.fixed_high, max(1.0, normalised))
            return (self.fixed_high - clamped) + 1.0
        effective_max = max(self.max_weight, weight)
        return (effective_max - weight) + 1.0


def depth_limited_path(
    graph: SocGraph,
    start: str,
    goal: str,
    depth_limit: int = 23,
    strategy: CostStrategy = CostStrategy.DYNAMIC,
    fixed_high: float = 100.0,
) -> Optional[PathResult]:
    """DFS with a configurable depth limit for unweighted exploration."""

    graph.ensure_person(start)
    graph.ensure_person(goal)
    computer = CostComputer(graph, strategy, fixed_high)
    path: List[str] = []
    visited: set[str] = set()

    def _dfs(current: str, depth: int) -> bool:
        if depth > depth_limit:
            return False
        path.append(current)
        visited.add(current)
        if current == goal:
            return True
        for neighbor, weight in graph.adjacency.get(current, {}).items():
            if neighbor in visited:
                continue
            if computer.edge_cost(weight) == inf:
                continue
            if _dfs(neighbor, depth + 1):
                return True
        path.pop()
        visited.remove(current)
        return False

    if not _dfs(start, 0):
        return None
    return _build_path_result(graph, path, computer)


def dijkstra_shortest_path(
    graph: SocGraph,
    start: str,
    goal: str,
    strategy: CostStrategy = CostStrategy.DYNAMIC,
    fixed_high: float = 100.0,
) -> Optional[PathResult]:
    """Weighted shortest path based on the configured cost strategy."""

    graph.ensure_person(start)
    graph.ensure_person(goal)
    computer = CostComputer(graph, strategy, fixed_high)
    queue: List[tuple[float, str, List[str]]] = [(0.0, start, [])]
    best_cost: Dict[str, float] = {}

    while queue:
        cost_so_far, node, trail = heapq.heappop(queue)
        if node in best_cost and cost_so_far >= best_cost[node]:
            continue
        best_cost[node] = cost_so_far
        new_trail = trail + [node]
        if node == goal:
            return _build_path_result(graph, new_trail, computer)
        for neighbor, weight in graph.adjacency.get(node, {}).items():
            edge_cost = computer.edge_cost(weight)
            if edge_cost == inf:
                continue
            heapq.heappush(queue, (cost_so_far + edge_cost, neighbor, new_trail))
    return None


def _build_path_result(graph: SocGraph, nodes: Sequence[str], computer: CostComputer) -> PathResult:
    edges: List[PathEdge] = []
    total_cost = 0.0
    total_strength = 0.0
    for i in range(len(nodes) - 1):
        source = nodes[i]
        target = nodes[i + 1]
        weight = graph.get_edge_weight(source, target)
        if weight is None:
            raise ValueError(f"Missing edge from {source} to {target}")
        cost = computer.edge_cost(weight)
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
                status_score=person.status_score,
                metadata={
                    "school": list(person.school),
                    "employers": list(person.employers),
                    "societies": list(person.societies),
                    "location": person.location,
                    "grad_year": person.grad_year,
                    "platforms": dict(person.platforms),
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
