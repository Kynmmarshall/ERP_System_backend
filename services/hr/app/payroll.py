"""Pure payroll calculation - no DB/HTTP dependencies, so every bracket
boundary and rounding rule can be exercised with plain unit tests (see
tests/test_payroll_calc.py). Calculation order (see phase6-plan.md):
gross -> CNPS employee contribution (capped at the ceiling) -> abattement
forfaitaire (standard deduction) -> taxable base -> marginal-bracket IRPP
-> net pay.

All monetary values are whole XAF (no sub-unit currency), so every result
is rounded to the nearest franc using ROUND_HALF_UP.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class ScheduleRates:
    """Plain-data mirror of PayrollScheduleVersion's rate fields - kept
    independent of the SQLAlchemy model so this module never imports the
    DB layer."""

    cnps_employee_rate: Decimal
    cnps_employer_rate: Decimal
    cnps_ceiling_xaf: int
    standard_deduction_rate: Decimal
    irpp_brackets: list[dict]


@dataclass(frozen=True)
class PayslipBreakdown:
    gross_xaf: int
    cnps_employee_xaf: int
    cnps_employer_xaf: int
    taxable_base_xaf: int
    irpp_xaf: int
    net_xaf: int


def _round_xaf(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _apply_irpp_brackets(taxable_base_xaf: Decimal, brackets: list[dict]) -> Decimal:
    """brackets is an ascending list of {"up_to_xaf": int|None, "rate": float},
    the last row's up_to_xaf=None meaning "and above". Tax is computed
    marginally: only the slice of the taxable base falling within each
    bracket is taxed at that bracket's rate.
    """
    tax = Decimal(0)
    lower = Decimal(0)
    for bracket in brackets:
        up_to = bracket["up_to_xaf"]
        upper = Decimal(up_to) if up_to is not None else taxable_base_xaf
        if taxable_base_xaf <= lower:
            break
        amount_in_bracket = min(taxable_base_xaf, upper) - lower
        if amount_in_bracket > 0:
            tax += amount_in_bracket * Decimal(str(bracket["rate"]))
        lower = upper
        if up_to is None:
            break
    return tax


def calculate_payslip(gross_xaf: int, schedule: ScheduleRates) -> PayslipBreakdown:
    if gross_xaf < 0:
        raise ValueError("gross_xaf must not be negative")

    gross = Decimal(gross_xaf)
    cnps_base = min(gross, Decimal(schedule.cnps_ceiling_xaf))
    cnps_employee = cnps_base * schedule.cnps_employee_rate
    cnps_employer = cnps_base * schedule.cnps_employer_rate

    after_cnps = gross - cnps_employee
    taxable_base = after_cnps * (Decimal(1) - schedule.standard_deduction_rate)
    if taxable_base < 0:
        taxable_base = Decimal(0)

    irpp = _apply_irpp_brackets(taxable_base, schedule.irpp_brackets)

    cnps_employee_xaf = _round_xaf(cnps_employee)
    cnps_employer_xaf = _round_xaf(cnps_employer)
    taxable_base_xaf = _round_xaf(taxable_base)
    irpp_xaf = _round_xaf(irpp)
    net_xaf = gross_xaf - cnps_employee_xaf - irpp_xaf

    return PayslipBreakdown(
        gross_xaf=gross_xaf,
        cnps_employee_xaf=cnps_employee_xaf,
        cnps_employer_xaf=cnps_employer_xaf,
        taxable_base_xaf=taxable_base_xaf,
        irpp_xaf=irpp_xaf,
        net_xaf=net_xaf,
    )
