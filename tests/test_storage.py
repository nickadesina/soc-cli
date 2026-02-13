import json
from pathlib import Path

import pytest

from soc_climb import (
    PersonNode,
    SocGraph,
    load_graph_csv,
    load_graph_json,
    save_graph_csv,
    save_graph_json,
)


CSV_HEADER = (
    "id,name,family,schools,employers,societies,location,tier,dependency_weight,"
    "decision_nodes,platforms,ecosystems,close_connections,family_links,notes"
)


def _build_graph() -> SocGraph:
    graph = SocGraph()
    graph.add_person(
        PersonNode(
            id="alice",
            name="Alice",
            schools=["Stanford"],
            platforms={"linkedin": "alice"},
            societies={"leadership_club": 2},
            dependency_weight=2,
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
    assert loaded.get_person("alice").societies == {"leadership_club": 2}


def test_csv_round_trip(tmp_path: Path):
    graph = _build_graph()
    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    save_graph_csv(nodes, edges, graph)

    loaded = load_graph_csv(nodes, edges)
    assert loaded.get_edge_weight("alice", "bob") == graph.get_edge_weight("alice", "bob")
    assert loaded.get_person("alice").platforms == {"linkedin": "alice"}
    assert loaded.get_person("alice").societies == {"leadership_club": 2}


def test_load_csv_rejects_non_finite_edge_weight(tmp_path: Path):
    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    nodes.write_text(
        "\n".join(
            [
                CSV_HEADER,
                "alice,Alice,,,,,, ,3,, ,,,,",
                "bob,Bob,,,,,, ,3,, ,,,,",
            ]
        ).replace(" ", ""),
        encoding="utf-8",
    )
    edges.write_text(
        "\n".join(
            [
                "source,target,weight,contexts",
                "alice,bob,nan,school=1",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Non-finite float for weight"):
        load_graph_csv(nodes, edges)


def test_load_csv_rejects_invalid_context_weight(tmp_path: Path):
    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    nodes.write_text(
        "\n".join(
            [
                CSV_HEADER,
                "alice,Alice,,,,,, ,3,, ,,,,",
                "bob,Bob,,,,,, ,3,, ,,,,",
            ]
        ).replace(" ", ""),
        encoding="utf-8",
    )
    edges.write_text(
        "\n".join(
            [
                "source,target,weight,contexts",
                "alice,bob,1.5,school=oops",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid float for context\\[school\\]"):
        load_graph_csv(nodes, edges)


def test_load_csv_rejects_invalid_dependency_weight(tmp_path: Path):
    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    nodes.write_text(
        "\n".join(
            [
                CSV_HEADER,
                "alice,Alice,,,,,,,6,,,,,,",
            ]
        ),
        encoding="utf-8",
    )
    edges.write_text("source,target,weight,contexts\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dependency_weight must be between 1 and 5"):
        load_graph_csv(nodes, edges)


def test_load_csv_rejects_invalid_society_rank(tmp_path: Path):
    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    nodes.write_text(
        "\n".join(
            [
                CSV_HEADER,
                "alice,Alice,,,,focus=inf,,3,3,,,,,,",
            ]
        ),
        encoding="utf-8",
    )
    edges.write_text("source,target,weight,contexts\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid int for map\\[focus\\]"):
        load_graph_csv(nodes, edges)


def test_load_json_converts_legacy_strength_weights_when_marker_missing(tmp_path: Path):
    target = tmp_path / "graph.json"
    target.write_text(
        json.dumps(
            {
                "people": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "edges": [
                    {"source": "a", "target": "b", "weight": 9},
                    {"source": "a", "target": "c", "weight": 3},
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_graph_json(target)
    assert loaded.get_edge_weight("a", "b") == pytest.approx(1.0)
    assert loaded.get_edge_weight("a", "c") == pytest.approx(8.0)


def test_load_json_preserves_distance_weights_when_marker_present(tmp_path: Path):
    target = tmp_path / "graph.json"
    target.write_text(
        json.dumps(
            {
                "edge_weight_model": "distance_v2",
                "people": [{"id": "a"}, {"id": "b"}],
                "edges": [{"source": "a", "target": "b", "weight": 7}],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_graph_json(target)
    assert loaded.get_edge_weight("a", "b") == pytest.approx(7.0)


def test_load_csv_converts_non_integer_legacy_strength_weights(tmp_path: Path):
    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    nodes.write_text(
        "\n".join(
            [
                CSV_HEADER,
                "a,Alice,,,,,, ,3,, ,,,,",
                "b,Bob,,,,,, ,3,, ,,,,",
            ]
        ).replace(" ", ""),
        encoding="utf-8",
    )
    edges.write_text(
        "\n".join(
            [
                "source,target,weight,contexts",
                "a,b,2.5,",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_graph_csv(nodes, edges)
    assert loaded.get_edge_weight("a", "b") == pytest.approx(1.0)
