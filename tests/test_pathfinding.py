import pytest

from soc_climb import (
    CostStrategy,
    PersonNode,
    SocGraph,
    depth_limited_path,
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


def test_depth_limited_path_finds_route(sample_graph: SocGraph):
    result = depth_limited_path(sample_graph, "a", "d")
    assert result is not None
    assert result.node_ids[0] == "a"
    assert result.node_ids[-1] == "d"


def test_dijkstra_shortest_path_prefers_strong_edges(sample_graph: SocGraph):
    result = dijkstra_shortest_path(
        sample_graph,
        "a",
        "d",
        strategy=CostStrategy.DYNAMIC,
    )
    assert result is not None
    assert result.node_ids == ["a", "b", "d"]
    assert result.total_strength == pytest.approx(7.0)


def test_dijkstra_returns_none_when_unreachable(sample_graph: SocGraph):
    sample_graph.add_person(PersonNode(id="isolated"))
    assert dijkstra_shortest_path(sample_graph, "isolated", "a") is None
