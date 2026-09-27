"""Уведомления: новые события с момента последнего просмотра (ТЗ, раздел 4.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.db import get_session
from app.core.timeutil import now_utc
from app.models import DATASET_REAL, Event, User
from app.schemas.views import event_view

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    dataset = user.dataset or DATASET_REAL
    since = user.notifications_seen_at

    query = select(Event).where(Event.dataset == dataset).order_by(Event.started_at.desc())
    latest = list(session.scalars(query.limit(10)))

    unseen_query = select(func.count()).select_from(Event).where(Event.dataset == dataset)
    if since is not None:
        unseen_query = unseen_query.where(Event.started_at > since)
    unseen = int(session.scalar(unseen_query) or 0)

    critical = [
        event_view(session, event)
        for event in latest
        if event.severity == "critical" and event.status != "resolved"
    ]

    return {
        "unseen": unseen,
        "events": [event_view(session, event) for event in latest],
        # Критическое событие должно быть замечено из любого раздела.
        "critical": critical[:1],
        "seenAt": since.isoformat() if since else None,
    }


@router.post("/seen")
def mark_seen(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    user.notifications_seen_at = now_utc()
    session.add(user)
    session.commit()
    return {"seenAt": user.notifications_seen_at.isoformat()}
