"""Phase 12: branded Excel report built with openpyxl from the dict produced
by report_data.gather_report_data(). Three sheets — Summary, Weather &
Forecast, History — plus one native openpyxl line chart (recommendation over
time) embedded on the History sheet. Never raises on missing data: an empty
history renders one explicit "No predictions recorded yet" row instead of an
empty/broken table (see the module docstring on report_data.py)."""

import io

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

BRAND_BLUE = "2A78D6"
BRAND_INK = "13202C"
LIGHT_FILL = "EAF1FB"
MUTED = "5B6673"

TITLE_FONT = Font(name="Calibri", size=18, bold=True, color=BRAND_BLUE)
SUBTITLE_FONT = Font(name="Calibri", size=10, color=MUTED)
SECTION_FONT = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
SECTION_FILL = PatternFill("solid", fgColor=BRAND_BLUE)
LABEL_FONT = Font(name="Calibri", size=10, bold=True, color=BRAND_INK)
VALUE_FONT = Font(name="Calibri", size=10, color=BRAND_INK)
HEADER_FONT = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=BRAND_BLUE)
STRIPE_FILL = PatternFill("solid", fgColor=LIGHT_FILL)
THIN_BORDER = Border(bottom=Side(style="thin", color="D7DEE6"))
DISCLAIMER = "Synthetic-data research prototype — not agronomic advice."


def _section_header(ws: Worksheet, row: int, text: str, span: int) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = SECTION_FONT
    cell.fill = SECTION_FILL
    cell.alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[row].height = 22
    for col in range(1, span + 1):
        ws.cell(row=row, column=col).fill = SECTION_FILL
    return row + 1


def _label_value(ws: Worksheet, row: int, label: str, value) -> int:
    ws.cell(row=row, column=1, value=label).font = LABEL_FONT
    cell = ws.cell(row=row, column=2, value=value)
    cell.font = VALUE_FONT
    return row + 1


def _branded_header(ws: Worksheet, data: dict, span: int) -> int:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    # Brand name on row 1, tagline folded into row 2's subtitle - mirrors the
    # PDF report's header (app/services/report_pdf.py) so both exports carry
    # the same identity. Row numbers below are unchanged.
    title = ws.cell(row=1, column=1, value="LEHAR")
    title.font = TITLE_FONT
    ws.row_dimensions[1].height = 26

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)
    generated = data["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
    subtitle = ws.cell(
        row=2,
        column=1,
        value=(
            "Level-based Early-warning for Hydrological & Agricultural Risk "
            f"· Generated {generated} · Synthetic research data"
        ),
    )
    subtitle.font = SUBTITLE_FONT

    row = 4
    metrics = data["model_metrics"] or {}
    metrics_text = (
        f"MAE {metrics.get('mae', 'n/a'):.3f} mm · RMSE {metrics.get('rmse', 'n/a'):.3f} mm · R2 {metrics.get('r2', 'n/a'):.4f}"
        if metrics
        else "No metrics recorded for this model version."
    )
    row = _label_value(ws, row, "Model version", data["model_version"] or "n/a")
    row = _label_value(ws, row, "Model metrics", metrics_text)
    row = _label_value(ws, row, "Report owner", data["user"].username)
    row = _label_value(ws, row, "District", data["district"])
    return row + 1


def _field_section(ws: Worksheet, row: int, field, span: int) -> int:
    row = _section_header(ws, row, "Field details", span)
    if field is None:
        ws.cell(row=row, column=1, value="No field selected — this report is not tied to a saved field.").font = VALUE_FONT
        return row + 2
    row = _label_value(ws, row, "Name", field.name)
    row = _label_value(ws, row, "District", field.district)
    row = _label_value(ws, row, "Crop type", field.crop_type)
    row = _label_value(ws, row, "Default soil moisture (%)", field.default_soil_moisture_pct or "n/a")
    row = _label_value(ws, row, "Default canal flow (cusecs)", field.default_canal_flow_cusecs or "n/a")
    return row + 1


def _latest_prediction_section(ws: Worksheet, row: int, latest: dict | None, span: int) -> int:
    row = _section_header(ws, row, "Latest prediction summary", span)
    if latest is None:
        ws.cell(row=row, column=1, value="No predictions recorded yet.").font = VALUE_FONT
        return row + 2
    row = _label_value(ws, row, "Recorded", latest["created_at"].strftime("%Y-%m-%d %H:%M UTC"))
    row = _label_value(ws, row, "District / crop", f"{latest['district']} / {latest['crop_type']}")
    row = _label_value(
        ws,
        row,
        "Inputs",
        f"soil moisture {latest['soil_moisture_pct']:.0f}%, canal flow {latest['canal_flow_cusecs']:.0f} cusecs",
    )
    row = _label_value(
        ws,
        row,
        "Weather used",
        f"{latest['temperature_c']:.1f}°C, {latest['humidity_pct']:.0f}% humidity, "
        f"{latest['rainfall_mm']:.1f}mm rain, ET0 {latest['evapotranspiration_mm']:.1f}mm",
    )
    row = _label_value(ws, row, "Recommendation", f"{latest['recommendation_mm']:.1f} mm ({latest['source']})")
    row = _label_value(ws, row, "Risk band", f"{latest['risk_band'] or 'n/a'} ({latest['risk_score'] if latest['risk_score'] is not None else 'n/a'})")
    if latest["top_factors"]:
        for i, sentence in enumerate(latest["top_factors"], start=1):
            row = _label_value(ws, row, f"Top SHAP factor {i}", sentence)
    else:
        row = _label_value(ws, row, "Top SHAP factors", "Not available for this prediction.")
    return row + 1


def _autosize(ws: Worksheet, widths: dict[int, int]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


def _build_summary_sheet(wb: Workbook, data: dict) -> None:
    ws = wb.active
    ws.title = "Summary"
    span = 2
    row = _branded_header(ws, data, span)
    row = _field_section(ws, row, data["field"], span)
    row = _latest_prediction_section(ws, row, data["latest_prediction"], span)

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    footer = ws.cell(row=row, column=1, value=DISCLAIMER)
    footer.font = Font(name="Calibri", size=9, italic=True, color=MUTED)

    _autosize(ws, {1: 26, 2: 62})
    ws.sheet_view.showGridLines = False


def _build_weather_sheet(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("Weather & Forecast")
    span = 5
    row = _section_header(ws, 1, "Current weather", span)
    weather = data["weather"]
    if weather is None:
        ws.cell(row=row, column=1, value="Live weather is currently unavailable for this district.").font = VALUE_FONT
        row += 2
    else:
        headers = ["District", "Temperature (°C)", "Humidity (%)", "Rainfall (mm)", "ET0 (mm)"]
        for col, h in enumerate(headers, start=1):
            c = ws.cell(row=row, column=col, value=h)
            c.font = HEADER_FONT
            c.fill = HEADER_FILL
        row += 1
        ws.cell(row=row, column=1, value=data["district"])
        ws.cell(row=row, column=2, value=round(weather["temperature_c"], 1))
        ws.cell(row=row, column=3, value=round(weather["humidity_pct"], 0))
        ws.cell(row=row, column=4, value=round(weather["rainfall_mm"], 1))
        ws.cell(row=row, column=5, value=round(weather["evapotranspiration_mm"], 1))
        row += 2

    row = _section_header(ws, row, "7-day forecast", span)
    forecast = data["forecast"]
    if not forecast:
        ws.cell(row=row, column=1, value="Forecast is currently unavailable for this district.").font = VALUE_FONT
    else:
        headers = ["Date", "Temperature (°C)", "Humidity (%)", "Rainfall (mm)", "ET0 (mm)"]
        header_row = row
        for col, h in enumerate(headers, start=1):
            c = ws.cell(row=header_row, column=col, value=h)
            c.font = HEADER_FONT
            c.fill = HEADER_FILL
        for i, day in enumerate(forecast):
            r = header_row + 1 + i
            ws.cell(row=r, column=1, value=day["date"])
            ws.cell(row=r, column=2, value=round(day["temperature_c"], 1))
            ws.cell(row=r, column=3, value=round(day["humidity_pct"], 0) if day["humidity_pct"] is not None else "n/a")
            ws.cell(row=r, column=4, value=round(day["rainfall_mm"], 1))
            ws.cell(row=r, column=5, value=round(day["evapotranspiration_mm"], 1))
            if i % 2 == 1:
                for col in range(1, span + 1):
                    ws.cell(row=r, column=col).fill = STRIPE_FILL
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate

    _autosize(ws, {1: 14, 2: 18, 3: 14, 4: 14, 5: 12})
    ws.sheet_view.showGridLines = False


HISTORY_HEADERS = [
    "Date/time (UTC)",
    "District",
    "Crop",
    "Soil moisture (%)",
    "Canal flow (cusecs)",
    "Recommendation (mm)",
    "Source",
    "Model version",
    "Risk band",
    "Actual (mm)",
]


def _build_history_sheet(wb: Workbook, data: dict) -> Worksheet:
    ws = wb.create_sheet("History")
    history = data["history"]

    for col, h in enumerate(HISTORY_HEADERS, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
    ws.freeze_panes = "A2"

    if not history:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(HISTORY_HEADERS))
        ws.cell(row=2, column=1, value="No predictions recorded yet.").font = VALUE_FONT
    else:
        # Oldest-first so the embedded chart reads left-to-right chronologically.
        for i, log in enumerate(reversed(history)):
            r = i + 2
            ws.cell(row=r, column=1, value=log.created_at.strftime("%Y-%m-%d %H:%M"))
            ws.cell(row=r, column=2, value=log.district)
            ws.cell(row=r, column=3, value=log.crop_type)
            ws.cell(row=r, column=4, value=round(log.soil_moisture_pct, 1))
            ws.cell(row=r, column=5, value=round(log.canal_flow_cusecs, 0))
            ws.cell(row=r, column=6, value=round(log.recommendation_mm, 1))
            ws.cell(row=r, column=7, value=log.source)
            ws.cell(row=r, column=8, value=log.model_version or "n/a")
            ws.cell(row=r, column=9, value=log.risk_band or "n/a")
            ws.cell(row=r, column=10, value=round(log.actual.actual_irrigation_mm, 1) if log.actual else None)
            if i % 2 == 1:
                for col in range(1, len(HISTORY_HEADERS) + 1):
                    ws.cell(row=r, column=col).fill = STRIPE_FILL

    _autosize(ws, {1: 17, 2: 16, 3: 12, 4: 16, 5: 18, 6: 18, 7: 20, 8: 22, 9: 12, 10: 13})
    ws.sheet_view.showGridLines = False
    return ws


def _embed_chart(ws: Worksheet, n_rows: int) -> None:
    """Native openpyxl LineChart of recommendation-over-time — only added
    when there's at least one real row to chart (an empty/degenerate chart
    would be misleading, not honest, so it's simply omitted)."""
    if n_rows < 1:
        return
    chart = LineChart()
    chart.title = "Recommendation over time (mm)"
    chart.style = 2
    chart.y_axis.title = "mm"
    chart.x_axis.title = "Date/time (UTC)"
    chart.height = 8
    chart.width = 20

    data_ref = Reference(ws, min_col=6, min_row=1, max_row=n_rows + 1)
    cats_ref = Reference(ws, min_col=1, min_row=2, max_row=n_rows + 1)
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.series[0].graphicalProperties.line.solidFill = BRAND_BLUE
    chart.series[0].graphicalProperties.line.width = 20000
    chart.series[0].smooth = False

    anchor_row = n_rows + 4
    ws.add_chart(chart, f"A{anchor_row}")


def build_xlsx_report(data: dict) -> bytes:
    """Returns the finished .xlsx file as raw bytes."""
    wb = Workbook()
    _build_summary_sheet(wb, data)
    _build_weather_sheet(wb, data)
    history_ws = _build_history_sheet(wb, data)
    _embed_chart(history_ws, len(data["history"]))

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


__all__ = ["build_xlsx_report", "DISCLAIMER"]
