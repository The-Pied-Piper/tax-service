"""The take-home endpoints, run against the real tax engine (no database is touched)."""

from dataclasses import replace
from decimal import Decimal
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
        "income_tax": "11497.09",
        "take_home": "53468.68",
        "provisional": False,
        "unit": CAD,
        "average_income_tax_rate": {"amount": "0.2362", "unit": PERCENT},
        "marginal_income_tax_rate": {"amount": "0.3434", "unit": PERCENT},
    }


def test_70000_in_ontario_2026_is_provisional(client: TestClient) -> None:
    body = compute(client, year=2026).json()
    assert body["take_home"] == "53786.25"
    assert body["provisional"] is True
    assert body["unit"] == CAD
    assert body["average_income_tax_rate"] == {"amount": "0.2316", "unit": PERCENT}
    assert body["marginal_income_tax_rate"] == {"amount": "0.3436", "unit": PERCENT}


@pytest.mark.parametrize(
    ("year", "average", "marginal"),
    [(2025, "0.2362", "0.3434"), (2026, "0.2316", "0.3436")],
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


# Alberta: (year, salary, total_deductions, income_tax, take_home, average rate, marginal rate)
ALBERTA = [
    (2025, "20000.00", "1467.84", "158.09", "18532.16", "0.0734", "0.2098945"),
    (2025, "70000.00", "16217.99", "11183.76", "53782.01", "0.2317", "0.3503125"),
    (2025, "200000.00", "62655.68", "57148.10", "137344.32", "0.3133", "0.4230542655"),
    (2026, "20000.00", "1411.24", "103.49", "18588.76", "0.0706", "0.205188"),
    (2026, "70000.00", "15892.80", "10812.98", "54107.20", "0.2270", "0.35056"),
    (2026, "200000.00", "62146.34", "56376.82", "137853.66", "0.3107", "0.422949296"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "income_tax", "take_home", "average", "marginal"), ALBERTA
)
def test_alberta_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    income_tax: str,
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
    assert body["income_tax"] == income_tax
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


# British Columbia: (year, salary, total_deductions, income_tax, take_home, average, marginal)
BRITISH_COLUMBIA = [
    (2025, "20000.00", "1467.84", "158.09", "18532.16", "0.0734", "0.2098945"),
    (2025, "70000.00", "15782.26", "10748.03", "54217.74", "0.2255", "0.3289978"),
    (2025, "275000.00", "100064.57", "94556.99", "174935.43", "0.3639", "0.535"),
    (2026, "20000.00", "1411.24", "103.49", "18588.76", "0.0706", "0.205188"),
    (2026, "70000.00", "15651.85", "10572.03", "54348.15", "0.2236", "0.328978"),
    (2026, "275000.00", "99175.26", "93405.74", "175824.74", "0.3606", "0.535"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "income_tax", "take_home", "average", "marginal"), BRITISH_COLUMBIA
)
def test_british_columbia_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    income_tax: str,
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
    assert body["income_tax"] == income_tax
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


# Manitoba: (year, salary, total_deductions, income_tax, take_home, average rate, marginal rate)
MANITOBA = [
    (2025, "20000.00", "1751.92", "442.17", "18248.08", "0.0876", "0.3193201"),
    (2025, "70000.00", "18367.46", "13333.23", "51632.54", "0.2624", "0.3761515"),
    (2025, "275000.00", "108255.71", "102748.13", "166744.29", "0.3937", "0.5125212"),
    (2026, "20000.00", "1695.54", "387.79", "18304.46", "0.0848", "0.3146244"),
    (2026, "70000.00", "18100.68", "13020.86", "51899.32", "0.2586", "0.376399"),
    (2026, "275000.00", "107698.76", "101929.24", "167301.24", "0.3916", "0.5125212"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "income_tax", "take_home", "average", "marginal"), MANITOBA
)
def test_manitoba_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    income_tax: str,
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
    assert body["income_tax"] == income_tax
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


# Saskatchewan: (year, salary, total_deductions, income_tax, take_home, average rate, marginal rate)
SASKATCHEWAN = [
    (2025, "20000.00", "1467.84", "158.09", "18532.16", "0.0734", "0.2098945"),
    (2025, "70000.00", "17712.17", "12677.94", "52287.83", "0.2530", "0.373825"),
    (2025, "275000.00", "100795.15", "95287.57", "174204.85", "0.3665", "0.475"),
    (2026, "20000.00", "1411.24", "103.49", "18588.76", "0.0706", "0.205188"),
    (2026, "70000.00", "17330.69", "12250.87", "52669.31", "0.2476", "0.3740725"),
    (2026, "275000.00", "100064.89", "94295.37", "174935.11", "0.3639", "0.475"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "income_tax", "take_home", "average", "marginal"), SASKATCHEWAN
)
def test_saskatchewan_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    income_tax: str,
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
    assert body["income_tax"] == income_tax
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


# Newfoundland and Labrador: (year, salary, total_deductions, income_tax, take_home, avg, marginal)
NEWFOUNDLAND = [
    (2025, "20000.00", "1467.84", "158.09", "18532.16", "0.0734", "0.2098945"),
    (2025, "70000.00", "18767.36", "13733.13", "51232.64", "0.2681", "0.394516"),
    (2025, "275000.00", "109314.88", "103807.30", "165685.12", "0.3975", "0.528"),
    (2026, "20000.00", "1411.24", "103.49", "18588.76", "0.0706", "0.205188"),
    (2026, "70000.00", "18297.00", "13217.18", "51703.00", "0.2614", "0.3947635"),
    (2026, "275000.00", "108460.99", "102691.47", "166539.01", "0.3944", "0.528"),
]


@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize(
    ("year", "salary", "total", "income_tax", "take_home", "average", "marginal"), NEWFOUNDLAND
)
def test_newfoundland_compute_with_both_rates(
    client: TestClient,
    year: int,
    salary: str,
    total: str,
    income_tax: str,
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
    assert body["income_tax"] == income_tax
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


@pytest.mark.parametrize("year", [2025, 2026])
@pytest.mark.parametrize("salary", ["20000.00", "70000.00", "200000.00"])
def test_contributions_are_total_deductions_less_income_tax_in_every_province(
    client: TestClient, year: int, salary: str
) -> None:
    """CPP and EI do not depend on the province, so total_deductions less income_tax (what they add
    up to) is the same everywhere; it breaks if income_tax is read from a different line."""
    contributions = set()
    for code in ("CA-ON", "CA-AB", "CA-BC", "CA-MB", "CA-SK", "CA-NL"):
        body = compute(client, jurisdiction_code=code, year=year, salary=salary).json()
        contributions.add(Decimal(body["total_deductions"]) - Decimal(body["income_tax"]))
    assert len(contributions) == 1


@pytest.mark.parametrize("code", ["CA-ON", "CA-AB", "CA-BC", "CA-MB", "CA-SK", "CA-NL"])
def test_income_tax_is_the_total_payable_line_of_the_trace(client: TestClient, code: str) -> None:
    body = compute(client, jurisdiction_code=code, include_trace=True).json()
    (t1,) = [form for form in body["trace"] if form["form"] == "ca/t1_tax_and_credits"]
    amounts = [line["amount"] for line in t1["lines"] if line["label"] == "total_payable"]
    assert amounts == [body["income_tax"]]
