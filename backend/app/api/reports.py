"""Отчёты: предпросмотр и выгрузка в трёх форматах."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_session
from app.core.errors import AppError
from app.models import DATASET_REAL, User
from app.services import reports
from app.services.reports import ReportRequest

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])

MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


class ReportParams(BaseModel):
    scope: Literal["canteen", "gate", "source"] = "canteen"
    source_id: int | None = None
    period: str = "day"
    date_from: str | None = None
    date_to: str | None = None
    step: str | None = None


class ExportParams(ReportParams):
    format: Literal["csv", "xlsx", "pdf"] = "pdf"


def _request(params: ReportParams) -> ReportRequest:
    if params.scope == "source" and params.source_id is None:
        raise AppError(
            "source_required",
            "Для отчёта по источнику нужно выбрать источник.",
            422,
            {"fields": {"source_id": "Выберите источник."}},
        )
    return ReportRequest(
        scope=params.scope,
        source_id=params.source_id,
        period=params.period,
        date_from=params.date_from,
        date_to=params.date_to,
        step=params.step,
    )


@router.post("/preview")
def preview(
    params: ReportParams,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    report = reports.build_report(
        session, _request(params), user.display_name or user.login, user.dataset or DATASET_REAL
    )
    return {"report": report}


@router.post("/export")
def export(
    params: ExportParams,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Файл собирается из того же отчёта, что показан в предпросмотре."""
    report = reports.build_report(
        session, _request(params), user.display_name or user.login, user.dataset or DATASET_REAL
    )

    if params.format == "csv":
        content = reports.to_csv(report)
    elif params.format == "xlsx":
        content = reports.to_xlsx(report)
    else:
        content = reports.to_pdf(report)

    name = reports.filename(report, params.format)
    LOGGER.info("Отчёт выгружен: %s (%s строк)", name, report["totals"]["rows"])
    return Response(
        content=content,
        media_type=MEDIA[params.format],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
