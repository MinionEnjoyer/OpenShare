import aiosqlite
from pathlib import Path

DB_PATH = Path("/data/gallery.db")

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
    uploaded_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_media_owner_time ON media (owner_sub, uploaded_at DESC);

CREATE TABLE IF NOT EXISTS folders (
    id          TEXT PRIMARY KEY,
    owner_sub   TEXT NOT NULL,
    parent_id   TEXT REFERENCES folders(id) ON DELETE SET NULL,
    name        TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_folders_owner_parent ON folders (owner_sub, parent_id);
"""


async def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
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

        await db.commit()


# ---------- media ----------

async def insert_media(item: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        cols = ",".join(item.keys())
        placeholders = ",".join(["?"] * len(item))
        await db.execute(f"INSERT INTO media ({cols}) VALUES ({placeholders})", tuple(item.values()))
        await db.commit()


async def find_media_by_hash(owner_sub: str, sha256: str):
    """Return an existing media row with the same owner + content hash, for de-duplication."""
    if not sha256:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM media WHERE owner_sub=? AND sha256=? LIMIT 1", (owner_sub, sha256)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def folder_find_or_create(owner_sub: str, name: str, fid_if_new: str) -> str:
    """Find a top-level folder by name for this owner, or create it. Returns the folder id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id FROM folders WHERE owner_sub=? AND parent_id IS NULL AND name=? LIMIT 1",
            (owner_sub, name),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row["id"]
        await db.execute(
            "INSERT INTO folders (id, owner_sub, parent_id, name) VALUES (?, ?, NULL, ?)",
            (fid_if_new, owner_sub, name),
        )
        await db.commit()
        return fid_if_new


async def get_media(media_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE id=?", (media_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_media_in_folder(owner_sub: str, folder_id: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if folder_id is None:
            sql = "SELECT * FROM media WHERE owner_sub=? AND folder_id IS NULL ORDER BY uploaded_at DESC"
            args: tuple = (owner_sub,)
        else:
            sql = "SELECT * FROM media WHERE owner_sub=? AND folder_id=? ORDER BY uploaded_at DESC"
            args = (owner_sub, folder_id)
        async with db.execute(sql, args) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def delete_media(media_id: str, owner_sub: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM media WHERE id=? AND owner_sub=?", (media_id, owner_sub)
        )
        await db.commit()
        return cur.rowcount > 0


async def move_media(media_id: str, owner_sub: str, folder_id: str | None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        if folder_id is not None:
            async with db.execute(
                "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
            ) as cur:
                if not await cur.fetchone():
                    return False
        cur = await db.execute(
            "UPDATE media SET folder_id=? WHERE id=? AND owner_sub=?",
            (folder_id, media_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def bulk_move_media(ids: list[str], owner_sub: str, folder_id: str | None) -> int:
    if not ids:
        return 0
    async with aiosqlite.connect(DB_PATH) as db:
        if folder_id is not None:
            async with db.execute(
                "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (folder_id, owner_sub)
            ) as cur:
                if not await cur.fetchone():
                    return 0
        placeholders = ",".join(["?"] * len(ids))
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
    async with aiosqlite.connect(DB_PATH) as db:
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

async def folder_create(folder_id: str, owner_sub: str, name: str, parent_id: str | None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        if parent_id is not None:
            async with db.execute(
                "SELECT 1 FROM folders WHERE id=? AND owner_sub=?", (parent_id, owner_sub)
            ) as cur:
                if not await cur.fetchone():
                    return False
        await db.execute(
            "INSERT INTO folders (id, owner_sub, parent_id, name) VALUES (?, ?, ?, ?)",
            (folder_id, owner_sub, parent_id, name.strip()[:120]),
        )
        await db.commit()
        return True


async def folder_get(folder_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM folders WHERE id=?", (folder_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def folder_list_children(owner_sub: str, parent_id: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if parent_id is None:
            sql = "SELECT * FROM folders WHERE owner_sub=? AND parent_id IS NULL ORDER BY name"
            args: tuple = (owner_sub,)
        else:
            sql = "SELECT * FROM folders WHERE owner_sub=? AND parent_id=? ORDER BY name"
            args = (owner_sub, parent_id)
        async with db.execute(sql, args) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def folder_breadcrumb(folder_id: str | None):
    """Return list from root → folder. Each entry: {id, name}. Empty for root."""
    if folder_id is None:
        return []
    chain = []
    seen = set()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur_id = folder_id
        while cur_id and cur_id not in seen:
            seen.add(cur_id)
            async with db.execute(
                "SELECT id, name, parent_id FROM folders WHERE id=?", (cur_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                break
            chain.append({"id": row["id"], "name": row["name"]})
            cur_id = row["parent_id"]
    chain.reverse()
    return chain


async def folder_rename(folder_id: str, owner_sub: str, name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE folders SET name=? WHERE id=? AND owner_sub=?",
            (name.strip()[:120], folder_id, owner_sub),
        )
        await db.commit()
        return cur.rowcount > 0


async def folder_delete(folder_id: str, owner_sub: str) -> bool:
    """Re-parent direct children (subfolders + media) up to this folder's parent, then delete."""
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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


async def folder_list_all_for_owner(owner_sub: str):
    """For folder pickers — returns id, name, parent_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, parent_id FROM folders WHERE owner_sub=? ORDER BY name", (owner_sub,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def owner_storage_bytes(owner_sub: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM media WHERE owner_sub=?", (owner_sub,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def list_media_missing_thumbs(media_type: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE media SET thumb_path=? WHERE id=?", (thumb_path, media_id))
        await db.commit()


async def search_media(owner_sub: str, q: str, limit: int = 200):
    pat = f"%{q}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM media WHERE owner_sub=? AND original_name LIKE ? COLLATE NOCASE "
            "ORDER BY uploaded_at DESC LIMIT ?",
            (owner_sub, pat, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def search_folders(owner_sub: str, q: str, limit: int = 100):
    pat = f"%{q}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM folders WHERE owner_sub=? AND name LIKE ? COLLATE NOCASE "
            "ORDER BY name LIMIT ?",
            (owner_sub, pat, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def folder_public_view(folder_id: str):
    """Return folder + subfolders + media (regardless of owner check — for /f/<id>)."""
    async with aiosqlite.connect(DB_PATH) as db:
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
            "SELECT * FROM media WHERE folder_id=? ORDER BY uploaded_at DESC", (folder_id,)
        ) as cur:
            items = [dict(r) for r in await cur.fetchall()]
        return {"folder": folder, "subfolders": subfolders, "items": items}
