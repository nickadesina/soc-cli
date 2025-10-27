from pathlib import Path

from soc_climb import (
    PersonNode,
    SocGraph,
    load_graph_csv,
    load_graph_json,
    save_graph_csv,
    save_graph_json,
)


def _build_graph() -> SocGraph:
    graph = SocGraph()
    graph.add_person(
        PersonNode(
            id="alice",
            name="Alice",
            school=["Stanford"],
            platforms={"linkedin": "alice"},
        )
    )
    graph.add_person(PersonNode(id="bob", employers=["OpenAI"]))
    graph.add_connection("alice", "bob", 2.0, contexts={"school": 1.0})
    return graph


def test_json_round_trip(tmp_path: Path):
    graph = _build_graph()
    target = tmp_path / "graph.json"
    save_graph_json(target, graph)

    loaded = load_graph_json(target)
    assert loaded.get_edge_weight("alice", "bob") == graph.get_edge_weight("alice", "bob")
    assert loaded.get_person("alice").name == "Alice"


def test_csv_round_trip(tmp_path: Path):
    graph = _build_graph()
    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    save_graph_csv(nodes, edges, graph)

    loaded = load_graph_csv(nodes, edges)
    assert loaded.get_edge_weight("alice", "bob") == graph.get_edge_weight("alice", "bob")
    assert loaded.get_person("alice").platforms == {"linkedin": "alice"}
