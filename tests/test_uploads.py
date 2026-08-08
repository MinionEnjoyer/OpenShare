from pathlib import Path

import pytest

import db
import main
from conftest import OpenShareHarness, OTHER_OWNER, OWNER, PNG_1X1, TRUSTED_ORIGIN, run


pytestmark = pytest.mark.integration


def test_scoped_service_upload_persists_and_serves_image(harness: OpenShareHarness):
    response = harness.upload(("pixel.png", PNG_1X1, "image/png"), source="chat", service=True)

    assert response.status_code == 200
    assert response.json()["rejected"] == []
    saved = response.json()["saved"]
    assert len(saved) == 1
    assert saved[0]["media_type"] == "image"

    item = harness.media(saved[0]["id"])
    assert item is not None
    assert item["owner_sub"] == OWNER["sub"]
    assert item["original_name"] == "pixel.png"
    assert Path(item["storage_path"]).is_file()
    assert Path(item["thumb_path"]).is_file()

    assert harness.folders() == []
    assert item["folder_id"] is None
    assert item["source_app"] == "openchat"
    assert run(db.list_media_in_folder(OWNER["sub"], None)) == []
    assert [asset["id"] for asset in run(db.list_companion_media(OWNER["sub"], "openchat"))] == [item["id"]]
    companion = harness.client.get(
        "/api/companion-content?app_name=openchat", headers=harness.owner_headers()
    )
    assert companion.status_code == 200
    assert companion.json()[0]["name"] == "pixel.png"
    assert companion.json()[0]["viewUrl"] == f"/i/{item['id']}"

    raw = harness.client.get(f"/raw/{item['id']}")
    assert raw.status_code == 200
    assert raw.content == PNG_1X1
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in raw.headers["content-security-policy"]

    thumb = harness.client.get(f"/thumb/{item['id']}")
    assert thumb.status_code == 200
    assert thumb.content == b"deterministic-test-thumbnail"


def test_browser_owner_upload_uses_same_pipeline(harness: OpenShareHarness):
    response = harness.upload(("notes.txt", b"hello harness", "text/plain"), service=False)

    assert response.status_code == 200
    media_id = response.json()["saved"][0]["id"]
    item = harness.media(media_id)
    assert item["owner_sub"] == OWNER["sub"]
    assert item["media_type"] == "text"


def test_upload_requires_owner_or_valid_service_credentials(harness: OpenShareHarness):
    files = [("files", ("pixel.png", PNG_1X1, "image/png"))]

    anonymous = harness.client.post("/upload", headers={"Origin": TRUSTED_ORIGIN}, files=files)
    invalid = harness.client.post(
        "/upload",
        headers=harness.service_headers(key="wrong-key"),
        files=files,
    )

    assert anonymous.status_code == 401
    assert invalid.status_code == 401
    assert run(db.owner_storage_bytes(OWNER["sub"])) == 0


def test_identical_uploads_deduplicate_per_owner(harness: OpenShareHarness):
    first = harness.upload(("first.png", PNG_1X1, "image/png"))
    second = harness.upload(("renamed.png", PNG_1X1, "image/png"))

    first_id = first.json()["saved"][0]["id"]
    second_id = second.json()["saved"][0]["id"]
    assert second_id == first_id
    assert len(run(db.list_media_in_folder(OWNER["sub"], None))) == 1
    assert len(list(harness.files_dir.iterdir())) == 1


def test_historical_openchat_duplicates_are_grouped_without_breaking_old_ids(harness: OpenShareHarness):
    response = harness.upload(("sticker.png", PNG_1X1, "image/png"), source="sticker", service=True)
    original = harness.media(response.json()["saved"][0]["id"])
    duplicate = {**original, "id": "historical-duplicate", "original_name": "sticker-copy.png"}
    duplicate.pop("uploaded_at", None)
    run(db.insert_media(duplicate))

    listed = run(db.list_companion_media(OWNER["sub"], "openchat"))
    api_response = harness.client.get(
        "/api/companion-content?app_name=openchat", headers=harness.owner_headers()
    )

    assert len(listed) == 1
    assert listed[0]["duplicate_count"] == 2
    assert run(db.get_media(original["id"])) is not None
    assert run(db.get_media("historical-duplicate")) is not None
    assert api_response.json()[0]["duplicateCount"] == 2


def test_deduplication_does_not_cross_owner_boundary(harness: OpenShareHarness):
    first = harness.upload(("pixel.png", PNG_1X1, "image/png"), owner=OWNER)
    second = harness.upload(("pixel.png", PNG_1X1, "image/png"), owner=OTHER_OWNER)

    assert first.json()["saved"][0]["id"] != second.json()["saved"][0]["id"]
    assert run(db.owner_storage_bytes(OWNER["sub"])) == len(PNG_1X1)
    assert run(db.owner_storage_bytes(OTHER_OWNER["sub"])) == len(PNG_1X1)


def test_unsupported_files_are_rejected_without_storage_leaks(harness: OpenShareHarness):
    response = harness.upload(("payload.bin", b"not media", "application/octet-stream"))

    assert response.status_code == 200
    assert response.json()["saved"] == []
    assert response.json()["rejected"][0]["reason"].startswith("unsupported type")
    assert list(harness.files_dir.iterdir()) == []


def test_operator_file_count_limit_is_opt_in(harness: OpenShareHarness, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "UPLOAD_MAX_FILES", 1)

    response = harness.upload(
        ("one.png", PNG_1X1, "image/png"),
        ("two.png", PNG_1X1, "image/png"),
    )

    assert response.status_code == 413
    assert list(harness.files_dir.iterdir()) == []


def test_operator_file_size_limit_cleans_partial_upload(harness: OpenShareHarness, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "UPLOAD_MAX_BYTES", 3)

    response = harness.upload(("large.txt", b"four", "text/plain"))

    assert response.status_code == 200
    assert response.json()["saved"] == []
    assert "operator-configured" in response.json()["rejected"][0]["reason"]
    assert list(harness.files_dir.iterdir()) == []


def test_waveform_analysis_uses_scoped_auth_and_configured_limit(
    harness: OpenShareHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    files = {"file": ("clip.wav", b"wave", "audio/wav")}
    accepted = harness.client.post("/waveform", headers=harness.service_headers(), files=files)
    assert accepted.status_code == 200
    assert accepted.json() == {"peaks": [0, 25, 100, 25], "duration": 1.25}

    monkeypatch.setattr(main, "WAVEFORM_MAX_BYTES", 3)
    limited = harness.client.post("/waveform", headers=harness.service_headers(), files=files)
    assert limited.status_code == 413
