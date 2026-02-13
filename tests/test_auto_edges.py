from datetime import date

from soc_climb import (
    DecisionNode,
    PersonNode,
    SocGraph,
    auto_connect_new_person,
    edge_distance_value,
    upsert_person_with_auto_edges,
)


def test_edge_distance_value_marks_explicit_ties_as_close() -> None:
    alice = PersonNode(id="alice", close_connections=["bob"])
    bob = PersonNode(id="bob")

    result = edge_distance_value(alice, bob, today=date(2026, 1, 1))
    assert result is not None
    distance, explicit = result
    assert explicit is True
    assert distance <= 2


def test_edge_distance_value_requires_relevance_for_inferred_links() -> None:
    alice = PersonNode(id="alice")
    bob = PersonNode(id="bob")

    assert edge_distance_value(alice, bob, today=date(2026, 1, 1)) is None


def test_edge_distance_value_uses_decision_node_overlap() -> None:
    alice = PersonNode(
        id="alice",
        decision_nodes=[DecisionNode(org="openai", role="research", start="2024-01-01", end=None)],
    )
    bob = PersonNode(
        id="bob",
        decision_nodes=[DecisionNode(org="openai", role="ops", start="2025-01-01", end=None)],
    )
    carol = PersonNode(
        id="carol",
        decision_nodes=[DecisionNode(org="other", role="ops", start="2025-01-01", end=None)],
    )

    overlap = edge_distance_value(alice, bob, today=date(2026, 1, 1))
    mismatch = edge_distance_value(alice, carol, today=date(2026, 1, 1))

    assert overlap is not None
    assert mismatch is None


def test_auto_connect_top_k_keeps_explicit_and_closest_inferred() -> None:
    graph = SocGraph()
    new_person = PersonNode(
        id="new",
        employers=["e1", "e2"],
        location="nyc",
        close_connections=["explicit"],
    )
    graph.add_person(new_person)
    graph.add_person(PersonNode(id="explicit"))
    graph.add_person(PersonNode(id="medium", employers=["e1"], location="nyc"))
    graph.add_person(PersonNode(id="close", employers=["e1", "e2"], location="nyc"))

    edges = auto_connect_new_person(new_person, graph, top_k=2, today=date(2026, 1, 1))

    assert "explicit" in edges
    assert "close" in edges
    assert "medium" not in edges


def test_upsert_person_with_auto_edges_replaces_incident_edges_on_overwrite() -> None:
    graph = SocGraph()
    graph.add_person(PersonNode(id="b"))
    upsert_person_with_auto_edges(
        graph,
        PersonNode(id="a", close_connections=["b"]),
        overwrite=True,
        today=date(2026, 1, 1),
    )
    assert graph.get_edge_weight("a", "b") is not None
    assert graph.get_edge_weight("b", "a") is not None

    upsert_person_with_auto_edges(
        graph,
        PersonNode(id="a"),
        overwrite=True,
        today=date(2026, 1, 1),
    )
    assert graph.get_edge_weight("a", "b") is None
    assert graph.get_edge_weight("b", "a") is None
