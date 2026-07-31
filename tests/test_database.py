import asyncio

import pytest

import db
from conftest import OpenShareHarness, OWNER, run


pytestmark = pytest.mark.integration


def media_row(index: int) -> dict:
    return {
        "id": f"media-{index}",
        "owner_sub": OWNER["sub"],
        "owner_username": OWNER["username"],
        "media_type": "text",
        "original_name": f"file-{index}.txt",
        "storage_path": f"/tmp/file-{index}.txt",
        "thumb_path": None,
        "mime_type": "text/plain",
        "size_bytes": index + 1,
        "width": None,
        "height": None,
        "duration_s": None,
        "folder_id": None,
        "sha256": f"hash-{index}",
        "waveform": None,
    }


def test_schema_initialization_is_idempotent_and_complete(harness: OpenShareHarness):
    run(db.init())

    async def inspect():
        async with db.connect_db() as connection:
            columns = {
                row[1]
                for row in await (await connection.execute("PRAGMA table_info(media)")).fetchall()
            }
            journal_mode = (await (await connection.execute("PRAGMA journal_mode")).fetchone())[0]
            return columns, journal_mode

    columns, journal_mode = run(inspect())
    assert {"folder_id", "sha256", "waveform"} <= columns
    assert journal_mode == "wal"


def test_concurrent_writes_complete_without_database_locked(harness: OpenShareHarness):
    async def insert_all():
        await asyncio.gather(*(db.insert_media(media_row(index)) for index in range(20)))

    run(insert_all())

    rows = run(db.list_media_in_folder(OWNER["sub"], None))
    assert len(rows) == 20
    assert run(db.owner_storage_bytes(OWNER["sub"])) == sum(range(1, 21))


def test_search_is_case_insensitive_and_owner_scoped(harness: OpenShareHarness):
    first = media_row(1)
    first["original_name"] = "Quarterly-REPORT.txt"
    second = media_row(2)
    second.update({"id": "other", "owner_sub": "owner-2", "sha256": "other-hash"})
    run(db.insert_media(first))
    run(db.insert_media(second))

    results = run(db.search_media(OWNER["sub"], "report"))

    assert [row["id"] for row in results] == [first["id"]]


def test_folder_delete_reparents_direct_descendants(harness: OpenShareHarness):
    run(db.folder_create("parent", OWNER["sub"], "Parent", None))
    run(db.folder_create("child", OWNER["sub"], "Child", "parent"))
    row = media_row(1)
    row["folder_id"] = "parent"
    run(db.insert_media(row))

    assert run(db.folder_delete("parent", OWNER["sub"])) is True
    assert run(db.folder_get("child"))["parent_id"] is None
    assert run(db.get_media(row["id"]))["folder_id"] is None
