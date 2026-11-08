import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def client() -> TestClient:
    test_client: TestClient = create_app(Settings()).test_client()
    return test_client
