import asyncio
import base64
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The application reads these at import time. Tests replace every persistence path
# with a per-test temporary directory before starting the ASGI lifespan.
os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-long-enough")
os.environ.setdefault("OIDC_CLIENT_ID", "test-client")
os.environ.setdefault("OIDC_CLIENT_SECRET", "test-secret")
os.environ.setdefault("OIDC_ISSUER", "https://auth.example.test/application/o/openshare/")
os.environ.setdefault("PUBLIC_URL", "https://share.example.test")
os.environ.setdefault("SHARE_API_KEY", "test-share-key")
os.environ.setdefault("STORAGE_ROOT", "/tmp/openshare-pytest-storage")
os.environ.setdefault("DATABASE_FILE", "/tmp/openshare-pytest.db")

import db  # noqa: E402
import main  # noqa: E402


OWNER = {"sub": "owner-1", "username": "owner"}
OTHER_OWNER = {"sub": "owner-2", "username": "other"}
TRUSTED_ORIGIN = "https://share.example.test"

# Valid 1x1 PNG. Keeping it inline makes the harness self-contained and avoids
# binary fixtures that are awkward to review in pull requests.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def run(coro):
    """Run one of OpenShare's async DB helpers from a synchronous pytest test."""
    return asyncio.run(coro)


@dataclass
class OpenShareHarness:
    client: TestClient
    root: Path
    files_dir: Path
    thumbs_dir: Path
    database: Path

    def owner_headers(self, owner: dict[str, str] = OWNER) -> dict[str, str]:
        return {
            "Origin": TRUSTED_ORIGIN,
            "X-Test-Owner-Sub": owner["sub"],
            "X-Test-Owner-Name": owner["username"],
        }

    def service_headers(self, owner: dict[str, str] = OWNER, key: str = "test-share-key") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {key}",
            "X-Share-User-Sub": owner["sub"],
            "X-Share-User-Name": owner["username"],
        }

    def upload(
        self,
        *files: tuple[str, bytes, str],
        owner: dict[str, str] = OWNER,
        source: str = "",
        folder_id: str = "",
        service: bool = True,
    ):
        headers = self.service_headers(owner) if service else self.owner_headers(owner)
        data = {"source": source, "folder_id": folder_id}
        multipart = [("files", (name, content, mime)) for name, content, mime in files]
        return self.client.post("/upload", headers=headers, data=data, files=multipart)

    def media(self, media_id: str) -> dict[str, Any] | None:
        return run(db.get_media(media_id))

    def folders(self, owner: dict[str, str] = OWNER) -> list[dict[str, Any]]:
        return run(db.folder_list_all_for_owner(owner["sub"]))


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> OpenShareHarness:
    storage = tmp_path / "storage"
    files_dir = storage / "files"
    thumbs_dir = storage / "thumbs"
    database = tmp_path / "data" / "gallery.db"

    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(main, "STORAGE_ROOT", storage)
    monkeypatch.setattr(main, "FILES_DIR", files_dir)
    monkeypatch.setattr(main, "THUMBS_DIR", thumbs_dir)

    # Operator limits are tested by opting in within individual tests. The harness
    # baseline mirrors a default self-hosted deployment: no implicit upload caps.
    for setting in (
        "UPLOAD_MAX_FILES", "UPLOAD_MAX_BYTES", "UPLOAD_TOTAL_MAX_BYTES",
        "ARCHIVE_MAX_BYTES", "ARCHIVE_EXPANDED_MAX_BYTES", "ARCHIVE_MAX_ENTRIES",
        "PROCESSING_MAX_CONCURRENCY", "PROCESSING_TIMEOUT_SECONDS", "WAVEFORM_MAX_BYTES",
    ):
        monkeypatch.setattr(main, setting, None)
    monkeypatch.setattr(main, "_processing_semaphore", None)

    def write_thumb(_src: Path, dst: Path, result=(1, 1)):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"deterministic-test-thumbnail")
        return result

    async def image_like(src: Path, dst: Path):
        return write_thumb(src, dst)

    async def video_thumb(src: Path, dst: Path):
        return write_thumb(src, dst, (320, 180, 12.5))

    async def waveform(_src: Path):
        return [0, 25, 100, 25], 1.25

    async def transcode(_src: Path, _dst: Path):
        return False

    monkeypatch.setattr(main.thumbs, "make_image_thumb", write_thumb)
    monkeypatch.setattr(main.thumbs, "make_video_thumb", video_thumb)
    monkeypatch.setattr(main.thumbs, "make_pdf_thumb", image_like)
    monkeypatch.setattr(main.thumbs, "make_text_thumb", image_like)
    monkeypatch.setattr(main.thumbs, "make_model_thumb", image_like)
    monkeypatch.setattr(main.thumbs, "make_audio_waveform", waveform)
    monkeypatch.setattr(main.thumbs, "transcode_audio_to_mp3", transcode)

    original_upload_user = main.require_upload_user

    def test_owner(request: Request) -> dict[str, str]:
        sub = request.headers.get("x-test-owner-sub", "").strip()
        if not sub:
            raise HTTPException(status_code=401, detail="test owner header missing")
        return {
            "sub": sub,
            "username": request.headers.get("x-test-owner-name", "").strip() or sub,
        }

    def test_upload_user(request: Request) -> dict[str, str]:
        if request.headers.get("x-test-owner-sub"):
            return test_owner(request)
        return original_upload_user(request)

    main.app.dependency_overrides[main.require_user] = test_owner
    main.app.dependency_overrides[main.require_upload_user] = test_upload_user
    try:
        with TestClient(main.app, base_url=TRUSTED_ORIGIN) as client:
            yield OpenShareHarness(client, storage, files_dir, thumbs_dir, database)
    finally:
        main.app.dependency_overrides.clear()
