import asyncio
import string

import pytest

import main


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("filename", "mime", "expected_type", "expected_mime"),
    [
        ("photo.bin", "image/webp", "image", "image/webp"),
        ("movie.bin", "video/mp4; codecs=h264", "video", "video/mp4"),
        ("paper.bin", "application/x-pdf", "pdf", "application/pdf"),
        ("mesh.bin", "model/stl", "model", "model/stl"),
        ("clip.bin", "audio/webm;codecs=opus", "audio", "audio/webm"),
        ("data.bin", "application/json", "text", "application/json"),
        ("archive.bin", "application/x-7z-compressed", "archive", "application/x-7z-compressed"),
        ("fallback.PNG", "application/octet-stream", "image", "image/png"),
        ("fallback.MP3", "", "audio", "audio/mpeg"),
        ("script.PY", "application/octet-stream", "text", "text/plain; charset=utf-8"),
        ("model.OBJ", "application/octet-stream", "model", "application/octet-stream"),
        ("unknown.bin", "application/octet-stream", None, "application/octet-stream"),
    ],
)
def test_upload_classification_matrix(filename, mime, expected_type, expected_mime):
    assert main.classify_upload(filename, mime) == (expected_type, expected_mime)


def test_public_ids_are_url_safe_unique_and_high_entropy():
    ids = {main.new_id() for _ in range(1_000)}

    assert len(ids) == 1_000
    assert all(len(value) == 22 for value in ids)
    assert all(set(value) <= set(string.ascii_letters + string.digits) for value in ids)


def test_optional_positive_int_treats_unset_and_zero_as_unlimited(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HARNESS_LIMIT", raising=False)
    assert main.optional_positive_int("HARNESS_LIMIT") is None

    monkeypatch.setenv("HARNESS_LIMIT", "0")
    assert main.optional_positive_int("HARNESS_LIMIT") is None

    monkeypatch.setenv("HARNESS_LIMIT", "12")
    assert main.optional_positive_int("HARNESS_LIMIT") == 12


@pytest.mark.parametrize("value", ["-1", "not-a-number", "1.5"])
def test_optional_positive_int_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, value: str):
    monkeypatch.setenv("HARNESS_LIMIT", value)
    with pytest.raises(RuntimeError):
        main.optional_positive_int("HARNESS_LIMIT")


def test_bounded_processing_applies_timeout(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "PROCESSING_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(main, "_processing_semaphore", None)

    async def slow():
        await asyncio.sleep(0.05)

    with pytest.raises(TimeoutError):
        asyncio.run(main.bounded_processing(slow()))


def test_humanize_bytes_uses_readable_units():
    assert main.humanize_bytes(0) == "0 B"
    assert main.humanize_bytes(1024) == "1.0 KB"
    assert main.humanize_bytes(5 * 1024 * 1024) == "5.0 MB"
