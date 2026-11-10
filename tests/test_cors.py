"""CORS: the API answers browser requests from configured website origins only."""

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.main import create_app
from app.settings import Settings

URL = "/api/v1/status/livez"
SITE = "https://aftertaxlens.com"
DEV_SITE = "https://dev.aftertaxlens.com"
ALLOW = "access-control-allow-origin"


def _client(origins: list[str]) -> TestClient:
    client: TestClient = create_app(Settings(cors_allowed_origins=origins)).test_client()
    return client


def _preflight(client: TestClient, origin: str, method: str = "POST") -> int:
    response = client.options(
        URL,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )
    status: int = response.status_code
    return status


def test_allowed_origin_gets_the_header() -> None:
    response = _client([SITE, DEV_SITE]).get(URL, headers={"Origin": DEV_SITE})
    assert response.headers[ALLOW] == DEV_SITE
    assert response.headers["vary"] == "Origin"


def test_other_origin_does_not() -> None:
    response = _client([SITE]).get(URL, headers={"Origin": "https://example.org"})
    assert ALLOW not in response.headers


def test_error_responses_carry_the_header() -> None:
    client = _client([SITE])
    not_found = client.get("/api/v1/nowhere", headers={"Origin": SITE})
    wrong_method = client.delete(URL, headers={"Origin": SITE})
    assert (not_found.status_code, wrong_method.status_code) == (404, 405)
    assert not_found.headers[ALLOW] == SITE
    assert wrong_method.headers[ALLOW] == SITE


def test_preflight_from_allowed_origin_is_answered() -> None:
    response = _client([SITE]).options(
        URL,
        headers={
            "Origin": SITE,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers[ALLOW] == SITE


def test_preflight_from_other_origin_or_for_other_method_is_refused() -> None:
    client = _client([SITE])
    assert _preflight(client, "https://example.org") == 400
    assert _preflight(client, SITE, method="DELETE") == 400


def test_no_origins_configured_means_no_header() -> None:
    assert ALLOW not in _client([]).get(URL, headers={"Origin": SITE}).headers


def test_bad_request_carries_the_header() -> None:
    response = _client([SITE]).post(
        "/api/v1/take-home-calculations:compute", json={}, headers={"Origin": SITE}
    )
    assert response.status_code == 400
    assert response.headers[ALLOW] == SITE


def test_origins_are_split_and_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "APP_CORS_ALLOWED_ORIGINS",
        " HTTPS://AfterTaxLens.com/ , ,http://localhost:5173,https://aftertaxlens.com:443",
    )
    assert Settings().cors_allowed_origins == [SITE, "http://localhost:5173"]


BAD_ORIGINS = [
    "*",
    "https://*.a.com",
    "aftertaxlens.com",
    "https://a.com/path",
    '["https://a.com"]',
    "https://a.com;https://b.com",
    "https://a.com;b.com",
    "https://u:p@a.com",
    "https://a.com?x=1",
    "https://a.com#f",
    "https://a.com:notaport",
    "https://a.com:",
    "https://a .com",
]


@pytest.mark.parametrize("bad", BAD_ORIGINS)
def test_malformed_origins_stop_startup(bad: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_CORS_ALLOWED_ORIGINS", bad)
    with pytest.raises(ValidationError):
        Settings()


def test_a_list_is_checked_too() -> None:
    with pytest.raises(ValidationError):
        Settings(cors_allowed_origins=["*"])
