"""Smoke tests proving the spec is served and every operation is wired.

Operations answer 501 until their service method is implemented; replace these
with real tests as you go. Readiness may be 503 when no database is reachable.
"""

from starlette.testclient import TestClient

BASE = "/api/v1"


def test_spec_is_served(client: TestClient) -> None:
    assert client.get(f"{BASE}/openapi.json").status_code == 200


def test_get_livez_is_wired(client: TestClient) -> None:
    assert client.get(f"{BASE}/status/livez").status_code == 200


def test_get_readyz_is_wired(client: TestClient) -> None:
    assert client.get(f"{BASE}/status/readyz").status_code in (200, 503)


def test_list_widgets_is_wired(client: TestClient) -> None:
    assert client.get(f"{BASE}/widgets").status_code in (200, 501)
