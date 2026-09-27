"""Счётчики за сутки переживают перезапуск рабочего потока."""

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.timeutil import now_utc, start_of_day
from app.models import Base, Bucket, Source
from app.services.sources import today_totals


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_today_totals_sum_only_current_day():
    session = _session()
    session.add(Source(id=1, name="Столовая", scope="canteen"))

    # Вчерашние данные в сегодняшний счётчик попадать не должны.
    session.add(
        Bucket(
            source_id=1,
            dataset="real",
            started_at=start_of_day() - timedelta(hours=2),
            entered=5,
            exited=4,
        )
    )
    session.add(Bucket(source_id=1, dataset="real", started_at=now_utc(), entered=3, exited=1))
    session.add(
        Bucket(
            source_id=1,
            dataset="real",
            started_at=now_utc() - timedelta(minutes=5),
            entered=2,
            exited=2,
        )
    )
    # Демо-данные считаются отдельно и в реальные счётчики не подмешиваются.
    session.add(Bucket(source_id=1, dataset="demo", started_at=now_utc(), entered=99, exited=99))
    session.commit()

    assert today_totals(session, 1) == (5, 3)


def test_today_totals_empty_source():
    session = _session()
    session.add(Source(id=2, name="КПП 1", scope="gate"))
    session.commit()

    assert today_totals(session, 2) == (0, 0)
