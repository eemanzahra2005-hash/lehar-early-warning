"""GET /api/v1/report — branded Excel (default) or PDF report (Phase 12).

Auth required: a report is built from the caller's own field/prediction data
(same ownership model as /history, /fields). Gathering (report_data.py) is
kept separate from rendering (report_xlsx.py / report_pdf.py) so each format
is a thin, independently-testable transform of the same dict.
"""

from datetime import date as date_cls

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import User, get_db
from app.dependencies import get_explain_service, get_model_service, get_weather_service
from app.services.explain import ExplainService
from app.services.ml_model import ModelService
from app.services.report_data import gather_report_data, report_filename
from app.services.weather import WeatherService
from app.validators import validate_district

router = APIRouter(tags=["report"])

MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.get("/report")
def get_report(
    format: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    field_id: int | None = None,
    district: str | None = None,
    date_from: date_cls | None = Query(None, alias="from"),
    date_to: date_cls | None = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    model_service: ModelService = Depends(get_model_service),
    weather_service: WeatherService = Depends(get_weather_service),
    explain_service: ExplainService = Depends(get_explain_service),
) -> Response:
    if district is not None:
        validate_district(district)

    data = gather_report_data(
        user=current_user,
        db=db,
        model_service=model_service,
        weather_service=weather_service,
        explain_service=explain_service,
        field_id=field_id,
        requested_district=district,
        date_from=date_from,
        date_to=date_to,
    )

    # report_pdf.py/report_xlsx.py pull in matplotlib/reportlab/openpyxl —
    # imported lazily here (not at module level) so a worker that never
    # serves a /report request never pays for them (LOW_MEMORY_MODE, Phase
    # 13.1 — see docs/DEPLOY_RENDER.md). This router already depends on
    # get_model_service/get_explain_service above, so the model itself is
    # loaded either way; this only defers the renderer libraries.
    if format == "pdf":
        from app.services.report_pdf import build_pdf_report

        content = build_pdf_report(data)
    else:
        from app.services.report_xlsx import build_xlsx_report

        content = build_xlsx_report(data)

    filename = report_filename(data, format)
    return Response(
        content=content,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
