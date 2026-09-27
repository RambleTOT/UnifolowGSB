"""Проверка API: вход, источники, разметка, настройки.

Тест поднимает приложение на временной базе и пустом каталоге видео: рабочие
потоки источников при этом не запускаются, проверяется именно контракт API.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("uniflow")
    os.environ.update(
        {
            "UNIFLOW_DATABASE_URL": f"sqlite:///{root / 'test.db'}",
            "UNIFLOW_VIDEO_DIR": str(root / "videos"),
            "UNIFLOW_SNAPSHOT_DIR": str(root / "snapshots"),
            "UNIFLOW_CACHE_DIR": str(root / "cache"),
            "UNIFLOW_SECRET_KEY": "test-secret-key",
            "UNIFLOW_ADMIN_LOGIN": "admin",
            "UNIFLOW_ADMIN_PASSWORD": "test-password-123",
        }
    )

    from app.core.config import get_settings

    get_settings.cache_clear()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as active:
        yield active


@pytest.fixture(scope="module")
def signed_in(client):
    response = client.post(
        "/api/auth/login", json={"login": "admin", "password": "test-password-123"}
    )
    assert response.status_code == 200
    return client


def test_health_reports_device(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["device"] in ("cpu", "mps", "cuda")
    assert body["deviceTitle"]
    assert isinstance(body["startedAt"], int)


def test_protected_routes_require_session(client):
    response = client.get("/api/sources")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_login_rejects_wrong_password(client):
    response = client.post("/api/auth/login", json={"login": "admin", "password": "нет"})
    assert response.status_code == 401
    # Сообщение не раскрывает, логин неверен или пароль.
    assert response.json()["error"]["message"] == "Неверный логин или пароль."


def test_login_attempts_are_rate_limited(client):
    """Перебор пароля должен упираться в паузу, а не в подсказку."""
    codes = []
    for _ in range(12):
        response = client.post(
            "/api/auth/login", json={"login": "подбиратель", "password": "нет"}
        )
        codes.append(response.json()["error"]["code"])

    assert codes[0] == "invalid_credentials"
    assert codes[-1] == "too_many_attempts"


def test_login_returns_profile_start_point(signed_in):
    user = signed_in.get("/api/auth/me").json()["user"]
    assert user["login"] == "admin"
    assert user["profile"] == "admin"
    assert user["start"] == {"section": "sources", "scope": "all"}


def test_bootstrap_creates_four_sources(signed_in):
    body = signed_in.get("/api/sources").json()
    names = [source["name"] for source in body["sources"]]
    assert names == ["Столовая", "Раздача", "КПП 1", "КПП 2"]
    # Источник без видео — нормальное состояние, а не сбой.
    assert all(source["readiness"]["state"] == "no_video" for source in body["sources"])
    assert body["dataStatus"]["state"] == "no_sources"


def test_source_lifecycle(signed_in):
    created = signed_in.post(
        "/api/sources",
        json={"name": "КПП 3", "scope": "gate", "location": "Временный проход"},
    ).json()["source"]
    assert created["readiness"]["state"] == "no_video"

    duplicate = signed_in.post("/api/sources", json={"name": "КПП 3", "scope": "gate"})
    assert duplicate.status_code == 422
    assert "name" in duplicate.json()["error"]["details"]["fields"]

    renamed = signed_in.patch(
        f"/api/sources/{created['id']}", json={"name": "КПП 3 — временный"}
    ).json()["source"]
    assert renamed["name"] == "КПП 3 — временный"

    disabled = signed_in.post(f"/api/sources/{created['id']}/disable").json()["source"]
    assert disabled["enabled"] is False
    assert disabled["status"] == "disabled"

    removed = signed_in.delete(f"/api/sources/{created['id']}")
    assert removed.status_code == 200
    assert "остались" in removed.json()["message"]

    listed = signed_in.get("/api/sources").json()["sources"]
    assert all(source["id"] != created["id"] for source in listed)


def test_stream_source_accepts_only_network_links(signed_in):
    rejected = signed_in.post(
        "/api/sources",
        json={"name": "Камера по ссылке", "scope": "gate", "connection_type": "stream",
              "stream_url": "ftp://camera.example/live", "enabled": False},
    )
    assert rejected.status_code == 422
    assert "stream_url" in rejected.json()["error"]["details"]["fields"]


def test_stream_source_lifecycle(signed_in):
    # Выключен сразу: рабочий поток к несуществующей камере в тестах не нужен.
    created = signed_in.post(
        "/api/sources",
        json={"name": "Площадь", "scope": "gate", "connection_type": "stream",
              "stream_url": "  https://camera.example/public/live.m3u8  ", "enabled": False},
    ).json()
    source = created["source"]
    assert source["connectionType"] == "stream"
    assert source["streamUrl"] == "https://camera.example/public/live.m3u8"
    assert source["video"] is None
    # Ссылка есть, разметки нет — следующий шаг разметка, а не загрузка видео.
    assert source["readiness"]["state"] != "no_video"
    assert created["nextStep"] == "markup"

    cleared = signed_in.patch(f"/api/sources/{source['id']}", json={"stream_url": ""}).json()["source"]
    assert cleared["streamUrl"] is None
    assert cleared["readiness"] == {"state": "no_video", "missing": ["не указана ссылка на поток"]}

    signed_in.delete(f"/api/sources/{source['id']}")


def test_markup_validation_and_save(signed_in):
    broken = signed_in.put(
        "/api/sources/1/geometry",
        json={
            "anchor": "bottom_center",
            "lines": [
                {"id": "l1", "name": "Коротышка", "a": [0.5, 0.5], "b": [0.51, 0.5],
                 "entry_side": -1}
            ],
            "zones": [],
        },
    )
    assert broken.status_code == 422
    assert broken.json()["error"]["details"]["objects"][0]["code"] == "line_too_short"

    saved = signed_in.put(
        "/api/sources/1/geometry",
        json={
            "anchor": "bottom_center",
            "lines": [
                {"id": "line-main", "name": "Основной проход", "a": [0.15, 0.55],
                 "b": [0.85, 0.55], "entry_side": -1, "counts": "both"}
            ],
            "zones": [
                {"id": "zone-queue", "name": "Очередь", "kind": "queue",
                 "min_dwell_seconds": 5,
                 "polygon": [[0.1, 0.6], [0.6, 0.6], [0.6, 0.95], [0.1, 0.95]]}
            ],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert "История не пересчитывается" in body["message"]
    assert body["markup"]["lines"][0]["name"] == "Основной проход"
    # Видео источнику не назначено, поэтому готовность так и говорит: считать
    # нечего, даже если разметка уже есть.
    assert body["source"]["readiness"]["state"] == "no_video"
    # Главная метрика определяется разметкой: есть линия — значит поток.
    assert body["source"]["primaryMetric"] == "flow"


def test_settings_bounds_and_reset(signed_in):
    out_of_range = signed_in.put("/api/settings", json={"retention_days": 4000})
    assert out_of_range.status_code == 422
    assert "retention_days" in out_of_range.json()["error"]["details"]["fields"]

    saved = signed_in.put("/api/settings", json={"queue_threshold": 14}).json()
    assert saved["values"]["queue_threshold"] == 14
    assert saved["restarted"] is False

    restored = signed_in.post("/api/settings/reset").json()
    assert restored["values"]["queue_threshold"] == 10


def test_unknown_source_returns_readable_error(signed_in):
    response = signed_in.get("/api/sources/999")
    assert response.status_code == 404
    assert response.json()["error"]["message"].startswith("Источник не найден")
