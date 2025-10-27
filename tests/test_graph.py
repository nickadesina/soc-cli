import pytest

from soc_climb import PersonNode, SocGraph


def test_add_person_and_connection():
    graph = SocGraph()
    alice = PersonNode(id="alice", school=["Stanford"])
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


def test_filter_people_by_school_and_grad_year():
    graph = SocGraph()
    graph.add_person(PersonNode(id="a", school=["Stanford"], grad_year=2023))
    graph.add_person(PersonNode(id="b", school=["Stanford"], grad_year=2024))
    graph.add_person(PersonNode(id="c", school=["MIT"], grad_year=2023))

    matches = graph.filter_people(school="Stanford", grad_year=2023)
    assert len(matches) == 1
    assert matches[0].id == "a"
