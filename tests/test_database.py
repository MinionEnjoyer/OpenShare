import asyncio
import sqlite3

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
            folder_columns = {
                row[1]
                for row in await (await connection.execute("PRAGMA table_info(folders)")).fetchall()
            }
            journal_mode = (await (await connection.execute("PRAGMA journal_mode")).fetchone())[0]
            return columns, folder_columns, journal_mode

    columns, folder_columns, journal_mode = run(inspect())
    assert {"folder_id", "sha256", "waveform"} <= columns
    assert {"color", "icon"} <= folder_columns
    assert journal_mode == "wal"


def test_existing_folder_rows_receive_safe_appearance_defaults(monkeypatch, tmp_path):
    legacy_database = tmp_path / "legacy" / "gallery.db"
    legacy_database.parent.mkdir(parents=True)
    with sqlite3.connect(legacy_database) as connection:
        connection.execute(
            "CREATE TABLE folders (id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL, "
            "parent_id TEXT, name TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO folders (id, owner_sub, parent_id, name) VALUES ('legacy', ?, NULL, 'Legacy')",
            (OWNER["sub"],),
        )
    monkeypatch.setattr(db, "DB_PATH", legacy_database)

    run(db.init())

    folder = run(db.folder_get("legacy"))
    assert folder["color"] == "#4f9cf9"
    assert folder["icon"] == "📁"


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
