"""The take-home endpoints, run against the real tax engine (no database is touched)."""

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from app.adapters.inbound.take_home_calculations_adapter import TakeHomeCalculationsRequestAdapter
from app.application.ports.deductions import DeductionsUnavailableError
from app.application.services.take_home_calculations_service import TakeHomeCalculationsService
from app.domain.take_home import Deductions
from app.generated.handlers import Adapters
from app.main import build_adapters, create_app
from app.settings import Settings

BASE = "/api/v1"
COMPUTE = f"{BASE}/take-home-calculations:compute"
CAD = {
    "name": "ca/cad",
    "placement": "before",
    "singular": "CA$",
    "plural": "CA$",
    "spaced": False,
    "as_percentage": False,
}
PERCENT = {
    "name": "core/percent",
    "placement": "after",
    "singular": "%",
    "plural": "%",
    "spaced": False,
    "as_percentage": True,
}
MONTHS = {
    "name": "core/months",
    "placement": "after",
    "singular": "month",
    "plural": "months",
    "spaced": True,
    "as_percentage": False,
}


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
        "unit": CAD,
        "average_income_tax_rate": {"amount": "0.1642", "unit": PERCENT},
        "marginal_income_tax_rate": {"amount": "0.2965", "unit": PERCENT},
    }


def test_70000_in_ontario_2026_is_provisional(client: TestClient) -> None:
    body = compute(client, year=2026).json()
    assert body["take_home"] == "53786.25"
    assert body["provisional"] is True
    assert body["unit"] == CAD
    assert body["average_income_tax_rate"] == {"amount": "0.1591", "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": "0.2965", "unit": PERCENT}


@pytest.mark.parametrize(
    ("year", "average", "marginal"),
    [(2025, "0.1642", "0.2965"), (2026, "0.1591", "0.2965")],
)
def test_the_rates_are_also_in_the_response_with_the_trace(
    client: TestClient, year: int, average: str, marginal: str
) -> None:
    body = compute(client, year=year, include_trace=True).json()
    assert body["average_income_tax_rate"] == {"amount": average, "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": marginal, "unit": PERCENT}
    assert body["unit"] == CAD  # the money unit is unaffected
    assert body["trace"]


@pytest.mark.parametrize("year", [2025, 2026])
def test_every_trace_line_carries_its_unit_and_money_rows_the_top_level_one(
    client: TestClient, year: int
) -> None:
    body = compute(client, year=year, include_trace=True).json()
    lines = [line for entry in body["trace"] for line in entry["lines"]]
    assert all("unit" in line for line in lines)
    units = [line["unit"] for line in lines]
    assert units.count(body["unit"]) > 100  # the money rows
    assert None in units  # a figure without a unit is an explicit null
    assert set(map(str, filter(None, units))) <= {str(CAD), str(MONTHS), str(PERCENT)}
    assert MONTHS in units  # a count of months goes after the number
    assert PERCENT in units  # a rate is a fraction shown as a percentage


def test_the_ei_row_on_t2204_is_in_canadian_dollars(client: TestClient) -> None:
    trace = compute(client, include_trace=True).json()["trace"]
    (t2204,) = (entry for entry in trace if entry["form"] == "ca/t2204")
    rows = [line for line in t2204["lines"] if line["amount"] == "1077.48"]
    assert rows
    assert all(row["unit"] == CAD for row in rows)


def test_whole_dollar_salary_is_accepted(client: TestClient) -> None:
    assert compute(client, salary="70000").json()["salary"] == "70000.00"


def test_trace_is_grouped_by_form_and_only_when_asked(client: TestClient) -> None:
    trace = compute(client, include_trace=True).json()["trace"]
    forms = {entry["form"]: entry["lines"] for entry in trace}
    assert forms
    for lines in forms.values():
        for line in lines:
            assert line["text"]
            assert set(line) == {"label", "name", "reference", "amount", "text", "unit"}
    labels = [line["label"] for lines in forms.values() for line in lines]
    assert any(label is not None for label in labels)
    lines = [line for entry in forms.values() for line in entry]
    assert any(line["name"] is None for line in lines)  # absent is an explicit null
    assert "trace" not in compute(client).json()


def test_every_trace_form_has_a_display_name(client: TestClient) -> None:
    trace = compute(client, include_trace=True).json()["trace"]
    names = {entry["form"]: entry["name"] for entry in trace}
    assert names["ca/schedule_8"].startswith("Schedule 8")
    assert names["ca-on/on428"] == "Form ON428: Ontario Tax"
    lines = {
        line["label"]: line.get("name")
        for entry in trace
        if entry["form"] == "ca-on/on428"
        for line in entry["lines"]
    }
    assert lines["on428_surtax_total_line_68"] == "Ontario surtax"
    references = {
        line["label"]: line.get("reference")
        for entry in trace
        if entry["form"] == "ca-on/on428"
        for line in entry["lines"]
    }
    assert references["on428_surtax_total_line_68"] == "68"
    assert all(names.values())
    assert sum(name != form for form, name in names.items()) >= 7  # all but the untitled


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"jurisdiction_code": "CA-QC"}, "jurisdiction_code"),
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
                "name": "Ontario",
                "years": [
                    {"year": 2025, "provisional": False},
                    {"year": 2026, "provisional": True},
                ],
            },
            {
                "code": "CA-AB",
                "name": "Alberta",
                "years": [
                    {"year": 2025, "provisional": False},
                    {"year": 2026, "provisional": True},
                ],
            },
            {
                "code": "CA-BC",
                "name": "British Columbia",
                "years": [
                    {"year": 2025, "provisional": False},
                    {"year": 2026, "provisional": True},
                ],
            },
            {
                "code": "CA-MB",
                "name": "Manitoba",
                "years": [
                    {"year": 2025, "provisional": False},
                    {"year": 2026, "provisional": True},
                ],
            },
            {
                "code": "CA-SK",
                "name": "Saskatchewan",
                "years": [
                    {"year": 2025, "provisional": False},
                    {"year": 2026, "provisional": True},
                ],
            },
            {
                "code": "CA-NL",
                "name": "Newfoundland and Labrador",
                "years": [
                    {"year": 2025, "provisional": False},
                    {"year": 2026, "provisional": True},
                ],
            },
        ],
        "next_page_token": "",
    }


def test_jurisdictions_rejects_a_page_token(client: TestClient) -> None:
    response = client.get(f"{BASE}/jurisdictions", params={"page_token": "x"})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["field"] == "page_token"


def test_a_failed_calculation_is_a_500_problem() -> None:
    class Failing:
        async def calculate(self, *args: Any) -> Deductions:
            raise DeductionsUnavailableError("CA-ON 2025: KeyError")

    def build(settings: Settings, engine: AsyncEngine) -> Adapters:
        return replace(
            build_adapters(settings, engine),
            take_home_calculations=TakeHomeCalculationsRequestAdapter(
                TakeHomeCalculationsService(Failing())
            ),
        )

    client = create_app(Settings(), build).test_client()
    response = compute(client)
    assert response.status_code == 500
    assert response.json()["title"] == "Calculation failed"
    assert "KeyError" not in response.json()["detail"]


def test_the_first_unsupported_value_is_the_one_named(client: TestClient) -> None:
    # Checked in this order: salary, jurisdiction_code, year, then the language.
    assert compute(client, salary="0.00", year=2024).json()["field"] == "salary"
    assert (
        compute(client, jurisdiction_code="CA-QC", year=2024).json()["field"] == "jurisdiction_code"
    )
    assert compute(client, year=2024, language_code="fr").json()["field"] == "year"


# Alberta: (year, salary, total_deductions, take_home, average rate, marginal rate)
ALBERTA = [
    (2025, "20000.00", "1467.84", "18532.16", "0.0079", "0.145"),
    (2025, "70000.00", "16217.99", "53782.01", "0.1598", "0.305"),
    (2025, "200000.00", "62655.68", "137344.32", "0.2857", "0.42"),
    (2026, "20000.00", "1411.24", "18588.76", "0.0052", "0.14"),
    (2026, "70000.00", "15892.80", "54107.20", "0.1545", "0.305"),
    (2026, "200000.00", "62146.34", "137853.66", "0.2819", "0.42"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(("year", "salary", "total", "take_home", "average", "marginal"), ALBERTA)
def test_alberta_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    take_home: str,
    average: str,
    marginal: str,
    trace: bool,
) -> None:
    response = compute(
        client, jurisdiction_code="CA-AB", year=year, salary=salary, include_trace=trace
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_deductions"] == total
    assert body["take_home"] == take_home
    assert body["provisional"] is (year == 2026)
    assert body["unit"] == CAD
    assert body["average_income_tax_rate"] == {"amount": average, "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": marginal, "unit": PERCENT}
    assert ("trace" in body) is trace
    if trace:
        assert "ca-ab/return" in {entry["form"] for entry in body["trace"]}


def test_ontario_70000_is_unchanged_by_alberta(client: TestClient) -> None:
    assert compute(client).json()["take_home"] == "53468.68"


# British Columbia: (year, salary, total_deductions, take_home, average rate, marginal rate)
BRITISH_COLUMBIA = [
    (2025, "20000.00", "1467.84", "18532.16", "0.0079", "0.145"),
    (2025, "70000.00", "15782.26", "54217.74", "0.1535", "0.282"),
    (2025, "275000.00", "100064.57", "174935.43", "0.3438", "0.535"),
    (2026, "20000.00", "1411.24", "18588.76", "0.0052", "0.14"),
    (2026, "70000.00", "15651.85", "54348.15", "0.1510", "0.282"),
    (2026, "275000.00", "99175.26", "175824.74", "0.3397", "0.535"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "take_home", "average", "marginal"), BRITISH_COLUMBIA
)
def test_british_columbia_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    take_home: str,
    average: str,
    marginal: str,
    trace: bool,
) -> None:
    response = compute(
        client, jurisdiction_code="CA-BC", year=year, salary=salary, include_trace=trace
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_deductions"] == total
    assert body["take_home"] == take_home
    assert body["provisional"] is (year == 2026)
    assert body["unit"] == CAD
    assert body["average_income_tax_rate"] == {"amount": average, "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": marginal, "unit": PERCENT}
    assert ("trace" in body) is trace
    if trace:
        assert "ca-bc/return" in {entry["form"] for entry in body["trace"]}


def test_british_columbia_is_not_offered_in_a_year_it_lacks(client: TestClient) -> None:
    response = compute(client, jurisdiction_code="CA-BC", year=2024)
    assert response.status_code == 400
    assert response.json()["field"] == "year"


def test_ontario_70000_is_unchanged_by_british_columbia(client: TestClient) -> None:
    assert compute(client).json()["take_home"] == "53468.68"


# Manitoba: (year, salary, total_deductions, take_home, average rate, marginal rate)
MANITOBA = [
    (2025, "20000.00", "1751.92", "18248.08", "0.0221", "0.253"),
    (2025, "70000.00", "18367.46", "51632.54", "0.1905", "0.3325"),
    (2025, "275000.00", "108255.71", "166744.29", "0.3736", "0.5125212"),
    (2026, "20000.00", "1695.54", "18304.46", "0.0194", "0.248"),
    (2026, "70000.00", "18100.68", "51899.32", "0.1860", "0.3325"),
    (2026, "275000.00", "107698.76", "167301.24", "0.3707", "0.5125212"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(("year", "salary", "total", "take_home", "average", "marginal"), MANITOBA)
def test_manitoba_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    take_home: str,
    average: str,
    marginal: str,
    trace: bool,
) -> None:
    response = compute(
        client, jurisdiction_code="CA-MB", year=year, salary=salary, include_trace=trace
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_deductions"] == total
    assert body["take_home"] == take_home
    assert body["provisional"] is (year == 2026)
    assert body["unit"] == CAD
    assert body["average_income_tax_rate"] == {"amount": average, "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": marginal, "unit": PERCENT}
    assert ("trace" in body) is trace
    if trace:
        assert "ca-mb/return" in {entry["form"] for entry in body["trace"]}


def test_manitoba_is_not_offered_in_a_year_it_lacks(client: TestClient) -> None:
    response = compute(client, jurisdiction_code="CA-MB", year=2024)
    assert response.status_code == 400
    assert response.json()["field"] == "year"


# Saskatchewan: (year, salary, total_deductions, take_home, average rate, marginal rate)
SASKATCHEWAN = [
    (2025, "20000.00", "1467.84", "18532.16", "0.0079", "0.145"),
    (2025, "70000.00", "17712.17", "52287.83", "0.1811", "0.33"),
    (2025, "275000.00", "100795.15", "174204.85", "0.3465", "0.475"),
    (2026, "20000.00", "1411.24", "18588.76", "0.0052", "0.14"),
    (2026, "70000.00", "17330.69", "52669.31", "0.1750", "0.33"),
    (2026, "275000.00", "100064.89", "174935.11", "0.3429", "0.475"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "take_home", "average", "marginal"), SASKATCHEWAN
)
def test_saskatchewan_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    take_home: str,
    average: str,
    marginal: str,
    trace: bool,
) -> None:
    response = compute(
        client, jurisdiction_code="CA-SK", year=year, salary=salary, include_trace=trace
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_deductions"] == total
    assert body["take_home"] == take_home
    assert body["provisional"] is (year == 2026)
    assert body["unit"] == CAD
    assert body["average_income_tax_rate"] == {"amount": average, "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": marginal, "unit": PERCENT}
    assert ("trace" in body) is trace
    if trace:
        assert "ca-sk/return" in {entry["form"] for entry in body["trace"]}


def test_saskatchewan_is_not_offered_in_a_year_it_lacks(client: TestClient) -> None:
    response = compute(client, jurisdiction_code="CA-SK", year=2024)
    assert response.status_code == 400
    assert response.json()["field"] == "year"


# Newfoundland and Labrador: (year, salary, total_deductions, take_home, average, marginal)
NEWFOUNDLAND = [
    (2025, "20000.00", "1467.84", "18532.16", "0.0079", "0.232"),
    (2025, "70000.00", "18767.36", "51232.64", "0.1962", "0.35"),
    (2025, "275000.00", "109314.88", "165685.12", "0.3775", "0.528"),
    (2026, "20000.00", "1411.24", "18588.76", "0.0052", "0.227"),
    (2026, "70000.00", "18297.00", "51703.00", "0.1888", "0.35"),
    (2026, "275000.00", "108460.99", "166539.01", "0.3734", "0.528"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "take_home", "average", "marginal"), NEWFOUNDLAND
)
def test_newfoundland_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    take_home: str,
    average: str,
    marginal: str,
    trace: bool,
) -> None:
    response = compute(
        client, jurisdiction_code="CA-NL", year=year, salary=salary, include_trace=trace
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_deductions"] == total
    assert body["take_home"] == take_home
    assert body["provisional"] is (year == 2026)
    assert body["unit"] == CAD
    assert body["average_income_tax_rate"] == {"amount": average, "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": marginal, "unit": PERCENT}
    assert ("trace" in body) is trace
    if trace:
        assert "ca-nl/return" in {entry["form"] for entry in body["trace"]}


def test_newfoundland_is_not_offered_in_a_year_it_lacks(client: TestClient) -> None:
    response = compute(client, jurisdiction_code="CA-NL", year=2024)
    assert response.status_code == 400
    assert response.json()["field"] == "year"


def test_ontario_70000_is_unchanged_by_manitoba_and_saskatchewan(client: TestClient) -> None:
    assert compute(client).json()["take_home"] == "53468.68"


def test_ontario_70000_is_unchanged_by_newfoundland(client: TestClient) -> None:
    assert compute(client).json()["take_home"] == "53468.68"


def test_alberta_is_not_offered_in_a_year_it_lacks(client: TestClient) -> None:
    response = compute(client, jurisdiction_code="CA-AB", year=2024)
    assert response.status_code == 400
    assert response.json()["field"] == "year"
