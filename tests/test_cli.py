import json

from soc_climb.cli import main


def test_cli_add_and_query(tmp_path, capsys):
    json_path = tmp_path / "graph.json"

    main(
        [
            "add-person",
            "--json",
            str(json_path),
            "--id",
            "alice",
            "--name",
            "Alice",
            "--school",
            "Stanford",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"

    main(
        [
            "add-person",
            "--json",
            str(json_path),
            "--id",
            "bob",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["person"]["id"] == "bob"

    main(
        [
            "add-connection",
            "--json",
            str(json_path),
            "--source",
            "alice",
            "--target",
            "bob",
            "--weight",
            "3.0",
            "--context",
            "school=1",
        ]
    )
    edge_payload = json.loads(capsys.readouterr().out)
    assert edge_payload["edge"]["weight"] == 3.0

    main([
        "shortest-path",
        "--json",
        str(json_path),
        "--source",
        "alice",
        "--target",
        "bob",
    ])
    path_payload = json.loads(capsys.readouterr().out)
    assert path_payload["nodes"][0]["id"] == "alice"

    main([
        "filter",
        "--json",
        str(json_path),
        "--filter-school",
        "Stanford",
    ])
    results = json.loads(capsys.readouterr().out)
    assert results[0]["id"] == "alice"
