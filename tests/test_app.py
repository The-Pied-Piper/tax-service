"""Smoke tests proving the spec is served and every operation is wired.

Operations answer 501 until their service method is implemented; replace these
with real tests as you go. Readiness needs no database: Lambda has none.
"""

from starlette.testclient import TestClient

BASE = "/api/v1"


def test_spec_is_served(client: TestClient) -> None:
    assert client.get(f"{BASE}/openapi.json").status_code == 200


def test_get_livez_is_wired(client: TestClient) -> None:
    assert client.get(f"{BASE}/status/livez").status_code == 200


def test_get_readyz_is_ready_without_a_database(client: TestClient) -> None:
    assert client.get(f"{BASE}/status/readyz").status_code == 200
