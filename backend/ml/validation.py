"""
Phase 8: pandera schema + validation report for the training dataset CSV
(data/synthetic_irrigation_dataset_pk107.csv).

Replaces ml/pipeline.py's old ad-hoc range-check loop (Phase 7) with a real
statistical/schema validation library, collecting EVERY violation in one
pass (lazy=True) rather than stopping at the first, plus a missing-values
report and unexpected-category detection that pandera's column checks alone
don't surface as a friendly summary. See docs/DATA_VALIDATION.md for the
bounds and the reasoning behind each.

`soil_moisture_pct` is deliberately `nullable=True`: generate_data.py injects
sensor faults on purpose (missing_sensor/stuck_sensor) before imputing them,
and this schema is meant to describe the physical sensor reading honestly,
not just whatever the current generator happens to output today. The real
generated CSV currently has zero nulls anywhere (imputation already applied
before the file is written) — nullable=True does not relax any other check,
it only stops a hypothetical pre-imputation dataset from failing validation
solely because of an expected, documented gap.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

ML_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ML_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ml.districts import DISTRICTS  # noqa: E402
from ml.generate_data import CROPS  # noqa: E402

KNOWN_DISTRICTS = sorted(DISTRICTS.keys())
KNOWN_CROPS = sorted(CROPS)

TARGET_COLUMN = "irrigation_recommendation_mm"

# Physical bounds for the training dataset — see docs/DATA_VALIDATION.md.
# Deliberately tighter than Phase 7's old RANGE_CHECKS (which used generous
# "catch garbage data" bounds); the real generated dataset's actual min/max
# per column is comfortably inside every one of these (verified against
# data/synthetic_irrigation_dataset_pk107.csv before picking these values).
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "temperature_c": (-10.0, 55.0),
    "humidity_pct": (0.0, 100.0),
    "rainfall_mm": (0.0, 400.0),
    "evapotranspiration_mm": (0.0, 20.0),
    "canal_flow_cusecs": (0.0, 2000.0),
}
SOIL_MOISTURE_RANGE = (0.0, 100.0)
TARGET_RANGE = (0.0, 100.0)

REQUIRED_COLUMNS = set(NUMERIC_RANGES) | {"soil_moisture_pct", TARGET_COLUMN, "crop_type", "district", "date"}


def _range_column(low: float, high: float, *, nullable: bool = False) -> Column:
    return Column(float, checks=Check.in_range(low, high), nullable=nullable)


def build_schema() -> DataFrameSchema:
    """Builds the pandera schema fresh (rather than a module-level constant)
    so KNOWN_DISTRICTS/KNOWN_CROPS changes (e.g. a future district-list
    edit) are always picked up without needing a reload."""
    columns = {name: _range_column(*bounds) for name, bounds in NUMERIC_RANGES.items()}
    columns["soil_moisture_pct"] = _range_column(*SOIL_MOISTURE_RANGE, nullable=True)
    columns[TARGET_COLUMN] = _range_column(*TARGET_RANGE)
    columns["crop_type"] = Column(str, checks=Check.isin(KNOWN_CROPS), nullable=False)
    columns["district"] = Column(str, checks=Check.isin(KNOWN_DISTRICTS), nullable=False)
    columns["date"] = Column("datetime64[ns]", nullable=False)
    # strict=False: the CSV also carries sensor_fault_type/was_imputed/month/
    # day_of_year/etc. — this schema only opines on the columns it lists.
    return DataFrameSchema(columns, strict=False)


@dataclass
class ValidationReport:
    """Everything needed for a readable validation_report.json artifact
    (see ml/pipeline.py's validate() stage) — never just a bool."""

    passed: bool
    n_rows: int
    n_columns: int
    errors: list[str] = field(default_factory=list)
    missing_values: dict[str, int] = field(default_factory=dict)
    unexpected_categories: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "n_rows": self.n_rows,
            "n_columns": self.n_columns,
            "errors": self.errors,
            "missing_values": self.missing_values,
            "unexpected_categories": self.unexpected_categories,
        }


class DataValidationError(ValueError):
    """Raised by ml/pipeline.py's validate() stage — never train on data
    that fails schema (CLAUDE.md rule 4)."""

    def __init__(self, report: ValidationReport):
        self.report = report
        summary = "; ".join(report.errors[:5])
        more = f" (+{len(report.errors) - 5} more)" if len(report.errors) > 5 else ""
        super().__init__(f"Training data failed validation ({len(report.errors)} issue(s)): {summary}{more}")


def missing_values_report(df: pd.DataFrame) -> dict[str, int]:
    """Null count per required column that's actually present in df — only
    columns with at least one missing value are included."""
    present = [c for c in sorted(REQUIRED_COLUMNS) if c in df.columns]
    if not present:
        return {}
    counts = df[present].isnull().sum()
    return {column: int(n) for column, n in counts.items() if n > 0}


def unexpected_categories_report(df: pd.DataFrame) -> dict[str, list[str]]:
    """Category values outside the known district/crop_type lists — reported
    even when the schema check below would already fail the run, since a
    human reading validation_report.json wants the exact unknown values."""
    report: dict[str, list[str]] = {}
    if "district" in df.columns:
        unknown = sorted(set(df["district"].dropna().unique()) - set(KNOWN_DISTRICTS))
        if unknown:
            report["district"] = unknown
    if "crop_type" in df.columns:
        unknown = sorted(set(df["crop_type"].dropna().unique()) - set(KNOWN_CROPS))
        if unknown:
            report["crop_type"] = unknown
    return report


def _readable_check(column: str, check: str) -> str:
    """Shortens the district isin(...) check string (107 names long) to a
    readable count instead of dumping every known district into every error
    line — every other check string is already short enough to show as-is."""
    if check.startswith("isin(") and len(check) > 60:
        known = KNOWN_DISTRICTS if column == "district" else KNOWN_CROPS
        return f"isin(<{len(known)} known {column} values>)"
    return check


def _summarize_failures(failure_cases: pd.DataFrame) -> list[str]:
    """One readable line per (column, check) — e.g. "temperature_c: 3 row(s)
    failed check 'in_range(-10, 55)' (examples: [80.0, 62.4, -15.0])" —
    rather than one line per failing row, which could be thousands of lines
    on a badly corrupted dataset."""
    lines = []
    for (column, check), group in failure_cases.groupby(["column", "check"], dropna=False):
        examples = group["failure_case"].head(3).tolist()
        readable_check = _readable_check(column, check)
        lines.append(f"{column}: {len(group)} row(s) failed check '{readable_check}' (examples: {examples})")
    return lines


def validate_training_data(df: pd.DataFrame) -> ValidationReport:
    """Runs the pandera schema (lazy=True — collects every violation, not
    just the first) plus the missing-values and unexpected-category
    reports. Returns a ValidationReport; never raises on its own — callers
    that must fail-fast raise DataValidationError(report) themselves (see
    ml/pipeline.py's validate() stage)."""
    df = df.copy()

    missing_cols = sorted(REQUIRED_COLUMNS - set(df.columns))
    errors: list[str] = []
    if missing_cols:
        errors.append(f"Missing required column(s): {missing_cols}")

    missing_values = missing_values_report(df)
    unexpected_categories = unexpected_categories_report(df)

    if "date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["date"]):
        # "date parseable": unparseable values become NaT here, which the
        # schema's nullable=False check on "date" then reports as a failure.
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    if not missing_cols:
        try:
            build_schema().validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            errors.extend(_summarize_failures(exc.failure_cases))

    return ValidationReport(
        passed=not errors,
        n_rows=len(df),
        n_columns=len(df.columns),
        errors=errors,
        missing_values=missing_values,
        unexpected_categories=unexpected_categories,
    )
