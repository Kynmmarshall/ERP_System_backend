"""Pure calculate_payslip() unit tests - no DB, no HTTP. Uses an
illustrative example rate schedule (see EXAMPLE_IRPP_BRACKETS in
tests/helpers.py) purely to exercise the calculation logic; these are not
real CNPS/DGI rates."""

from decimal import Decimal

import pytest

from app.payroll import ScheduleRates, calculate_payslip
from tests.helpers import EXAMPLE_IRPP_BRACKETS

_RATES = ScheduleRates(
    cnps_employee_rate=Decimal("0.042"),
    cnps_employer_rate=Decimal("0.070"),
    cnps_ceiling_xaf=750_000,
    standard_deduction_rate=Decimal("0.30"),
    irpp_brackets=EXAMPLE_IRPP_BRACKETS,
)


def test_gross_below_cnps_ceiling_computes_expected_breakdown() -> None:
    breakdown = calculate_payslip(500_000, _RATES)

    assert breakdown.cnps_employee_xaf == 21_000
    assert breakdown.taxable_base_xaf == 335_300
    assert breakdown.irpp_xaf == 43_825
    assert breakdown.net_xaf == 435_175


def test_gross_above_cnps_ceiling_caps_contribution_at_ceiling() -> None:
    breakdown = calculate_payslip(1_000_000, _RATES)

    # CNPS is computed on min(gross, ceiling), not the full gross.
    assert breakdown.cnps_employee_xaf == 31_500
    assert breakdown.cnps_employer_xaf == 52_500
    assert breakdown.irpp_xaf == 147_283
    assert breakdown.net_xaf == 1_000_000 - 31_500 - 147_283


def test_zero_gross_yields_zero_everything() -> None:
    breakdown = calculate_payslip(0, _RATES)

    assert breakdown.cnps_employee_xaf == 0
    assert breakdown.taxable_base_xaf == 0
    assert breakdown.irpp_xaf == 0
    assert breakdown.net_xaf == 0


def test_negative_gross_is_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_payslip(-1, _RATES)


def test_gross_exactly_at_first_bracket_boundary() -> None:
    # Zero CNPS/deduction rates so taxable_base == gross exactly, isolating
    # the bracket-boundary behavior from any rounding introduced upstream.
    rates = ScheduleRates(
        cnps_employee_rate=Decimal("0"),
        cnps_employer_rate=Decimal("0"),
        cnps_ceiling_xaf=750_000,
        standard_deduction_rate=Decimal("0"),
        irpp_brackets=EXAMPLE_IRPP_BRACKETS,
    )
    at_boundary = calculate_payslip(200_000, rates)
    # Entirely within the first 10% bracket.
    assert at_boundary.irpp_xaf == 20_000

    just_past_boundary = calculate_payslip(210_000, rates)
    # The 10,000 above the boundary is taxed at the second bracket's 15%.
    assert just_past_boundary.irpp_xaf == 20_000 + 1_500
