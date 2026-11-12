"""The inbound request adapter on its own: what reaches the application when a field is omitted."""

from decimal import Decimal

from app.adapters.inbound.take_home_calculations_adapter import TakeHomeCalculationsRequestAdapter
from app.domain.take_home import FormTrace, TakeHomeResult, TraceEntry, Unit
from app.generated.models import ComputeTakeHomeCalculationRequest

CAD = Unit("ca/cad", "before", "CA$", "CA$", False)


class Recorder:
    def __init__(self) -> None:
        self.language: str | None = "unset"

    async def compute_take_home_calculation(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str | None,
        include_trace: bool,
    ) -> TakeHomeResult:
        self.language = language_code
        return TakeHomeResult(
            salary=salary,
            total_deductions=Decimal(0),
            take_home=salary,
            provisional=False,
            unit=CAD,
            trace=None,
        )


async def test_an_omitted_language_reaches_the_application_as_not_asked_for() -> None:
    recorder = Recorder()
    request = ComputeTakeHomeCalculationRequest(
        jurisdiction_code="CA-ON", year=2025, salary="70000.00"
    )
    await TakeHomeCalculationsRequestAdapter(recorder).compute_take_home_calculation(request)
    assert recorder.language is None


async def test_a_language_that_was_sent_is_passed_on() -> None:
    recorder = Recorder()
    request = ComputeTakeHomeCalculationRequest(
        jurisdiction_code="CA-ON", year=2025, salary="70000.00", language_code="fr"
    )
    await TakeHomeCalculationsRequestAdapter(recorder).compute_take_home_calculation(request)
    assert recorder.language == "fr"


class Tracing:
    async def compute_take_home_calculation(
        self,
        jurisdiction_code: str,
        year: int,
        salary: Decimal,
        language_code: str | None,
        include_trace: bool,
    ) -> TakeHomeResult:
        trace = (
            FormTrace(
                "ex/form",
                None,
                (TraceEntry("ex_line", None, None, Decimal(1), "one", unit=None),),
            ),
        )
        return TakeHomeResult(
            salary=salary,
            total_deductions=Decimal(0),
            take_home=salary,
            provisional=False,
            unit=CAD,
            trace=trace,
        )


async def test_a_form_without_a_name_goes_out_under_its_identifier() -> None:
    request = ComputeTakeHomeCalculationRequest(
        jurisdiction_code="CA-ON", year=2025, salary="70000.00", include_trace=True
    )
    response = await TakeHomeCalculationsRequestAdapter(Tracing()).compute_take_home_calculation(
        request
    )
    assert response.trace is not None
    (form,) = response.trace
    assert (form.form, form.name) == ("ex/form", "ex/form")
    (line,) = form.lines
    assert (line.name, line.reference) == (None, None)
    assert line.unit is None


async def test_the_unit_goes_out_with_the_result() -> None:
    request = ComputeTakeHomeCalculationRequest(
        jurisdiction_code="CA-ON", year=2025, salary="70000.00"
    )
    response = await TakeHomeCalculationsRequestAdapter(Tracing()).compute_take_home_calculation(
        request
    )
    unit = response.unit
    assert (unit.name, unit.placement, unit.singular, unit.plural, unit.spaced) == (
        "ca/cad",
        "before",
        "CA$",
        "CA$",
        False,
    )
