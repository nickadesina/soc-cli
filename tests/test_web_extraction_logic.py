import pytest
from fastapi import HTTPException

import soc_climb.web as web_module


def test_extract_person_fields_web_search_falls_back_to_image_only(monkeypatch) -> None:
    expected = {
        "id": "fallback_person",
        "name": "Fallback Person",
        "location": None,
        "schools": [],
        "employers": [],
        "notes": None,
        "tier": None,
        "dependency_weight": None,
    }

    def fake_web_search_extract(
        _image_bytes: bytes,
        _image_mime: str,
        *,
        name_hint: str | None = None,
        id_hint: str | None = None,
    ):
        raise HTTPException(status_code=502, detail="simulated web-search failure")

    def fake_image_only_extract(_image_bytes: bytes, _image_mime: str):
        return expected

    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_image_with_web_search",
        fake_web_search_extract,
    )
    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_name_with_web_search",
        lambda _name_query: (_ for _ in ()).throw(
            HTTPException(status_code=502, detail="name-retry-failed")
        ),
    )
    monkeypatch.setattr(web_module, "_extract_person_fields_from_image", fake_image_only_extract)

    payload = web_module._extract_person_fields(b"img", "image/png", web_search=True)

    assert payload["fields"] == expected
    assert payload["web_search_used"] is False
    assert payload["web_search_fallback"] is True
    assert "image-only extraction" in payload["warning"]


def test_extract_person_fields_web_search_success(monkeypatch) -> None:
    image_only = {
        "id": "jane_doe",
        "name": "Jane Doe",
        "location": "San Francisco",
        "schools": [],
        "employers": [],
        "notes": None,
        "tier": None,
        "dependency_weight": None,
    }
    web_enriched = {
        "id": "jane_doe",
        "name": "Jane Doe",
        "location": "San Francisco",
        "schools": ["Stanford University"],
        "employers": ["PayPal"],
        "notes": "Co-founder and former CEO of PayPal.",
        "tier": 2,
        "dependency_weight": 3,
    }

    captured_hints: dict[str, str | None] = {"name": None, "id": None}

    def fake_image_only_extract(_image_bytes: bytes, _image_mime: str):
        return image_only

    def fake_web_search_extract(
        _image_bytes: bytes,
        _image_mime: str,
        *,
        name_hint: str | None = None,
        id_hint: str | None = None,
    ):
        captured_hints["name"] = name_hint
        captured_hints["id"] = id_hint
        return web_enriched

    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_image_with_web_search",
        fake_web_search_extract,
    )
    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_name_with_web_search",
        lambda _name_query: {},
    )
    monkeypatch.setattr(web_module, "_extract_person_fields_from_image", fake_image_only_extract)

    payload = web_module._extract_person_fields(b"img", "image/png", web_search=True)

    assert payload["fields"] == {
        "id": "jane_doe",
        "name": "Jane Doe",
        "location": "San Francisco",
        "schools": ["Stanford University"],
        "employers": ["PayPal"],
        "notes": "Co-founder and former CEO of PayPal.",
        "tier": 2,
        "dependency_weight": 3,
    }
    assert payload["web_search_used"] is True
    assert "web_search_fallback" not in payload
    assert captured_hints == {"name": "Jane Doe", "id": "jane_doe"}


def test_extract_person_fields_non_retryable_web_search_error_is_raised(monkeypatch) -> None:
    def fake_image_only_extract(_image_bytes: bytes, _image_mime: str):
        return {
            "id": "name_from_image",
            "name": "Name From Image",
            "location": None,
            "schools": [],
            "employers": [],
            "notes": None,
            "tier": None,
            "dependency_weight": None,
        }

    def fake_web_search_extract(
        _image_bytes: bytes,
        _image_mime: str,
        *,
        name_hint: str | None = None,
        id_hint: str | None = None,
    ):
        raise HTTPException(status_code=400, detail="bad request")

    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_image_with_web_search",
        fake_web_search_extract,
    )
    monkeypatch.setattr(web_module, "_extract_person_fields_from_image", fake_image_only_extract)

    with pytest.raises(HTTPException, match="bad request"):
        web_module._extract_person_fields(b"img", "image/png", web_search=True)


def test_name_query_lines_prefers_image_name_then_targeted_queries() -> None:
    lines = web_module._name_query_lines(name_hint="Ada Lovelace", id_hint="ada_lovelace")
    assert lines == [
        '"Ada Lovelace"',
        '"Ada Lovelace" biography profile',
        '"Ada Lovelace" location',
    ]


def test_clean_location_rejects_demonym_role_text() -> None:
    assert (
        web_module._clean_location("German-American entrepreneur and former CEO of PayPal")
        is None
    )
    assert web_module._clean_location("San Francisco, California, United States") == (
        "San Francisco, California, United States"
    )


def test_extract_person_fields_uses_name_search_retry_when_initial_enrichment_is_weak(
    monkeypatch,
) -> None:
    image_only = {
        "id": "peter_thiel",
        "name": "Peter Thiel",
        "location": None,
        "schools": [],
        "employers": [],
        "notes": None,
        "tier": None,
        "dependency_weight": None,
    }
    weak_web = {
        "id": "peter_thiel",
        "name": "Peter Thiel",
        "location": None,
        "schools": [],
        "employers": [],
        "notes": None,
        "tier": None,
        "dependency_weight": None,
    }
    name_retry = {
        "id": "peter_thiel",
        "name": "Peter Thiel",
        "location": "Los Angeles, California, United States",
        "schools": ["Stanford University"],
        "employers": ["PayPal"],
        "notes": "Co-founded PayPal.",
        "tier": None,
        "dependency_weight": None,
    }

    monkeypatch.setattr(web_module, "_extract_person_fields_from_image", lambda *_args: image_only)
    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_image_with_web_search",
        lambda *_args, **_kwargs: weak_web,
    )
    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_name_with_web_search",
        lambda _name_query: name_retry,
    )

    payload = web_module._extract_person_fields(b"img", "image/png", web_search=True)
    assert payload["web_search_used"] is True
    assert payload["fields"]["location"] == "Los Angeles, California, United States"
    assert payload["fields"]["schools"] == ["Stanford University"]
    assert payload["fields"]["employers"] == ["PayPal"]


def test_extract_person_fields_from_name_query_uses_web_search_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_name_with_web_search",
        lambda name_query: {
            "id": "peter_thiel",
            "name": name_query,
            "location": "Los Angeles, California, United States",
            "schools": ["Stanford University"],
            "employers": ["PayPal"],
            "notes": "Co-founded PayPal.",
            "tier": None,
            "dependency_weight": None,
        },
    )

    payload = web_module._extract_person_fields_from_name_query(
        "Peter Thiel",
        web_search=True,
    )
    assert payload["web_search_used"] is True
    assert payload["name_query_used"] is True
    assert payload["fields"]["name"] == "Peter Thiel"
    assert payload["fields"]["id"] == "peter_thiel"


def test_extract_person_fields_from_name_query_returns_fallback_when_web_search_off() -> None:
    payload = web_module._extract_person_fields_from_name_query(
        "Peter Thiel",
        web_search=False,
    )
    assert payload["web_search_used"] is False
    assert payload["web_search_fallback"] is True
    assert payload["name_query_used"] is True
    assert payload["fields"]["id"] == "peter_thiel"
    assert payload["fields"]["name"] == "Peter Thiel"


def test_normalise_cleaned_person_fields_enforces_schema() -> None:
    cleaned = web_module._normalise_cleaned_person_fields(
        {
            "id": " peter_thiel ",
            "name": " Peter Thiel ",
            "schools": ["Stanford University", "Stanford University", ""],
            "employers": ["PayPal", " Founders Fund "],
            "location": "German-American entrepreneur",
            "tier": 9,
            "dependency_weight": "2",
            "decision_nodes": [
                {"org": "PayPal", "role": "CEO", "start": "1999-01-01", "end": None},
                {"org": "", "role": "Bad", "start": "oops", "end": "oops"},
            ],
            "platforms": {"x": "@thiel", "": "@bad"},
            "societies": {"club": 2, "bad": 9},
            "ecosystems": ["fintech", "fintech"],
            "family_friends_links": [
                {"person_id": "elon_musk", "relationship": "friend", "alliance_signal": True},
                {"person_id": "elon_musk", "relationship": "friend", "alliance_signal": True},
            ],
            "notes": " Investor ",
        }
    )

    assert cleaned["id"] == "peter_thiel"
    assert cleaned["name"] == "Peter Thiel"
    assert cleaned["schools"] == ["Stanford University"]
    assert cleaned["employers"] == ["PayPal", "Founders Fund"]
    assert cleaned["location"] is None
    assert cleaned["tier"] is None
    assert cleaned["dependency_weight"] == 2
    assert cleaned["societies"] == {"club": 2}
    assert cleaned["ecosystems"] == ["fintech"]
    assert cleaned["family_friends_links"] == [
        {"person_id": "elon_musk", "relationship": "friend", "alliance_signal": True}
    ]
    assert cleaned["notes"] == "Investor"


def test_clean_fields_endpoint_returns_cleaned_payload(monkeypatch) -> None:
    app = web_module.create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/clean-fields"
    )
    endpoint = route.endpoint

    monkeypatch.setattr(
        web_module,
        "_clean_fields_with_model",
        lambda fields: {"id": "peter_thiel", "name": "Peter Thiel"},
    )

    payload = web_module.CleanFieldsPayload(fields={"name": "Peter Thiel"})
    result = endpoint(payload)
    assert result == {
        "status": "ok",
        "fields": {"id": "peter_thiel", "name": "Peter Thiel"},
    }


def test_extract_observability_flags_defaults() -> None:
    flags = web_module._extract_observability_flags(
        {},
        image_used=False,
        name_query_provided=False,
    )
    assert flags == {
        "image_used": False,
        "name_query_used": False,
        "web_search_used": False,
        "web_search_retry": False,
        "web_search_fallback": False,
    }


def test_extract_observability_flags_from_payload_and_request_context() -> None:
    flags = web_module._extract_observability_flags(
        {
            "web_search_used": True,
            "web_search_retry": True,
            "web_search_fallback": False,
            "name_query_used": False,
        },
        image_used=True,
        name_query_provided=True,
    )
    assert flags == {
        "image_used": True,
        "name_query_used": True,
        "web_search_used": True,
        "web_search_retry": True,
        "web_search_fallback": False,
    }
