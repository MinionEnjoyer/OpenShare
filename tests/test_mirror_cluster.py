import json
import hashlib
import time
from pathlib import Path

import pytest

import db
import mirror
from conftest import OpenShareHarness, OWNER, run


def config() -> mirror.MirrorConfig:
    return mirror.MirrorConfig(
        True,
        "west-share",
        "a" * 32,
        (mirror.Peer("east-share", "https://east-share.example.com"),),
    )


def asset_envelope(content: bytes, event_id: str = "1f376840-1c66-4f4f-ac79-ef76d433d6e8") -> dict:
    digest = hashlib.sha256(content).hexdigest()
    return {
        "id": event_id,
        "originNodeId": "east-share",
        "occurredAt": int(time.time() * 1000),
        "digest": digest,
        "asset": {
            "id": "asset1",
            "owner_sub": OWNER["sub"],
            "owner_username": OWNER["username"],
            "media_type": "text",
            "original_name": "notes.txt",
            "mime_type": "text/plain",
            "size_bytes": len(content),
            "width": None,
            "height": None,
            "duration_s": None,
            "sha256": digest,
            "waveform": None,
            "source": "chat",
            "source_app": "openchat",
        },
    }


@pytest.mark.unit
def test_mirror_configuration_requires_a_private_key_and_explicit_https_peers():
    assert mirror.load_config({}).enabled is False
    valid = mirror.load_config({
        "FEDERATION_ENABLED": "1",
        "FEDERATION_NODE_ID": "west-share",
        "FEDERATION_SHARED_SECRET": "a" * 32,
        "FEDERATION_PEERS": '[{"id":"east-share","url":"https://east.example.com/"}]',
    })
    assert valid.peers == (mirror.Peer("east-share", "https://east.example.com"),)

    with pytest.raises(RuntimeError, match="at least 32"):
        mirror.load_config({
            "FEDERATION_ENABLED": "1", "FEDERATION_NODE_ID": "west",
            "FEDERATION_SHARED_SECRET": "short", "FEDERATION_PEERS": "[]",
        })
    with pytest.raises(RuntimeError, match="HTTPS"):
        mirror.load_config({
            "FEDERATION_ENABLED": "1", "FEDERATION_NODE_ID": "west",
            "FEDERATION_SHARED_SECRET": "a" * 32,
            "FEDERATION_PEERS": '[{"id":"east","url":"http://east.local"}]',
        })


@pytest.mark.unit
def test_mirror_signature_rejects_tampering_and_stale_requests():
    cfg = config()
    body = asset_envelope(b"hello")
    now = time.time()
    timestamp = str(int(now * 1000))
    signature = mirror.sign_envelope(cfg.shared_secret, timestamp, body)

    mirror.validate_envelope(
        body, node_id="east-share", timestamp=timestamp, signature=signature, now=now, config=cfg,
    )
    with pytest.raises(PermissionError, match="signature"):
        mirror.validate_envelope(
            {**body, "digest": "0" * 64}, node_id="east-share", timestamp=timestamp,
            signature=signature, now=now, config=cfg,
        )
    with pytest.raises(PermissionError, match="stale"):
        mirror.validate_envelope(
            body, node_id="east-share", timestamp=timestamp, signature=signature,
            now=now + mirror.MAX_CLOCK_SKEW_SECONDS + 1, config=cfg,
        )


@pytest.mark.integration
def test_received_asset_is_digest_checked_persisted_and_idempotent(harness: OpenShareHarness, tmp_path: Path):
    content = b"mirrored attachment"
    body = asset_envelope(content)
    temporary = tmp_path / "incoming.part"
    temporary.write_bytes(content)

    assert run(mirror.apply_received_asset(body, temporary, harness.files_dir)) is True
    item = harness.media("asset1")
    assert item is not None
    assert Path(item["storage_path"]).read_bytes() == content
    assert item["folder_id"] is None
    assert item["source_app"] == "openchat"
    assert harness.folders() == []
    assert run(db.mirror_event_seen("1f376840-1c66-4f4f-ac79-ef76d433d6e8")) is True

    duplicate = tmp_path / "duplicate.part"
    duplicate.write_bytes(content)
    assert run(mirror.apply_received_asset(body, duplicate, harness.files_dir)) is False
    assert not duplicate.exists()


@pytest.mark.integration
def test_signed_mirror_route_bypasses_browser_origin_check_only_after_authentication(
    monkeypatch, harness: OpenShareHarness,
):
    cfg = config()
    monkeypatch.setattr(mirror, "CONFIG", cfg)
    content = b"route mirror"
    body = asset_envelope(content, "ca44f1a3-a0e0-486d-9f65-098d02335e3c")
    timestamp = str(int(time.time() * 1000))
    headers = {
        "X-OpenShare-Node": "east-share",
        "X-OpenShare-Timestamp": timestamp,
        "X-OpenShare-Signature": mirror.sign_envelope(cfg.shared_secret, timestamp, body),
    }

    accepted = harness.client.post(
        "/mirror/v1/assets", headers=headers,
        data={"metadata": mirror.canonical_json(body)}, files={"file": ("notes.txt", content, "text/plain")},
    )
    rejected = harness.client.post(
        "/mirror/v1/assets", headers={**headers, "X-OpenShare-Signature": "sha256=bad"},
        data={"metadata": mirror.canonical_json({**body, "id": "a189edfe-120c-40ea-a020-283fc74b14aa"})},
        files={"file": ("notes.txt", content, "text/plain")},
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"accepted": True, "duplicate": False}
    assert rejected.status_code == 401


@pytest.mark.integration
def test_outbox_survives_until_peer_acknowledges(monkeypatch, harness: OpenShareHarness, tmp_path: Path):
    cfg = mirror.MirrorConfig(True, "west-share", "a" * 32, (mirror.Peer("east-share", "https://east.example.com"),))
    path = tmp_path / "asset.txt"
    path.write_bytes(b"durable")
    item = {
        "id": "local-asset", "owner_sub": OWNER["sub"], "owner_username": OWNER["username"],
        "media_type": "text", "original_name": "asset.txt", "storage_path": str(path),
        "mime_type": "text/plain", "size_bytes": 7, "width": None, "height": None,
        "duration_s": None, "sha256": None, "waveform": None,
        "source_app": "openchat",
    }
    run(mirror.queue_media(item, "chat", cfg))
    assert run(db.mirror_pending_count()) == 1

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **_kwargs):
            raise OSError("peer unavailable")

    monkeypatch.setattr(mirror.httpx, "AsyncClient", lambda **_kwargs: FailingClient())
    assert run(mirror.dispatch_once(cfg)) == 0
    assert run(db.mirror_pending_count()) == 1

    async def inspect_and_release_retry():
        async with db.connect_db() as connection:
            row = await (await connection.execute(
                "SELECT attempts, last_error FROM mirror_deliveries"
            )).fetchone()
            await connection.execute("UPDATE mirror_deliveries SET next_attempt_at=CURRENT_TIMESTAMP")
            await connection.commit()
            return row

    attempts, error = run(inspect_and_release_retry())
    assert attempts == 1
    assert error == "peer unavailable"

    class Response:
        def raise_for_status(self):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            assert json.loads(kwargs["data"]["metadata"])["asset"]["id"] == "local-asset"
            assert kwargs["headers"]["X-OpenShare-Node"] == "west-share"
            return Response()

    monkeypatch.setattr(mirror.httpx, "AsyncClient", lambda **_kwargs: Client())

    assert run(mirror.dispatch_once(cfg)) == 1
    assert run(db.mirror_pending_count()) == 0


@pytest.mark.integration
def test_mirror_status_does_not_expose_the_cluster_key(monkeypatch, harness: OpenShareHarness):
    monkeypatch.setattr(mirror, "CONFIG", config())
    response = harness.client.get("/mirror/v1/status")

    assert response.json() == {"enabled": True, "nodeId": "west-share", "peers": 1, "pending": 0}
    assert "a" * 32 not in response.text
