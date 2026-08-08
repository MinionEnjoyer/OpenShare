import aiosqlite
import os
from contextlib import asynccontextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DATABASE_FILE", "/data/gallery.db"))


@asynccontextmanager
async def connect_db():
    db = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA busy_timeout=30000")
        yield db
    finally:
        await db.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id              TEXT PRIMARY KEY,
    owner_sub       TEXT NOT NULL,
    owner_username  TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    thumb_path      TEXT,
    mime_type       TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    width           INTEGER,
    height          INTEGER,
    duration_s      REAL,
    source_app      TEXT NOT NULL DEFAULT 'personal',
    uploaded_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_media_owner_time ON media (owner_sub, uploaded_at DESC);

CREATE TABLE IF NOT EXISTS folders (
    id          TEXT PRIMARY KEY,
    owner_sub   TEXT NOT NULL,
    parent_id   TEXT REFERENCES folders(id) ON DELETE SET NULL,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL DEFAULT '#4f9cf9',
    icon        TEXT NOT NULL DEFAULT '📁',
    preview_mode TEXT NOT NULL DEFAULT 'icon',
    preview_media_id TEXT REFERENCES media(id) ON DELETE SET NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_folders_owner_parent ON folders (owner_sub, parent_id);

CREATE TABLE IF NOT EXISTS share_links (
    id          TEXT PRIMARY KEY,
    folder_id   TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    owner_sub   TEXT NOT NULL,
    legacy_path TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at  TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_share_links_owner_created ON share_links (owner_sub, created_at DESC);

CREATE TABLE IF NOT EXISTS media_share_links (
    id          TEXT PRIMARY KEY,
    media_id    TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    owner_sub   TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at  TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_media_share_links_owner_created
ON media_share_links (owner_sub, created_at DESC);

CREATE TABLE IF NOT EXISTS mirror_events (
    id          TEXT PRIMARY KEY,
    origin_node TEXT NOT NULL,
    payload     TEXT NOT NULL,
    file_path   TEXT,
    digest      TEXT NOT NULL,
    applied_at  TIMESTAMP,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mirror_deliveries (
    event_id       TEXT NOT NULL REFERENCES mirror_events(id) ON DELETE CASCADE,
    peer_node      TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at  TIMESTAMP,
    last_error    TEXT,
    PRIMARY KEY (event_id, peer_node)
);
CREATE INDEX IF NOT EXISTS idx_mirror_delivery_pending ON mirror_deliveries (delivered_at, next_attempt_at);
"""


async def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with connect_db() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA)
        async with db.execute("PRAGMA table_info(folders)") as cur:
            folder_cols = {r[1] for r in await cur.fetchall()}
        if "color" not in folder_cols:
            await db.execute("ALTER TABLE folders ADD COLUMN color TEXT NOT NULL DEFAULT '#4f9cf9'")
        if "icon" not in folder_cols:
            await db.execute("ALTER TABLE folders ADD COLUMN icon TEXT NOT NULL DEFAULT '📁'")
        if "preview_mode" not in folder_cols:
            await db.execute("ALTER TABLE folders ADD COLUMN preview_mode TEXT NOT NULL DEFAULT 'icon'")
        if "preview_media_id" not in folder_cols:
            await db.execute(
                "ALTER TABLE folders ADD COLUMN preview_media_id TEXT REFERENCES media(id) ON DELETE SET NULL"
            )
        async with db.execute("PRAGMA table_info(share_links)") as cur:
            share_cols = {r[1] for r in await cur.fetchall()}
        if "legacy_path" not in share_cols:
            await db.execute("ALTER TABLE share_links ADD COLUMN legacy_path TEXT")
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_share_links_owner_legacy "
            "ON share_links (owner_sub, legacy_path)"
        )
        async with db.execute("PRAGMA table_info(media)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        if "folder_id" not in cols:
            await db.execute(
                "ALTER TABLE media ADD COLUMN folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_owner_folder ON media (owner_sub, folder_id)"
            )

        # If the media table still has the old CHECK constraint (image/video only),
        # rebuild it without one so we can store new media_type values like 'pdf'.
        async with db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='media'"
        ) as cur:
            row = await cur.fetchone()
        if row and "'image','video'" in row[0] and "'pdf'" not in row[0]:
            await db.executescript("""
                PRAGMA foreign_keys = OFF;
                BEGIN;
                CREATE TABLE media_new (
                    id              TEXT PRIMARY KEY,
                    owner_sub       TEXT NOT NULL,
                    owner_username  TEXT NOT NULL,
                    media_type      TEXT NOT NULL,
                    original_name   TEXT NOT NULL,
                    storage_path    TEXT NOT NULL,
                    thumb_path      TEXT,
                    mime_type       TEXT NOT NULL,
                    size_bytes      INTEGER NOT NULL,
                    width           INTEGER,
                    height          INTEGER,
                    duration_s      REAL,
                    uploaded_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    folder_id       TEXT REFERENCES folders(id) ON DELETE SET NULL
                );
                INSERT INTO media_new (id, owner_sub, owner_username, media_type, original_name,
                    storage_path, thumb_path, mime_type, size_bytes, width, height, duration_s,
                    uploaded_at, folder_id)
                SELECT id, owner_sub, owner_username, media_type, original_name,
                    storage_path, thumb_path, mime_type, size_bytes, width, height, duration_s,
                    uploaded_at, folder_id FROM media;
                DROP TABLE media;
                ALTER TABLE media_new RENAME TO media;
                CREATE INDEX idx_media_owner_time ON media (owner_sub, uploaded_at DESC);
                CREATE INDEX idx_media_owner_folder ON media (owner_sub, folder_id);
                COMMIT;
                PRAGMA foreign_keys = ON;
            """)

        # Content hash for de-duplication (added later; nullable for existing rows).
        async with db.execute("PRAGMA table_info(media)") as cur:
            cols2 = {r[1] for r in await cur.fetchall()}
        if "sha256" not in cols2:
            await db.execute("ALTER TABLE media ADD COLUMN sha256 TEXT")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_media_owner_hash ON media (owner_sub, sha256)")

        # Audio-level peaks (JSON array) for the waveform preview; nullable for existing rows.
        async with db.execute("PRAGMA table_info(media)") as cur:
            cols3 = {r[1] for r in await cur.fetchall()}
        if "waveform" not in cols3:
            await db.execute("ALTER TABLE media ADD COLUMN waveform TEXT")

        # Companion uploads live in a separate logical collection instead of a
        # user-visible magic folder. Migrate the folder created by older builds
        # only when this column is first introduced.
        async with db.execute("PRAGMA table_info(media)") as cur:
            cols4 = {r[1] for r in await cur.fetchall()}
        if "source_app" not in cols4:
            await db.execute(
                "ALTER TABLE media ADD COLUMN source_app TEXT NOT NULL DEFAULT 'personal'"
            )
            await db.execute(
                "UPDATE media SET source_app='openchat', folder_id=NULL WHERE folder_id IN ("
                "SELECT id FROM folders WHERE parent_id IS NULL AND name='Chat')"
            )
            await db.execute(
                "DELETE FROM folders WHERE parent_id IS NULL AND name='Chat' "
                "AND NOT EXISTS (SELECT 1 FROM media WHERE media.folder_id=folders.id) "
                "AND NOT EXISTS (SELECT 1 FROM folders child WHERE child.parent_id=folders.id)"
            )

        await db.commit()


# ---------- media ----------

async def insert_media(item: dict):
    async with connect_db() as db:
        cols = ",".join(item.keys())
        placeholders = ",".join(["?"] * len(item))
        await db.execute(f"INSERT INTO media ({cols}) VALUES ({placeholders})", tuple(item.values()))
        await db.commit()


async def find_media_by_hash(owner_sub: str, sha256: str, source_app: str = "personal"):
    """Return an existing media row with the same owner + content hash, for de-duplication."""
    if not sha256:
        return None
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM media WHERE owner_sub=? AND sha256=? AND source_app=? LIMIT 1",
            (owner_sub, sha256, source_app),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_media(media_id: str):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE id=?", (media_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _list_media_in_folder(connection, owner_sub: str, folder_id: str | None):
    if folder_id is None:
        sql = (
            "SELECT * FROM media WHERE owner_sub=? AND folder_id IS NULL "
            "AND source_app='personal' ORDER BY uploaded_at DESC"
        )
        args: tuple = (owner_sub,)
    else:
        sql = (
            "SELECT * FROM media WHERE owner_sub=? AND folder_id=? "
            "AND source_app='personal' ORDER BY uploaded_at DESC"
        )
        args = (owner_sub, folder_id)
    async with connection.execute(sql, args) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def list_media_in_folder(owner_sub: str, folder_id: str | None):
    async with connect_db() as connection:
        connection.row_factory = aiosqlite.Row
        return await _list_media_in_folder(connection, owner_sub, folder_id)


async def delete_media(media_id: str, owner_sub: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "DELETE FROM media WHERE id=? AND owner_sub=?", (media_id, owner_sub)
        )
        await db.commit()
        return cur.rowcount > 0


async def move_media(media_id: str, owner_sub: str, folder_id: str | None) -> bool:
    async with connect_db() as db:
        if folder_id is not None:
            async with db.execute(
                "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
            ) as cur:
                if not await cur.fetchone():
                    return False
        await db.execute(
            "UPDATE folders SET preview_mode='icon', preview_media_id=NULL "
            "WHERE owner_sub=? AND preview_media_id=?",
            (owner_sub, media_id),
        )
        cur = await db.execute(
            "UPDATE media SET folder_id=? WHERE id=? AND owner_sub=?",
            (folder_id, media_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def bulk_move_media(ids: list[str], owner_sub: str, folder_id: str | None) -> int:
    if not ids:
        return 0
    async with connect_db() as db:
        if folder_id is not None:
            async with db.execute(
                "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
            ) as cur:
                if not await cur.fetchone():
                    return 0
        placeholders = ",".join(["?"] * len(ids))
        await db.execute(
            f"UPDATE folders SET preview_mode='icon', preview_media_id=NULL "
            f"WHERE owner_sub=? AND preview_media_id IN ({placeholders})",
            (owner_sub, *ids),
        )
        cur = await db.execute(
            f"UPDATE media SET folder_id=? WHERE owner_sub=? AND id IN ({placeholders})",
            (folder_id, owner_sub, *ids),
        )
        await db.commit()
        return cur.rowcount


async def bulk_delete_media(ids: list[str], owner_sub: str) -> list[dict]:
    """Returns the rows of media that were deleted, for caller to clean up storage."""
    if not ids:
        return []
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        placeholders = ",".join(["?"] * len(ids))
        async with db.execute(
            f"SELECT * FROM media WHERE owner_sub=? AND id IN ({placeholders})",
            (owner_sub, *ids),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        if not rows:
            return []
        owned_ids = [r["id"] for r in rows]
        op = ",".join(["?"] * len(owned_ids))
        await db.execute(
            f"DELETE FROM media WHERE owner_sub=? AND id IN ({op})",
            (owner_sub, *owned_ids),
        )
        await db.commit()
        return rows


# ---------- folders ----------

async def folder_create(
    folder_id: str,
    owner_sub: str,
    name: str,
    parent_id: str | None,
    color: str = "#4f9cf9",
    icon: str = "📁",
) -> bool:
    async with connect_db() as db:
        if parent_id is not None:
            async with db.execute(
                "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (parent_id, owner_sub)
            ) as cur:
                if not await cur.fetchone():
                    return False
        await db.execute(
            "INSERT INTO folders (id, owner_sub, parent_id, name, color, icon) VALUES (?, ?, ?, ?, ?, ?)",
            (folder_id, owner_sub, parent_id, name.strip()[:120], color, icon),
        )
        await db.commit()
        return True


async def folder_get(folder_id: str):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM folders WHERE id=?", (folder_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _folder_list_children(connection, owner_sub: str, parent_id: str | None):
    if parent_id is None:
        sql = (
            "SELECT f.*, "
            "(SELECT COUNT(*) FROM folders child WHERE child.parent_id=f.id) AS child_count, "
            "(SELECT COUNT(*) FROM media item WHERE item.folder_id=f.id "
            "AND item.source_app='personal') AS item_count "
            "FROM folders f WHERE f.owner_sub=? AND f.parent_id IS NULL ORDER BY f.name"
        )
        args: tuple = (owner_sub,)
    else:
        sql = (
            "SELECT f.*, "
            "(SELECT COUNT(*) FROM folders child WHERE child.parent_id=f.id) AS child_count, "
            "(SELECT COUNT(*) FROM media item WHERE item.folder_id=f.id "
            "AND item.source_app='personal') AS item_count "
            "FROM folders f WHERE f.owner_sub=? AND f.parent_id=? ORDER BY f.name"
        )
        args = (owner_sub, parent_id)
    async with connection.execute(sql, args) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def folder_list_children(owner_sub: str, parent_id: str | None):
    async with connect_db() as connection:
        connection.row_factory = aiosqlite.Row
        return await _folder_list_children(connection, owner_sub, parent_id)


async def _folder_breadcrumb(connection, folder_id: str | None):
    """Return list from root → folder. Each entry: {id, name}. Empty for root."""
    if folder_id is None:
        return []
    chain = []
    seen = set()
    cur_id = folder_id
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        async with connection.execute(
            "SELECT id, name, parent_id FROM folders WHERE id=?", (cur_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            break
        chain.append({"id": row["id"], "name": row["name"]})
        cur_id = row["parent_id"]
    chain.reverse()
    return chain


async def folder_breadcrumb(folder_id: str | None):
    async with connect_db() as connection:
        connection.row_factory = aiosqlite.Row
        return await _folder_breadcrumb(connection, folder_id)


async def folder_rename(folder_id: str, owner_sub: str, name: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "UPDATE folders SET name=? WHERE id=? AND owner_sub=?",
            (name.strip()[:120], folder_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def folder_update(
    folder_id: str,
    owner_sub: str,
    name: str,
    color: str,
    icon: str,
    preview_mode: str = "icon",
    preview_media_id: str | None = None,
) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "UPDATE folders SET name=?, color=?, icon=?, preview_mode=?, preview_media_id=? "
            "WHERE id=? AND owner_sub=?",
            (name.strip()[:120], color, icon, preview_mode, preview_media_id, folder_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def folder_delete(folder_id: str, owner_sub: str) -> bool:
    """Re-parent direct children (subfolders + media) up to this folder's parent, then delete."""
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT parent_id FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        new_parent = row["parent_id"]
        await db.execute(
            "UPDATE folders SET parent_id=? WHERE parent_id=? AND owner_sub=?",
            (new_parent, folder_id, owner_sub),
        )
        await db.execute(
            "UPDATE media SET folder_id=? WHERE folder_id=? AND owner_sub=?",
            (new_parent, folder_id, owner_sub),
        )
        await db.execute(
            "DELETE FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
        )
        await db.commit()
        return True


async def _folder_descendant_ids(db, folder_id: str) -> set:
    descendants = set()
    stack = [folder_id]
    while stack:
        cur_id = stack.pop()
        async with db.execute("SELECT id FROM folders WHERE parent_id=?", (cur_id,)) as cur:
            rows = await cur.fetchall()
        for r in rows:
            child = r[0]
            if child not in descendants:
                descendants.add(child)
                stack.append(child)
    return descendants


async def folder_move(folder_id: str, owner_sub: str, new_parent_id: str | None) -> bool:
    if new_parent_id == folder_id:
        return False
    async with connect_db() as db:
        if new_parent_id is not None:
            async with db.execute(
                "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (new_parent_id, owner_sub)
            ) as cur:
                if not await cur.fetchone():
                    return False
            descendants = await _folder_descendant_ids(db, folder_id)
            if new_parent_id in descendants:
                return False
        cur = await db.execute(
            "UPDATE folders SET parent_id=? WHERE id=? AND owner_sub=?",
            (new_parent_id, folder_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def _folder_list_all_for_owner(connection, owner_sub: str):
    """Return the complete folder identity and appearance used by pickers and trees."""
    async with connection.execute(
        "SELECT f.id, f.name, f.parent_id, f.color, f.icon, f.preview_mode, f.preview_media_id, "
        "(SELECT COUNT(*) FROM folders child WHERE child.parent_id=f.id) AS child_count, "
        "(SELECT COUNT(*) FROM media item WHERE item.folder_id=f.id "
        "AND item.source_app='personal') AS item_count "
        "FROM folders f WHERE f.owner_sub=? ORDER BY f.name",
        (owner_sub,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def folder_list_all_for_owner(owner_sub: str):
    async with connect_db() as connection:
        connection.row_factory = aiosqlite.Row
        return await _folder_list_all_for_owner(connection, owner_sub)


async def _folder_preview_images(
    connection, owner_sub: str, limit_per_folder: int = 8
) -> dict[str, list[dict]]:
    """Return recent image thumbnails grouped by folder, bounded for UI payloads."""
    async with connection.execute(
        "SELECT id, folder_id, original_name FROM ("
        "SELECT id, folder_id, original_name, "
        "ROW_NUMBER() OVER (PARTITION BY folder_id ORDER BY uploaded_at DESC, id) AS row_number "
        "FROM media WHERE owner_sub=? AND folder_id IS NOT NULL "
        "AND source_app='personal' AND media_type='image' AND thumb_path IS NOT NULL"
        ") WHERE row_number <= ? ORDER BY folder_id, row_number",
        (owner_sub, limit_per_folder),
    ) as cur:
        rows = await cur.fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["folder_id"], []).append(
            {"id": row["id"], "name": row["original_name"], "thumb_url": f"/thumb/{row['id']}"}
        )
    return grouped


async def folder_preview_images(owner_sub: str, limit_per_folder: int = 8) -> dict[str, list[dict]]:
    async with connect_db() as connection:
        connection.row_factory = aiosqlite.Row
        return await _folder_preview_images(connection, owner_sub, limit_per_folder)


async def share_link_create(link_id: str, folder_id: str, owner_sub: str) -> bool:
    async with connect_db() as db:
        async with db.execute(
            "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute(
            "INSERT INTO share_links (id, folder_id, owner_sub) VALUES (?, ?, ?)",
            (link_id, folder_id, owner_sub),
        )
        await db.commit()
        return True


async def share_link_import(link_id: str, folder_id: str, owner_sub: str, legacy_path: str):
    """Record an owned legacy /f link without changing the address people already have."""
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
        ) as cur:
            if not await cur.fetchone():
                return None
        await db.execute(
            "INSERT OR IGNORE INTO share_links (id, folder_id, owner_sub, legacy_path) "
            "VALUES (?, ?, ?, ?)",
            (link_id, folder_id, owner_sub, legacy_path),
        )
        # Re-adding a previously removed legacy link should restore it to the
        # list instead of returning an entry that still appears revoked.
        await db.execute(
            "UPDATE share_links SET revoked_at=NULL "
            "WHERE owner_sub=? AND legacy_path=?",
            (owner_sub, legacy_path),
        )
        await db.commit()
        async with db.execute(
            "SELECT id, folder_id, owner_sub, legacy_path, created_at, revoked_at "
            "FROM share_links WHERE owner_sub=? AND legacy_path=?",
            (owner_sub, legacy_path),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def share_link_get(link_id: str):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM share_links WHERE id=? AND revoked_at IS NULL", (link_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def share_link_list(owner_sub: str):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT s.id, s.folder_id, s.legacy_path, s.created_at, s.revoked_at, "
            "f.name AS folder_name "
            "FROM share_links s JOIN folders f ON f.id=s.folder_id "
            "WHERE s.owner_sub=? ORDER BY s.created_at DESC, s.id DESC",
            (owner_sub,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def share_link_revoke(link_id: str, owner_sub: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "UPDATE share_links SET revoked_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND owner_sub=? AND revoked_at IS NULL",
            (link_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def media_share_link_create(link_id: str, media_id: str, owner_sub: str) -> bool:
    async with connect_db() as db:
        async with db.execute(
            "SELECT 1 FROM media WHERE id=? AND owner_sub=?", (media_id, owner_sub)
        ) as cur:
            if not await cur.fetchone():
                return False
        await db.execute(
            "INSERT INTO media_share_links (id, media_id, owner_sub) VALUES (?, ?, ?)",
            (link_id, media_id, owner_sub),
        )
        await db.commit()
        return True


async def media_share_link_get(link_id: str):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT s.*, m.media_type FROM media_share_links s "
            "JOIN media m ON m.id=s.media_id "
            "WHERE s.id=? AND s.revoked_at IS NULL",
            (link_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def media_share_link_list(owner_sub: str):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT s.id, s.media_id, s.created_at, s.revoked_at, "
            "m.original_name, m.media_type "
            "FROM media_share_links s JOIN media m ON m.id=s.media_id "
            "WHERE s.owner_sub=? ORDER BY s.created_at DESC, s.id DESC",
            (owner_sub,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def media_share_link_revoke(link_id: str, owner_sub: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "UPDATE media_share_links SET revoked_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND owner_sub=? AND revoked_at IS NULL",
            (link_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def _owner_storage_bytes(connection, owner_sub: str) -> int:
    async with connection.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM media WHERE owner_sub=?", (owner_sub,)
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def owner_storage_bytes(owner_sub: str) -> int:
    async with connect_db() as connection:
        return await _owner_storage_bytes(connection, owner_sub)


async def owner_library_snapshot(owner_sub: str, folder_id: str | None) -> dict:
    """Load one owner-library page through a single SQLite connection."""
    async with connect_db() as connection:
        connection.row_factory = aiosqlite.Row
        return {
            "items": await _list_media_in_folder(connection, owner_sub, folder_id),
            "subfolders": await _folder_list_children(connection, owner_sub, folder_id),
            "breadcrumb": await _folder_breadcrumb(connection, folder_id),
            "all_folders": await _folder_list_all_for_owner(connection, owner_sub),
            "storage_bytes": await _owner_storage_bytes(connection, owner_sub),
            "preview_images": await _folder_preview_images(connection, owner_sub),
        }


async def list_companion_media(owner_sub: str, source_app: str, limit: int = 200):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "WITH companion AS ("
            "SELECT media.*, "
            "COUNT(*) OVER (PARTITION BY COALESCE(sha256, id)) AS duplicate_count, "
            "ROW_NUMBER() OVER (PARTITION BY COALESCE(sha256, id) "
            "ORDER BY uploaded_at DESC, id DESC) AS duplicate_rank "
            "FROM media WHERE owner_sub=? AND source_app=?"
            ") SELECT * FROM companion WHERE duplicate_rank=1 "
            "ORDER BY uploaded_at DESC LIMIT ?",
            (owner_sub, source_app, limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def list_media_missing_thumbs(media_type: str | None = None):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        if media_type:
            sql = "SELECT * FROM media WHERE thumb_path IS NULL AND media_type=?"
            args: tuple = (media_type,)
        else:
            sql = "SELECT * FROM media WHERE thumb_path IS NULL"
            args = ()
        async with db.execute(sql, args) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def update_thumb_path(media_id: str, thumb_path: str | None):
    async with connect_db() as db:
        await db.execute("UPDATE media SET thumb_path=? WHERE id=?", (thumb_path, media_id))
        await db.commit()


# ---------- trusted mirror cluster ----------

async def mirror_enqueue(event_id: str, origin_node: str, payload: str, file_path: str, digest: str, peers: list[str]):
    async with connect_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO mirror_events (id, origin_node, payload, file_path, digest, applied_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (event_id, origin_node, payload, file_path, digest),
        )
        await db.executemany(
            "INSERT OR IGNORE INTO mirror_deliveries (event_id, peer_node) VALUES (?, ?)",
            [(event_id, peer) for peer in peers],
        )
        await db.commit()


async def mirror_pending(limit: int = 20):
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT d.*, e.origin_node, e.payload, e.file_path, e.digest "
            "FROM mirror_deliveries d JOIN mirror_events e ON e.id=d.event_id "
            "WHERE d.delivered_at IS NULL AND d.next_attempt_at <= CURRENT_TIMESTAMP "
            "ORDER BY d.next_attempt_at LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def mirror_pending_count() -> int:
    async with connect_db() as db, db.execute(
        "SELECT COUNT(*) FROM mirror_deliveries WHERE delivered_at IS NULL"
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def mirror_mark_delivery(event_id: str, peer_node: str, error: str | None = None):
    async with connect_db() as db:
        if error is None:
            await db.execute(
                "UPDATE mirror_deliveries SET delivered_at=CURRENT_TIMESTAMP, last_error=NULL "
                "WHERE event_id=? AND peer_node=?",
                (event_id, peer_node),
            )
        else:
            await db.execute(
                "UPDATE mirror_deliveries SET attempts=attempts+1, "
                "next_attempt_at=datetime('now', '+' || MIN(300, (1 << MIN(attempts+1, 8))) || ' seconds'), "
                "last_error=? WHERE event_id=? AND peer_node=?",
                (error[:1000], event_id, peer_node),
            )
        await db.commit()


async def mirror_event_seen(event_id: str) -> bool:
    async with connect_db() as db, db.execute(
        "SELECT 1 FROM mirror_events WHERE id=? AND applied_at IS NOT NULL", (event_id,)
    ) as cur:
        return await cur.fetchone() is not None


async def mirror_record_received(event_id: str, origin_node: str, payload: str, digest: str):
    async with connect_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO mirror_events "
            "(id, origin_node, payload, file_path, digest, applied_at, created_at) "
            "VALUES (?, ?, ?, NULL, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (event_id, origin_node, payload, digest),
        )
        await db.commit()


async def search_media(owner_sub: str, q: str, limit: int = 200):
    pat = f"%{q}%"
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM media WHERE owner_sub=? AND source_app='personal' "
            "AND (original_name LIKE ? COLLATE NOCASE OR media_type LIKE ? COLLATE NOCASE) "
            "ORDER BY uploaded_at DESC LIMIT ?",
            (owner_sub, pat, pat, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def search_folders(owner_sub: str, q: str, limit: int = 100):
    pat = f"%{q}%"
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM folders WHERE owner_sub=? AND name LIKE ? COLLATE NOCASE "
            "ORDER BY name LIMIT ?",
            (owner_sub, pat, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def search_suggestion_sources(owner_sub: str, media_limit: int = 500):
    """Return owner-scoped names used to derive search suggestions."""
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT original_name, media_type FROM media "
            "WHERE owner_sub=? AND source_app='personal' "
            "ORDER BY uploaded_at DESC LIMIT ?",
            (owner_sub, media_limit),
        ) as cur:
            media = [dict(r) for r in await cur.fetchall()]
        async with db.execute(
            "SELECT name FROM folders WHERE owner_sub=? ORDER BY name",
            (owner_sub,),
        ) as cur:
            folders = [dict(r) for r in await cur.fetchall()]
    return {"media": media, "folders": folders}


async def folder_public_view(folder_id: str):
    """Return folder + subfolders + media (regardless of owner check — for /f/<id>)."""
    async with connect_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM folders WHERE id=?", (folder_id,)) as cur:
            folder = await cur.fetchone()
        if not folder:
            return None
        folder = dict(folder)
        async with db.execute(
            "SELECT * FROM folders WHERE parent_id=? ORDER BY name", (folder_id,)
        ) as cur:
            subfolders = [dict(r) for r in await cur.fetchall()]
        async with db.execute(
            "SELECT * FROM media WHERE folder_id=? AND source_app='personal' "
            "ORDER BY uploaded_at DESC",
            (folder_id,),
        ) as cur:
            items = [dict(r) for r in await cur.fetchall()]
        return {"folder": folder, "subfolders": subfolders, "items": items}
