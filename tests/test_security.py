import asyncio
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import db
import main
from conftest import OpenShareHarness, PNG_1X1


def request_with_headers(*headers: tuple[str, str], session=None) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/upload",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers],
        "session": session or {},
    })


@pytest.mark.unit
def test_service_identity_is_scoped_away_from_owner_routes():
    request = request_with_headers(
        ("authorization", "Bearer test-share-key"),
        ("x-share-user-sub", "victim"),
    )
    assert main.require_upload_user(request)["sub"] == "victim"
    with pytest.raises(HTTPException) as exc:
        main.require_user(request)
    assert exc.value.status_code == 401


@pytest.mark.unit
def test_invalid_service_key_cannot_fall_back_to_a_browser_session():
    request = request_with_headers(
        ("authorization", "Bearer wrong"),
        ("x-share-user-sub", "victim"),
        session={"user": {"sub": "real-user", "preferred_username": "real"}},
    )
    with pytest.raises(HTTPException) as exc:
        main.require_upload_user(request)
    assert exc.value.status_code == 401


@pytest.mark.integration
def test_legacy_openchat_asset_upload_uses_scoped_service_key(harness: OpenShareHarness):
    response = harness.client.post(
        "/api/assets",
        headers={"Authorization": "Bearer test-share-key"},
        data={"source": "chat"},
        files={"file": ("sticker.png", PNG_1X1, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "sticker.png"
    assert payload["mimeType"] == "image/png"
    assert payload["mediaType"] == "image"
    assert harness.media(payload["id"])["owner_sub"] == "openchat-service"


@pytest.mark.integration
def test_legacy_openchat_asset_upload_rejects_wrong_service_key(harness: OpenShareHarness):
    response = harness.client.post(
        "/api/assets",
        headers={"Authorization": "Bearer wrong"},
        files={"file": ("sticker.png", b"not-a-real-image", "image/png")},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_cross_origin_mutation_is_rejected(harness: OpenShareHarness):
    response = harness.client.post(
        "/bulk/delete",
        headers={
            "origin": "https://evil.example",
            "x-test-owner-sub": "owner-1",
            "x-test-owner-name": "owner",
        },
        json={"ids": []},
    )
    assert response.status_code == 403


@pytest.mark.unit
def test_uploaded_html_is_served_as_plain_text(monkeypatch, tmp_path: Path):
    html = tmp_path / "payload.html"
    html.write_text("<script>window.pwned = true</script>", encoding="utf-8")
    monkeypatch.setattr(main.db, "get_media", AsyncMock(return_value={
        "id": "asset",
        "storage_path": str(html),
        "mime_type": "text/html",
        "media_type": "text",
    }))
    response = asyncio.run(main.raw("asset"))
    assert response.media_type == "text/plain; charset=utf-8"


@pytest.mark.unit
def test_active_file_inside_bundle_is_served_as_plain_text(monkeypatch, tmp_path: Path):
    files_dir = tmp_path / "files"
    bundle_dir = files_dir / "asset"
    bundle_dir.mkdir(parents=True)
    html = bundle_dir / "payload.html"
    html.write_text("<script>window.pwned = true</script>", encoding="utf-8")
    monkeypatch.setattr(main, "FILES_DIR", files_dir)
    monkeypatch.setattr(main.db, "get_media", AsyncMock(return_value={
        "id": "asset",
        "storage_path": str(html),
        "mime_type": "text/html",
        "media_type": "model",
    }))
    response = asyncio.run(main.raw_bundle_file("asset", "payload.html"))
    assert response.media_type == "text/plain; charset=utf-8"


@pytest.mark.unit
def test_archive_expansion_limit_is_opt_in_and_enforced(monkeypatch, tmp_path: Path):
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("model.obj", "v 0 0 0\n")
        bundle.writestr("texture.png", b"0" * 1024)
    monkeypatch.setattr(main, "FILES_DIR", tmp_path / "files")
    monkeypatch.setattr(main, "ARCHIVE_EXPANDED_MAX_BYTES", 100)
    with pytest.raises(HTTPException) as exc:
        main._extract_zip_bundle(archive, "asset")
    assert exc.value.status_code == 413


@pytest.mark.unit
def test_new_public_ids_have_128_bits_of_entropy_or_more():
    assert len(main.new_id()) >= 22


@pytest.mark.unit
def test_sqlite_connections_enable_integrity_and_locking_pragmas(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "gallery.db")

    async def inspect():
        async with db.connect_db() as connection:
            foreign_keys = (await (await connection.execute("PRAGMA foreign_keys")).fetchone())[0]
            busy_timeout = (await (await connection.execute("PRAGMA busy_timeout")).fetchone())[0]
            return foreign_keys, busy_timeout

    assert asyncio.run(inspect()) == (1, 30_000)
