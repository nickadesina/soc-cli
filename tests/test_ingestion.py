from soc_climb import (
    EdgeEvent,
    GraphIngestionService,
    PersonEvent,
    PersonNode,
    SocGraph,
)


def test_graph_ingestion_service_merges_events():
    graph = SocGraph()
    service = GraphIngestionService(graph)
    events = [
        PersonEvent(person=PersonNode(id="alice")),
        PersonEvent(person=PersonNode(id="bob")),
        EdgeEvent(source="alice", target="bob", weight_delta=1.0, contexts={"school": 1.0}),
    ]
    service.apply(events)

    assert graph.get_edge_weight("alice", "bob") == 1.0
    assert graph.edge_contexts("alice", "bob") == {"school": 1.0}


def test_ingestion_helpers_support_manual_updates():
    graph = SocGraph()
    service = GraphIngestionService(graph)

    service.apply_person(PersonNode(id="carol"))
    service.apply_person(PersonNode(id="dave"))
    service.apply_edge("carol", "dave", 2.0, contexts={"mutuals": 1.0})

    assert graph.get_edge_weight("carol", "dave") == 2.0
    assert graph.edge_contexts("carol", "dave") == {"mutuals": 1.0}
