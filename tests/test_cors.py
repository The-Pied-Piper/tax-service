"""CORS: the API answers browser requests from configured website origins only."""

from starlette.testclient import TestClient

from app.main import create_app
from app.settings import Settings

URL = "/api/v1/status/livez"
SITE = "https://aftertaxlens.com"
DEV_SITE = "https://dev.aftertaxlens.com"


def _client(origins: str) -> TestClient:
    client: TestClient = create_app(Settings(cors_allowed_origins=origins)).test_client()
    return client


def test_allowed_origin_gets_the_header() -> None:
    response = _client(f"{SITE},{DEV_SITE}").get(URL, headers={"Origin": DEV_SITE})
    assert response.headers["access-control-allow-origin"] == DEV_SITE


def test_other_origin_does_not() -> None:
    response = _client(SITE).get(URL, headers={"Origin": "https://example.org"})
    assert "access-control-allow-origin" not in response.headers


def test_preflight_from_allowed_origin_is_answered() -> None:
    response = _client(SITE).options(
        URL,
        headers={
            "Origin": SITE,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == SITE


def test_no_origins_configured_means_no_header() -> None:
    response = _client("").get(URL, headers={"Origin": SITE})
    assert "access-control-allow-origin" not in response.headers
