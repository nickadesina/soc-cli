import pytest

from soc_climb import (
    PersonNode,
    SocGraph,
    dijkstra_shortest_path,
)


@pytest.fixture
def sample_graph() -> SocGraph:
    graph = SocGraph()
    for node_id in ("a", "b", "c", "d"):
        graph.add_person(PersonNode(id=node_id))
    graph.add_connection("a", "b", 5.0, symmetric=True)
    graph.add_connection("b", "c", 3.0, symmetric=True)
    graph.add_connection("a", "c", 1.0, symmetric=True)
    graph.add_connection("c", "d", 4.0, symmetric=True)
    graph.add_connection("b", "d", 2.0, symmetric=True)
    return graph


def test_dijkstra_shortest_path_prefers_strong_edges(sample_graph: SocGraph):
    result = dijkstra_shortest_path(sample_graph, "a", "d")
    assert result is not None
    assert result.node_ids == ["a", "b", "d"]
    assert result.total_strength == pytest.approx(7.0)
    assert result.total_cost == pytest.approx(0.7)


def test_dijkstra_returns_none_when_unreachable(sample_graph: SocGraph):
    sample_graph.add_person(PersonNode(id="isolated"))
    assert dijkstra_shortest_path(sample_graph, "isolated", "a") is None


def test_dijkstra_ignores_tier_and_dependency_weight_for_cost():
    graph = SocGraph()
    graph.add_person(PersonNode(id="start"))
    graph.add_person(PersonNode(id="stronger", tier=4, dependency_weight=5))
    graph.add_person(PersonNode(id="weaker", tier=1, dependency_weight=1))
    graph.add_person(PersonNode(id="goal"))

    graph.add_connection("start", "stronger", 2.0, symmetric=False)
    graph.add_connection("stronger", "goal", 2.0, symmetric=False)
    graph.add_connection("start", "weaker", 1.8, symmetric=False)
    graph.add_connection("weaker", "goal", 1.8, symmetric=False)

    result = dijkstra_shortest_path(graph, "start", "goal")
    assert result is not None
    assert result.node_ids == ["start", "stronger", "goal"]
    assert result.total_cost == pytest.approx(1.0)
