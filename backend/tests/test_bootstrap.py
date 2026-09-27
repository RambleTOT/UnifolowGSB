"""Первый старт: видеофайлы с разметкой сами расходятся по источникам."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, Geometry, Source, Video
from app.services import bootstrap as bootstrap_module

MARKUP = {
    "anchor": "bottom_center",
    "lines": [
        {
            "id": "line-1",
            "name": "Проход",
            "a": [0.1, 0.5],
            "b": [0.9, 0.5],
            "entry_side": -1,
            "counts": "both",
        }
    ],
    "zones": [],
}


class FakeInfo:
    width = 640
    height = 360
    fps = 25.0
    duration_seconds = 10.0


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as active:
        yield active


@pytest.fixture
def videos(tmp_path, monkeypatch):
    directory = tmp_path / "videos"
    directory.mkdir()

    class FakeSettings:
        video_dir = directory
        allowed_video_suffixes = (".mp4",)

    monkeypatch.setattr(bootstrap_module, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(bootstrap_module, "probe_video", lambda path: FakeInfo())
    return directory


def write_video(directory: Path, name: str, owner: str | None = None, markup: bool = True) -> None:
    (directory / f"{name}.mp4").write_bytes(b"not a real file")
    if not markup:
        return
    payload = dict(MARKUP)
    if owner:
        payload = {"source": owner, **payload}
    (directory / f"{name}.markup.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_markup_sends_video_to_the_source_it_names(session, videos):
    write_video(videos, "gate", owner="КПП 2")
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_videos(session)

    sources = {source.name: source for source in session.scalars(select(Source))}
    assert sources["КПП 2"].video_id is not None
    assert sources["Столовая"].video_id is None
    geometry = session.scalars(select(Geometry)).one()
    assert geometry.source_id == sources["КПП 2"].id


def test_video_without_owner_goes_to_the_first_free_source(session, videos):
    write_video(videos, "a-named", owner="КПП 1")
    write_video(videos, "b-plain")
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_videos(session)

    sources = {source.name: source for source in session.scalars(select(Source))}
    assert sources["КПП 1"].video_id is not None
    # «Столовая» — первый источник без видео, ему и достаётся файл без хозяина.
    assert sources["Столовая"].video_id is not None
    assert sources["Раздача"].video_id is None


def test_annotated_copy_is_not_a_separate_video(session, videos):
    write_video(videos, "gate", owner="КПП 1")
    (videos / "gate.annotated.mp4").write_bytes(b"overlay")
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_videos(session)

    videos_in_base = list(session.scalars(select(Video)))
    assert [video.original_name for video in videos_in_base] == ["gate.mp4"]


def test_unknown_source_name_does_not_lose_the_video(session, videos):
    write_video(videos, "gate", owner="Проходная, которой нет")
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_videos(session)

    sources = {source.name: source for source in session.scalars(select(Source))}
    # Имя не совпало — файл всё равно нужно показать, иначе он просто исчезнет.
    assert sources["Столовая"].video_id is not None


def test_second_start_does_not_touch_anything(session, videos):
    write_video(videos, "gate", owner="КПП 1")
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_videos(session)
    write_video(videos, "later", owner="КПП 2")
    bootstrap_module.ensure_demo_videos(session)

    assert len(list(session.scalars(select(Video)))) == 1


STREAM = {
    "source": "КПП 2",
    "stream_url": "https://camera.example/public/live.m3u8",
    "model_profile": "far",
    "location": "Прямой эфир · Площадь",
    **MARKUP,
}


def write_stream(directory: Path, name: str, payload: dict) -> None:
    (directory / f"{name}.stream.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_stream_description_turns_named_source_into_live_camera(session, videos):
    write_stream(videos, "square", STREAM)
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_streams(session)

    source = session.scalars(select(Source).where(Source.name == "КПП 2")).one()
    assert source.connection_type == "stream"
    assert source.stream_url == STREAM["stream_url"]
    assert source.model_profile == "far"
    assert source.location == "Прямой эфир · Площадь"
    assert session.scalars(select(Geometry).where(Geometry.source_id == source.id)).one()


def test_stream_source_does_not_get_a_video_without_owner(session, videos):
    write_stream(videos, "square", STREAM)
    write_video(videos, "a-canteen", owner="Столовая")
    write_video(videos, "b-plain")
    write_video(videos, "c-plain")
    write_video(videos, "d-plain")
    # Тот же порядок, что при первом старте: сначала потоки, потом ролики.
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_streams(session)
    bootstrap_module.ensure_demo_videos(session)

    sources = {source.name: source for source in session.scalars(select(Source))}
    # Три ролика разошлись по источникам без видео, но не по источнику-потоку.
    assert sources["КПП 2"].video_id is None
    assert sources["КПП 2"].connection_type == "stream"
    assert all(sources[name].video_id is not None for name in ("Столовая", "Раздача", "КПП 1"))


def test_second_start_keeps_existing_stream(session, videos):
    write_stream(videos, "square", STREAM)
    bootstrap_module.ensure_sources(session)
    bootstrap_module.ensure_demo_streams(session)
    write_stream(videos, "square", {**STREAM, "stream_url": "https://camera.example/other.m3u8"})
    bootstrap_module.ensure_demo_streams(session)

    source = session.scalars(select(Source).where(Source.name == "КПП 2")).one()
    assert source.stream_url == STREAM["stream_url"]


def test_stream_source_is_ready_without_a_video_file(session):
    from app.cv.markup import markup_from_dict
    from app.services import sources as sources_service

    source = Source(name="КПП 2", scope="gate", connection_type="stream",
                    stream_url="https://camera.example/live.m3u8", status="online")
    session.add(source)
    session.flush()

    # Поток с разметкой — готов, а не «видео не назначено».
    assert sources_service.status_of(source) == "online"
    readiness = sources_service.readiness_of(session, source, markup_from_dict(MARKUP))
    assert readiness["state"] != "no_video"

    source.stream_url = None
    assert sources_service.status_of(source) == "no_video"
    assert sources_service.readiness_of(session, source, markup_from_dict(MARKUP))["missing"] == [
        "не указана ссылка на поток"
    ]
