"""Smoke tests proving the spec is served and every operation is wired.

Readiness depends on nothing external (no database), so it answers 200 anywhere.
"""

from starlette.testclient import TestClient

from app.main import create_app
from app.settings import Settings

BASE = "/api/v1"


def test_spec_is_served(client: TestClient) -> None:
    assert client.get(f"{BASE}/openapi.json").status_code == 200


def test_get_livez_is_wired(client: TestClient) -> None:
    assert client.get(f"{BASE}/status/livez").status_code == 200


def test_get_readyz_is_ready_without_a_database() -> None:
    unreachable = Settings(database_url="postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none")
    client: TestClient = create_app(unreachable).test_client()
    assert client.get(f"{BASE}/status/readyz").status_code == 200
