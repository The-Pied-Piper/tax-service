"""The take-home endpoints, run against the real tax engine (no database is touched)."""

from typing import Any

import pytest
from starlette.testclient import TestClient

BASE = "/api/v1"
COMPUTE = f"{BASE}/take-home-calculations:compute"


def compute(client: TestClient, **overrides: Any) -> Any:
    body = {"jurisdiction_code": "CA-ON", "year": 2025, "salary": "70000.00"} | overrides
    return client.post(COMPUTE, json=body)


def test_70000_in_ontario_2025(client: TestClient) -> None:
    response = compute(client)
    assert response.status_code == 200
    assert response.json() == {
        "salary": "70000.00",
        "total_deductions": "16531.32",
        "take_home": "53468.68",
        "provisional": False,
        "trace": None,
    }


def test_70000_in_ontario_2026_is_provisional(client: TestClient) -> None:
    body = compute(client, year=2026).json()
    assert body["take_home"] == "53786.25"
    assert body["provisional"] is True


def test_whole_dollar_salary_is_accepted(client: TestClient) -> None:
    assert compute(client, salary="70000").json()["salary"] == "70000.00"


def test_trace_is_grouped_by_form_and_only_when_asked(client: TestClient) -> None:
    trace = compute(client, include_trace=True).json()["trace"]
    forms = {entry["form"]: entry["lines"] for entry in trace}
    assert forms
    for lines in forms.values():
        for line in lines:
            assert line["text"]
            assert set(line) == {"label", "amount", "text"}
    labels = [line["label"] for lines in forms.values() for line in lines]
    assert any(label is not None for label in labels)
    assert compute(client).json()["trace"] is None


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"jurisdiction_code": "CA-AB"}, "jurisdiction_code"),
        ({"year": 2024}, "year"),
        ({"salary": "0.00"}, "salary"),
        ({"language_code": "fr"}, "language_code"),
    ],
)
def test_unsupported_values_name_the_field(
    client: TestClient, overrides: dict[str, Any], field: str
) -> None:
    response = compute(client, **overrides)
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["field"] == field


def test_a_salary_the_engine_cannot_hold_is_a_400_naming_the_field(client: TestClient) -> None:
    response = compute(client, salary="99999999999999999999999.99")
    assert response.status_code == 400
    assert response.json()["field"] == "salary"


@pytest.mark.parametrize("salary", ["-5", "abc", "70000.123", ""])
def test_malformed_salary_is_a_400(client: TestClient, salary: str) -> None:
    assert compute(client, salary=salary).status_code == 400


def test_jurisdictions_list(client: TestClient) -> None:
    response = client.get(f"{BASE}/jurisdictions")
    assert response.status_code == 200
    assert response.json() == {
        "jurisdictions": [
            {
                "code": "CA-ON",
                "years": [
                    {"year": 2025, "provisional": False},
                    {"year": 2026, "provisional": True},
                ],
            }
        ],
        "next_page_token": "",
    }


def test_jurisdictions_rejects_a_page_token(client: TestClient) -> None:
    assert client.get(f"{BASE}/jurisdictions", params={"page_token": "x"}).status_code == 400
