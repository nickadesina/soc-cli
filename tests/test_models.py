from soc_climb import PersonNode


def test_person_node_from_dict_ignores_legacy_decision_node_scope():
    person = PersonNode.from_dict(
        {
            "id": "alice",
            "decision_nodes": [
                {
                    "org": "OpenAI",
                    "role": "Policy",
                    "scope": "global",
                    "start": "2024-01-01",
                    "end": None,
                }
            ],
        }
    )

    decision_node = person.to_dict()["decision_nodes"][0]
    assert decision_node == {
        "org": "OpenAI",
        "role": "Policy",
        "start": "2024-01-01",
        "end": None,
    }
    assert "scope" not in decision_node
