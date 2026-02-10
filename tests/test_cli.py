import json

import pytest

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
            "--tier",
            "1",
            "--dependency-weight",
            "2",
            "--society-rank",
            "club=2",
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


def test_cli_add_connection_reports_invalid_context_value(tmp_path, capsys):
    json_path = tmp_path / "graph.json"
    main(["add-person", "--json", str(json_path), "--id", "alice"])
    capsys.readouterr()
    main(["add-person", "--json", str(json_path), "--id", "bob"])
    capsys.readouterr()

    with pytest.raises(SystemExit, match="Invalid numeric context value"):
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
                "2",
                "--context",
                "school=oops",
            ]
        )


def test_cli_add_connection_reports_unknown_person(tmp_path):
    with pytest.raises(SystemExit, match="Unknown person id: alice"):
        main(
            [
                "add-connection",
                "--source",
                "alice",
                "--target",
                "bob",
                "--weight",
                "1.0",
            ]
        )


def test_cli_rejects_invalid_dependency_weight(tmp_path):
    json_path = tmp_path / "graph.json"

    with pytest.raises(SystemExit, match="dependency_weight must be between 1 and 5"):
        main(
            [
                "add-person",
                "--json",
                str(json_path),
                "--id",
                "alice",
                "--dependency-weight",
                "9",
            ]
        )


def test_cli_remove_connection(tmp_path, capsys):
    json_path = tmp_path / "graph.json"
    main(["add-person", "--json", str(json_path), "--id", "alice"])
    capsys.readouterr()
    main(["add-person", "--json", str(json_path), "--id", "bob"])
    capsys.readouterr()
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
            "2",
        ]
    )
    capsys.readouterr()

    main(
        [
            "remove-connection",
            "--json",
            str(json_path),
            "--source",
            "alice",
            "--target",
            "bob",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"

    main(
        [
            "shortest-path",
            "--json",
            str(json_path),
            "--source",
            "alice",
            "--target",
            "bob",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_found"
