import io
import zipfile

import pytest

from conftest import OpenShareHarness, OTHER_OWNER, OWNER, PNG_1X1


pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("filename", "content", "mime", "media_type", "route"),
    [
        ("pixel.png", PNG_1X1, "image/png", "image", "i"),
        ("movie.mp4", b"fake video", "video/mp4", "video", "v"),
        ("paper.pdf", b"%PDF-1.7 fake", "application/pdf", "pdf", "d"),
        ("notes.py", b"print('hello')", "text/x-python", "text", "t"),
        ("clip.wav", b"fake audio", "audio/wav", "audio", "au"),
        ("mesh.stl", b"solid test\nendsolid", "model/stl", "model", "m"),
    ],
)
def test_public_viewer_matrix(
    harness: OpenShareHarness,
    filename: str,
    content: bytes,
    mime: str,
    media_type: str,
    route: str,
):
    upload = harness.upload((filename, content, mime))
    saved = upload.json()["saved"][0]

    viewer = harness.client.get(f"/{route}/{saved['id']}")
    wrong_viewer = harness.client.get(f"/i/{saved['id']}") if route != "i" else harness.client.get(f"/v/{saved['id']}")

    assert saved["media_type"] == media_type
    assert viewer.status_code == 200
    assert filename in viewer.text
    assert wrong_viewer.status_code == 404


def test_text_view_escapes_active_content_and_raw_is_plain_text(harness: OpenShareHarness):
    payload = b"<script>window.pwned = true</script>"
    media_id = harness.upload(("payload.html", payload, "text/html")).json()["saved"][0]["id"]

    viewer = harness.client.get(f"/t/{media_id}")
    raw = harness.client.get(f"/raw/{media_id}")

    assert viewer.status_code == 200
    assert "&lt;script&gt;" in viewer.text
    assert "<script>window.pwned" not in viewer.text
    assert raw.headers["content-type"].startswith("text/plain")
    assert raw.content == payload


def test_audio_upload_exposes_stored_waveform(harness: OpenShareHarness):
    media_id = harness.upload(("clip.wav", b"fake audio", "audio/wav")).json()["saved"][0]["id"]

    response = harness.client.get(f"/waveform/{media_id}")

    assert response.status_code == 200
    assert response.json() == {"peaks": [0, 25, 100, 25], "duration": 1.25}


def test_regular_zip_stays_downloadable_archive(harness: OpenShareHarness):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("readme.txt", "hello")

    saved = harness.upload(("files.zip", output.getvalue(), "application/zip")).json()["saved"][0]

    assert saved["media_type"] == "archive"
    assert harness.client.get(f"/a/{saved['id']}").status_code == 200
    assert harness.client.get(f"/raw/{saved['id']}").content == output.getvalue()


def test_zipped_model_bundle_is_extracted_and_relative_files_are_served(harness: OpenShareHarness):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("nested/model.obj", "mtllib material.mtl\nv 0 0 0\n")
        archive.writestr("nested/material.mtl", "newmtl test\n")

    saved = harness.upload(("model.zip", output.getvalue(), "application/zip")).json()["saved"][0]
    redirect = harness.client.get(f"/raw/{saved['id']}", follow_redirects=False)
    primary = harness.client.get(f"/raw/{saved['id']}/model.obj")
    material = harness.client.get(f"/raw/{saved['id']}/material.mtl")

    assert saved == {"id": saved["id"], "media_type": "model", "bundle": True}
    assert redirect.status_code == 302
    assert redirect.headers["location"].endswith("/model.obj")
    assert primary.text.startswith("mtllib material.mtl")
    assert material.text == "newmtl test\n"


def test_missing_raw_and_thumbnail_return_404(harness: OpenShareHarness):
    assert harness.client.get("/raw/missing").status_code == 404
    assert harness.client.get("/thumb/missing").status_code == 404


def test_single_delete_cannot_remove_another_owners_file(harness: OpenShareHarness):
    media_id = harness.upload(("private.png", PNG_1X1, "image/png"), owner=OTHER_OWNER).json()["saved"][0]["id"]

    denied = harness.client.post(
        f"/delete/{media_id}",
        headers=harness.owner_headers(OWNER),
        follow_redirects=False,
    )

    assert denied.status_code == 403
    assert harness.media(media_id) is not None
