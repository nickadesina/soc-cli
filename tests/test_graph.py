import pytest

from soc_climb import PersonNode, SocGraph


def test_add_person_and_connection():
    graph = SocGraph()
    alice = PersonNode(id="alice", schools=["Stanford"])
    bob = PersonNode(id="bob")
    graph.add_person(alice)
    graph.add_person(bob)

    graph.add_connection("alice", "bob", 2.5, contexts={"school": 1.0})

    assert graph.get_edge_weight("alice", "bob") == pytest.approx(2.5)
    assert graph.get_edge_weight("bob", "alice") == pytest.approx(2.5)
    assert graph.edge_contexts("alice", "bob") == {"school": 1.0}
    assert graph.max_weight() == pytest.approx(2.5)

    # Removing strength should drop the edge from the adjacency map.
    graph.add_connection("alice", "bob", -2.5)
    assert graph.get_edge_weight("alice", "bob") is None
    assert graph.max_weight() == pytest.approx(0.0)


def test_filter_people_by_school_and_tier():
    graph = SocGraph()
    graph.add_person(PersonNode(id="a", schools=["Stanford"], tier=1))
    graph.add_person(PersonNode(id="b", schools=["Stanford"], tier=2))
    graph.add_person(PersonNode(id="c", schools=["MIT"], tier=1))

    matches = graph.filter_people(schools="Stanford", tier=1)
    assert len(matches) == 1
    assert matches[0].id == "a"


def test_remove_person_drops_incident_edges():
    graph = SocGraph()
    for node_id in ("a", "b", "c"):
        graph.add_person(PersonNode(id=node_id))
    graph.add_connection("a", "b", 2.0)
    graph.add_connection("b", "c", 3.0)

    graph.remove_person("b")

    assert "b" not in graph.people
    assert graph.get_edge_weight("a", "b") is None
    assert graph.get_edge_weight("c", "b") is None


def test_remove_connection_drops_both_directions_by_default():
    graph = SocGraph()
    graph.add_person(PersonNode(id="a"))
    graph.add_person(PersonNode(id="b"))
    graph.add_connection("a", "b", 4.0)

    graph.remove_connection("a", "b")

    assert graph.get_edge_weight("a", "b") is None
    assert graph.get_edge_weight("b", "a") is None


def test_max_weight_recomputes_after_decrementing_top_edge():
    graph = SocGraph()
    for node_id in ("a", "b", "c"):
        graph.add_person(PersonNode(id=node_id))

    graph.add_connection("a", "b", 10.0)
    graph.add_connection("b", "c", 4.0)
    assert graph.max_weight() == pytest.approx(10.0)

    graph.add_connection("a", "b", -3.0)
    assert graph.get_edge_weight("a", "b") == pytest.approx(7.0)
    assert graph.max_weight() == pytest.approx(7.0)


@pytest.mark.parametrize("weight_delta", [float("nan"), float("inf"), float("-inf")])
def test_add_connection_rejects_non_finite_weight_delta(weight_delta: float):
    graph = SocGraph()
    graph.add_person(PersonNode(id="a"))
    graph.add_person(PersonNode(id="b"))

    with pytest.raises(ValueError, match="must be finite"):
        graph.add_connection("a", "b", weight_delta)


@pytest.mark.parametrize("context_delta", [float("nan"), float("inf"), float("-inf")])
def test_add_connection_rejects_non_finite_context_delta(context_delta: float):
    graph = SocGraph()
    graph.add_person(PersonNode(id="a"))
    graph.add_person(PersonNode(id="b"))

    with pytest.raises(ValueError, match="must be finite"):
        graph.add_connection("a", "b", 1.0, contexts={"school": context_delta})


def test_society_filter_supports_key_match():
    graph = SocGraph()
    graph.add_person(PersonNode(id="a", societies={"ivy_club": 2}))
    graph.add_person(PersonNode(id="b", societies={"other": 3}))

    matches = graph.filter_people(societies="ivy_club")
    assert len(matches) == 1
    assert matches[0].id == "a"
