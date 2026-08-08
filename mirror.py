"""Private, configuration-key-gated asset mirroring for trusted OpenShare clusters."""

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

import db


@dataclass(frozen=True)
class Peer:
    id: str
    url: str


@dataclass(frozen=True)
class MirrorConfig:
    enabled: bool
    node_id: str
    shared_secret: str
    peers: tuple[Peer, ...]


def load_config(environ: dict[str, str] | os._Environ[str] = os.environ) -> MirrorConfig:
    enabled = environ.get("FEDERATION_ENABLED", "0") == "1"
    if not enabled:
        return MirrorConfig(False, "", "", ())
    node_id = environ.get("FEDERATION_NODE_ID", "").strip()
    secret = environ.get("FEDERATION_SHARED_SECRET", "")
    if not node_id or len(node_id) > 64 or not all(c.isalnum() or c in "._-" for c in node_id):
        raise RuntimeError("FEDERATION_NODE_ID must be 1-64 letters, numbers, dot, underscore, or dash")
    if len(secret) < 32:
        raise RuntimeError("FEDERATION_SHARED_SECRET must contain at least 32 characters")
    try:
        raw_peers = json.loads(environ.get("FEDERATION_PEERS", ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("FEDERATION_PEERS must be a JSON array") from exc
    if not isinstance(raw_peers, list) or not raw_peers:
        raise RuntimeError("FEDERATION_PEERS must contain at least one peer")
    peers = []
    ids = set()
    for raw in raw_peers:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("url"), str):
            raise RuntimeError("each federation peer needs string id and url values")
        peer_id = raw["id"].strip()
        url = raw["url"].rstrip("/")
        if not peer_id or len(peer_id) > 64 or not all(c.isalnum() or c in "._-" for c in peer_id):
            raise RuntimeError("federation peer IDs must use letters, numbers, dot, underscore, or dash")
        if peer_id == node_id or peer_id in ids:
            raise RuntimeError("federation peer IDs must be unique and cannot match this node")
        if urlsplit(url).scheme != "https" or not urlsplit(url).netloc:
            raise RuntimeError("federation peer URLs must use HTTPS")
        ids.add(peer_id)
        peers.append(Peer(peer_id, url))
    return MirrorConfig(True, node_id, secret, tuple(peers))


CONFIG = load_config()
MAX_CLOCK_SKEW_SECONDS = 300


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_envelope(secret: str, timestamp: str, envelope: dict) -> str:
    content = f"{timestamp}.{canonical_json(envelope)}".encode()
    return "sha256=" + hmac.new(secret.encode(), content, hashlib.sha256).hexdigest()


def validate_envelope(
    envelope: dict,
    *,
    node_id: str,
    timestamp: str,
    signature: str,
    now: float | None = None,
    config: MirrorConfig | None = None,
) -> None:
    config = config or CONFIG
    if not config.enabled:
        raise ValueError("federation is disabled")
    if node_id not in {peer.id for peer in config.peers} or envelope.get("originNodeId") != node_id:
        raise PermissionError("unknown federation peer")
    try:
        sent_at = int(timestamp) / 1000
    except (TypeError, ValueError) as exc:
        raise PermissionError("invalid federation timestamp") from exc
    if abs((time.time() if now is None else now) - sent_at) > MAX_CLOCK_SKEW_SECONDS:
        raise PermissionError("stale federation request")
    expected = sign_envelope(config.shared_secret, timestamp, envelope)
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("invalid federation signature")
    required = {"id", "originNodeId", "occurredAt", "digest", "asset"}
    if set(envelope) != required or not isinstance(envelope["asset"], dict):
        raise ValueError("invalid federation envelope")
    try:
        uuid.UUID(str(envelope["id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid federation event id") from exc
    asset_id = str(envelope["asset"].get("id", ""))
    if not asset_id or len(asset_id) > 64 or not asset_id.isalnum():
        raise ValueError("invalid mirrored asset id")
    digest = str(envelope["digest"])
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("invalid asset digest")


async def queue_media(item: dict, source: str = "", config: MirrorConfig | None = None) -> None:
    config = config or CONFIG
    if not config.enabled:
        return
    path = Path(item["storage_path"])
    if not path.is_file():
        return
    digest = item.get("sha256") or await asyncio.to_thread(_file_digest, path)
    asset = {
        key: item.get(key)
        for key in (
            "id", "owner_sub", "owner_username", "media_type", "original_name", "mime_type",
            "size_bytes", "width", "height", "duration_s", "sha256", "waveform", "source_app",
        )
    }
    asset["source"] = source
    envelope = {
        "id": str(uuid.uuid4()),
        "originNodeId": config.node_id,
        "occurredAt": int(time.time() * 1000),
        "digest": digest,
        "asset": asset,
    }
    await db.mirror_enqueue(
        envelope["id"], config.node_id, canonical_json(envelope), str(path), digest,
        [peer.id for peer in config.peers],
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def apply_received_asset(envelope: dict, temporary_file: Path, files_dir: Path) -> bool:
    digest = await asyncio.to_thread(_file_digest, temporary_file)
    if not hmac.compare_digest(digest, str(envelope["digest"])):
        raise ValueError("asset digest mismatch")
    if await db.mirror_event_seen(envelope["id"]):
        temporary_file.unlink(missing_ok=True)
        return False
    asset = envelope["asset"]
    existing = await db.get_media(str(asset["id"]))
    if existing:
        temporary_file.unlink(missing_ok=True)
    else:
        suffix = Path(str(asset.get("original_name") or "")).suffix.lower()
        if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
            suffix = ".bin"
        files_dir.mkdir(parents=True, exist_ok=True)
        destination = files_dir / f"{asset['id']}{suffix}"
        await asyncio.to_thread(shutil.move, temporary_file, destination)
        # Keep companion-owned assets out of the user's personal folder tree on
        # every mirror node. Older senders only include ``source=chat``;
        # current senders also provide the explicit logical collection.
        source_app = str(asset.get("source_app") or (
            "openchat" if asset.get("source") in {"chat", "openchat", "sticker", "soundboard", "avatar", "attachment"}
            else "personal"
        ))
        if source_app not in {"personal", "openchat"}:
            source_app = "personal"
        await db.insert_media({
            "id": str(asset["id"]),
            "owner_sub": str(asset["owner_sub"]),
            "owner_username": str(asset["owner_username"]),
            "media_type": str(asset["media_type"]),
            "original_name": str(asset["original_name"]),
            "storage_path": str(destination),
            "thumb_path": None,
            "mime_type": str(asset["mime_type"]),
            "size_bytes": int(asset["size_bytes"]),
            "width": asset.get("width"),
            "height": asset.get("height"),
            "duration_s": asset.get("duration_s"),
            "folder_id": None,
            "sha256": digest,
            "waveform": asset.get("waveform"),
            "source_app": source_app,
        })
    await db.mirror_record_received(
        envelope["id"], envelope["originNodeId"], canonical_json(envelope), digest,
    )
    return True


async def dispatch_once(config: MirrorConfig | None = None) -> int:
    config = config or CONFIG
    if not config.enabled:
        return 0
    peers = {peer.id: peer for peer in config.peers}
    delivered = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for row in await db.mirror_pending():
            peer = peers.get(row["peer_node"])
            path = Path(row["file_path"])
            if not peer or not path.is_file():
                await db.mirror_mark_delivery(row["event_id"], row["peer_node"], "asset file is unavailable")
                continue
            envelope = json.loads(row["payload"])
            timestamp = str(int(time.time() * 1000))
            try:
                with path.open("rb") as stream:
                    response = await client.post(
                        f"{peer.url}/mirror/v1/assets",
                        data={"metadata": canonical_json(envelope)},
                        files={"file": (path.name, stream, envelope["asset"]["mime_type"])},
                        headers={
                            "X-OpenShare-Node": config.node_id,
                            "X-OpenShare-Timestamp": timestamp,
                            "X-OpenShare-Signature": sign_envelope(config.shared_secret, timestamp, envelope),
                        },
                    )
                response.raise_for_status()
                await db.mirror_mark_delivery(row["event_id"], row["peer_node"])
                delivered += 1
            except Exception as exc:
                await db.mirror_mark_delivery(row["event_id"], row["peer_node"], str(exc))
    return delivered


async def delivery_loop(config: MirrorConfig | None = None):
    config = config or CONFIG
    while True:
        with suppress(Exception):
            await dispatch_once(config)
        await asyncio.sleep(5)
