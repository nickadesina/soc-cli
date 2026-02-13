import pytest
from fastapi import HTTPException

import soc_climb.web as web_module


def test_extract_person_fields_web_search_falls_back_to_image_only(monkeypatch) -> None:
    expected = {
        "id": "fallback_person",
        "name": "Fallback Person",
        "family": None,
        "location": None,
        "tier": None,
        "dependency_weight": None,
    }

    def fake_web_search_extract(_image_bytes: bytes, _image_mime: str):
        raise HTTPException(status_code=502, detail="simulated web-search failure")

    def fake_image_only_extract(_image_bytes: bytes, _image_mime: str):
        return expected

    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_image_with_web_search",
        fake_web_search_extract,
    )
    monkeypatch.setattr(web_module, "_extract_person_fields_from_image", fake_image_only_extract)

    payload = web_module._extract_person_fields(b"img", "image/png", web_search=True)

    assert payload["fields"] == expected
    assert payload["web_search_used"] is False
    assert payload["web_search_fallback"] is True
    assert "image-only extraction" in payload["warning"]


def test_extract_person_fields_web_search_success(monkeypatch) -> None:
    expected = {
        "id": "web_search_person",
        "name": "Web Search Person",
        "family": None,
        "location": None,
        "tier": None,
        "dependency_weight": None,
    }

    def fake_web_search_extract(_image_bytes: bytes, _image_mime: str):
        return expected

    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_image_with_web_search",
        fake_web_search_extract,
    )

    payload = web_module._extract_person_fields(b"img", "image/png", web_search=True)

    assert payload["fields"] == expected
    assert payload["web_search_used"] is True
    assert "web_search_fallback" not in payload


def test_extract_person_fields_non_retryable_web_search_error_is_raised(monkeypatch) -> None:
    def fake_web_search_extract(_image_bytes: bytes, _image_mime: str):
        raise HTTPException(status_code=400, detail="bad request")

    monkeypatch.setattr(
        web_module,
        "_extract_person_fields_from_image_with_web_search",
        fake_web_search_extract,
    )

    with pytest.raises(HTTPException, match="bad request"):
        web_module._extract_person_fields(b"img", "image/png", web_search=True)
