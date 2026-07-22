"""Backfill audio-level waveforms + duration for audio uploaded before the waveform
feature existed. Idempotent — only processes audio rows whose `waveform` is null.

Run inside the container:
    docker compose exec openshare python scripts/backfill_waveforms.py
"""
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

# Make the app modules importable regardless of where this is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import thumbs  # noqa: E402
from db import DB_PATH  # noqa: E402


async def main() -> None:
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, storage_path, waveform FROM media WHERE media_type='audio'"
    ).fetchall()
    todo = [r for r in rows if not r["waveform"]]
    print(f"audio rows: {len(rows)}, missing waveform: {len(todo)}", flush=True)

    baked = 0
    for r in todo:
        p = Path(r["storage_path"])
        if not p.exists():
            print(f"  skip (file missing): {r['id']} {r['storage_path']}", flush=True)
            continue
        peaks, duration = await thumbs.make_audio_waveform(p)
        if not peaks:
            print(f"  no peaks (decode failed): {r['id']}", flush=True)
            continue
        db.execute(
            "UPDATE media SET waveform=?, duration_s=COALESCE(duration_s, ?) WHERE id=?",
            (json.dumps(peaks), duration, r["id"]),
        )
        db.commit()
        baked += 1
        print(f"  baked: {r['id']} ({len(peaks)} peaks, dur={duration})", flush=True)

    print(f"done: baked {baked} of {len(todo)} missing", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
