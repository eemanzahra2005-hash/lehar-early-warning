"""Phase 12: branded PDF report built with reportlab (layout/tables/text) +
matplotlib's Agg backend (charts rendered in-memory, embedded as PNG images —
same headless pattern as ml/pipeline.py's residuals plot) from the dict
produced by report_data.gather_report_data(). Mirrors report_xlsx.py's
content: branded title block, summary, weather/forecast, two charts, a
paginated history table, page numbers, and a disclaimer footer on every
page."""

import io

import matplotlib

matplotlib.use("Agg")  # headless — this app never has a display attached
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.report_xlsx import DISCLAIMER

BRAND_BLUE = colors.HexColor("#2A78D6")
BRAND_INK = colors.HexColor("#13202C")
MUTED = colors.HexColor("#5B6673")
LIGHT_FILL = colors.HexColor("#EAF1FB")

PAGE_SIZE = A4
MARGIN = 1.8 * cm

_styles = getSampleStyleSheet()
STYLE_TITLE = ParagraphStyle("ReportTitle", parent=_styles["Title"], textColor=BRAND_BLUE, fontSize=20, spaceAfter=2)
STYLE_SUBTITLE = ParagraphStyle("ReportSubtitle", parent=_styles["Normal"], textColor=MUTED, fontSize=9, spaceAfter=10)
STYLE_SECTION = ParagraphStyle(
    "SectionHeader", parent=_styles["Heading2"], textColor=colors.white, backColor=BRAND_BLUE,
    fontSize=12, spaceBefore=10, spaceAfter=6, leftIndent=6, borderPadding=(4, 4, 4, 4),
)
STYLE_BODY = ParagraphStyle("ReportBody", parent=_styles["Normal"], fontSize=9.5, textColor=BRAND_INK, alignment=TA_LEFT, spaceAfter=3)
STYLE_LABEL = ParagraphStyle("ReportLabel", parent=STYLE_BODY, fontName="Helvetica-Bold")


def _matplotlib_line_chart(dates: list[str], values: list[float], *, title: str, ylabel: str) -> Image | None:
    if not values:
        return None
    fig, ax = plt.subplots(figsize=(6.4, 2.6), dpi=150)
    ax.plot(dates, values, color="#2A78D6", linewidth=1.8, marker="o", markersize=2.5)
    ax.set_title(title, fontsize=10, color="#13202C")
    ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(axis="both", labelsize=6.5)
    if len(dates) > 8:
        step = max(1, len(dates) // 8)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=30, ha="right")
    else:
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    ax.grid(axis="y", linewidth=0.4, alpha=0.4)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    return Image(buffer, width=16.5 * cm, height=6.8 * cm)


def _matplotlib_rainfall_vs_recommendation(dates: list[str], rainfall: list[float], recommendation: list[float]) -> Image | None:
    if not recommendation:
        return None
    fig, ax1 = plt.subplots(figsize=(6.4, 2.6), dpi=150)
    x = range(len(dates))
    ax1.bar(x, rainfall, color="#7FB3EE", label="Rainfall (mm)", width=0.6)
    ax1.set_ylabel("Rainfall (mm)", fontsize=8, color="#2A78D6")
    ax1.tick_params(axis="y", labelsize=6.5)
    ax1.set_title("Rainfall vs recommendation", fontsize=10, color="#13202C")

    ax2 = ax1.twinx()
    ax2.plot(x, recommendation, color="#E8622C", linewidth=1.8, marker="o", markersize=2.5, label="Recommendation (mm)")
    ax2.set_ylabel("Recommendation (mm)", fontsize=8, color="#E8622C")
    ax2.tick_params(axis="y", labelsize=6.5)

    if len(dates) > 8:
        step = max(1, len(dates) // 8)
        ax1.set_xticks(list(x)[::step])
        ax1.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=30, ha="right", fontsize=6.5)
    else:
        ax1.set_xticks(list(x))
        ax1.set_xticklabels(dates, rotation=30, ha="right", fontsize=6.5)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    return Image(buffer, width=16.5 * cm, height=6.8 * cm)


def _section_header(text: str) -> Table:
    """A full-width colored bar (Paragraph alone can't reliably paint a
    background across the full content width in reportlab), matching the
    xlsx report's blue section-header styling."""
    t = Table([[Paragraph(text, ParagraphStyle("sh", parent=STYLE_BODY, textColor=colors.white, fontName="Helvetica-Bold", fontSize=11))]], colWidths=[17 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(BRAND_BLUE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, 1.3 * cm, PAGE_SIZE[0] - MARGIN, 1.3 * cm)
    canvas.setFont("Helvetica-Oblique", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 0.9 * cm, DISCLAIMER)
    canvas.drawRightString(PAGE_SIZE[0] - MARGIN, 0.9 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _title_block(data: dict) -> list:
    story = [
        # Brand name alone at title size: the full tagline wraps to two 20pt
        # lines on A4's 17.4cm printable width and crowds the header, so it
        # rides on the subtitle line instead. "&" is escaped because
        # ReportLab parses Paragraph text as mini-XML.
        Paragraph("LEHAR", STYLE_TITLE),
        Paragraph(
            "Level-based Early-warning for Hydrological &amp; Agricultural Risk<br/>"
            f"Generated {data['generated_at'].strftime('%Y-%m-%d %H:%M UTC')} · Synthetic research data",
            STYLE_SUBTITLE,
        ),
    ]
    metrics = data["model_metrics"] or {}
    metrics_text = (
        f"MAE {metrics.get('mae', 0):.3f} mm · RMSE {metrics.get('rmse', 0):.3f} mm · R2 {metrics.get('r2', 0):.4f}"
        if metrics
        else "No metrics recorded for this model version."
    )
    rows = [
        ["Model version", data["model_version"] or "n/a"],
        ["Model metrics", metrics_text],
        ["Report owner", data["user"].username],
        ["District", data["district"]],
    ]
    table = Table(rows, colWidths=[4 * cm, 13 * cm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), BRAND_INK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))
    return story


def _field_and_prediction_block(data: dict) -> list:
    story = [_section_header("Field details"), Spacer(1, 4)]
    field = data["field"]
    if field is None:
        story.append(Paragraph("No field selected — this report is not tied to a saved field.", STYLE_BODY))
    else:
        rows = [
            ["Name", field.name],
            ["District", field.district],
            ["Crop type", field.crop_type],
            ["Default soil moisture (%)", str(field.default_soil_moisture_pct or "n/a")],
            ["Default canal flow (cusecs)", str(field.default_canal_flow_cusecs or "n/a")],
        ]
        t = Table(rows, colWidths=[5 * cm, 12 * cm])
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9.5)]))
        story.append(t)
    story.append(Spacer(1, 6))

    story.append(_section_header("Latest prediction summary"))
    story.append(Spacer(1, 4))
    latest = data["latest_prediction"]
    if latest is None:
        story.append(Paragraph("No predictions recorded yet.", STYLE_BODY))
    else:
        rows = [
            ["Recorded", latest["created_at"].strftime("%Y-%m-%d %H:%M UTC")],
            ["District / crop", f"{latest['district']} / {latest['crop_type']}"],
            ["Inputs", f"soil moisture {latest['soil_moisture_pct']:.0f}%, canal flow {latest['canal_flow_cusecs']:.0f} cusecs"],
            [
                "Weather used",
                f"{latest['temperature_c']:.1f}°C, {latest['humidity_pct']:.0f}% humidity, "
                f"{latest['rainfall_mm']:.1f}mm rain, ET0 {latest['evapotranspiration_mm']:.1f}mm",
            ],
            ["Recommendation", f"{latest['recommendation_mm']:.1f} mm ({latest['source']})"],
            ["Risk band", f"{latest['risk_band'] or 'n/a'} ({latest['risk_score'] if latest['risk_score'] is not None else 'n/a'})"],
        ]
        t = Table(rows, colWidths=[4 * cm, 13 * cm])
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9.5), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
        story.append(Spacer(1, 4))
        if latest["top_factors"]:
            story.append(Paragraph("Top SHAP factors:", STYLE_LABEL))
            for sentence in latest["top_factors"]:
                story.append(Paragraph(f"&bull; {sentence}", STYLE_BODY))
        else:
            story.append(Paragraph("Top SHAP factors: not available for this prediction.", STYLE_BODY))
    story.append(Spacer(1, 6))
    return story


def _weather_block(data: dict) -> list:
    story = [_section_header("Current weather & 7-day forecast"), Spacer(1, 4)]
    weather = data["weather"]
    if weather is None:
        story.append(Paragraph("Live weather is currently unavailable for this district.", STYLE_BODY))
    else:
        rows = [
            ["District", "Temperature (°C)", "Humidity (%)", "Rainfall (mm)", "ET0 (mm)"],
            [
                data["district"],
                f"{weather['temperature_c']:.1f}",
                f"{weather['humidity_pct']:.0f}",
                f"{weather['rainfall_mm']:.1f}",
                f"{weather['evapotranspiration_mm']:.1f}",
            ],
        ]
        story.append(_styled_table(rows, colWidths=[4.5 * cm, 3.2 * cm, 3.2 * cm, 3 * cm, 2.6 * cm]))
    story.append(Spacer(1, 6))

    forecast = data["forecast"]
    if not forecast:
        story.append(Paragraph("Forecast is currently unavailable for this district.", STYLE_BODY))
    else:
        rows = [["Date", "Temperature (°C)", "Humidity (%)", "Rainfall (mm)", "ET0 (mm)"]]
        for day in forecast:
            humidity = f"{day['humidity_pct']:.0f}" if day["humidity_pct"] is not None else "n/a"
            rows.append([day["date"], f"{day['temperature_c']:.1f}", humidity, f"{day['rainfall_mm']:.1f}", f"{day['evapotranspiration_mm']:.1f}"])
        story.append(_styled_table(rows, colWidths=[4.5 * cm, 3.2 * cm, 3.2 * cm, 3 * cm, 2.6 * cm]))
    story.append(Spacer(1, 6))
    return story


STYLE_TABLE_HEADER = ParagraphStyle(
    "TableHeader", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=7.6,
    textColor=colors.white, leading=9,
)


def _styled_table(rows: list[list[str]], colWidths: list[float]) -> Table:
    # Header cells are wrapped in a Paragraph (word-wraps within its column,
    # e.g. "Canal (cusecs)" over two lines) rather than a plain string —
    # reportlab does not shrink/wrap plain-string cell text to fit a given
    # colWidth, so a header longer than its column silently overlapped the
    # next column's text (found via a real rendered-PDF check, not by eye).
    wrapped_rows = [[Paragraph(str(cell), STYLE_TABLE_HEADER) for cell in rows[0]], *rows[1:]]
    t = Table(wrapped_rows, colWidths=colWidths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7DEE6")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), LIGHT_FILL))
    t.setStyle(TableStyle(style))
    return t


HISTORY_HEADERS = ["Date/time", "District", "Crop", "Soil (%)", "Canal (cusecs)", "Rec. (mm)", "Source", "Risk", "Actual (mm)"]


def _history_block(data: dict) -> list:
    story = [_section_header("Prediction history"), Spacer(1, 4)]
    history = data["history"]
    if not history:
        story.append(Paragraph("No predictions recorded yet.", STYLE_BODY))
        return story

    rows = [HISTORY_HEADERS]
    for log in history:
        rows.append([
            log.created_at.strftime("%Y-%m-%d %H:%M"),
            log.district,
            log.crop_type,
            f"{log.soil_moisture_pct:.0f}",
            f"{log.canal_flow_cusecs:.0f}",
            f"{log.recommendation_mm:.1f}",
            log.source,
            log.risk_band or "n/a",
            f"{log.actual.actual_irrigation_mm:.1f}" if log.actual else "—",
        ])
    # Sums to 16.9cm — fits the 17.4cm printable width (A4 21cm - 2x1.8cm
    # margins) with a small safety margin; found the previous, wider set
    # overflowing the page in a real rendered-PDF check.
    story.append(_styled_table(rows, colWidths=[2.8 * cm, 2.0 * cm, 1.5 * cm, 1.4 * cm, 1.8 * cm, 1.6 * cm, 2.8 * cm, 1.4 * cm, 1.6 * cm]))
    return story


def _charts_block(data: dict) -> list:
    history = data["history"]
    if not history:
        return []
    chronological = list(reversed(history))
    dates = [log.created_at.strftime("%m-%d %H:%M") for log in chronological]
    recommendations = [log.recommendation_mm for log in chronological]
    rainfall = [log.rainfall_mm for log in chronological]

    story = [_section_header("Charts"), Spacer(1, 6)]
    rec_chart = _matplotlib_line_chart(dates, recommendations, title="Recommendation over time", ylabel="mm")
    if rec_chart:
        story.append(rec_chart)
        story.append(Spacer(1, 8))
    combo_chart = _matplotlib_rainfall_vs_recommendation(dates, rainfall, recommendations)
    if combo_chart:
        story.append(combo_chart)
    return story


def build_pdf_report(data: dict) -> bytes:
    """Returns the finished .pdf file as raw bytes. Page breaks are placed
    so the history table (which can be long) always starts on its own page
    and paginates automatically via reportlab's Table row-splitting."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=1.8 * cm,
        title="LEHAR Report",
    )

    story: list = []
    story.extend(_title_block(data))
    story.extend(_field_and_prediction_block(data))
    story.extend(_weather_block(data))
    story.append(PageBreak())
    story.extend(_charts_block(data))
    story.append(PageBreak())
    story.extend(_history_block(data))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


__all__ = ["build_pdf_report"]
