from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import db
from conftest import OpenShareHarness, OTHER_OWNER, OWNER, PNG_1X1, run


pytestmark = pytest.mark.integration


def create_folder(
    harness: OpenShareHarness,
    name: str,
    parent_id: str = "",
    owner: dict[str, str] = OWNER,
    color: str = "#4f9cf9",
    icon: str = "📁",
) -> str:
    response = harness.client.post(
        "/folders",
        headers=harness.owner_headers(owner),
        data={"name": name, "parent_id": parent_id, "color": color, "icon": icon},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return next(folder["id"] for folder in harness.folders(owner) if folder["name"] == name)


def test_nested_folder_crud_and_cycle_protection(harness: OpenShareHarness):
    parent_id = create_folder(harness, "Parent")
    child_id = create_folder(harness, "Child", parent_id)

    rename = harness.client.post(
        f"/folders/{child_id}/rename",
        headers=harness.owner_headers(),
        data={"name": "Renamed"},
        follow_redirects=False,
    )
    assert rename.status_code == 303
    assert run(db.folder_get(child_id))["name"] == "Renamed"

    cycle = harness.client.post(
        f"/folders/{parent_id}/move",
        headers=harness.owner_headers(),
        data={"parent_id": child_id},
        follow_redirects=False,
    )
    assert cycle.status_code == 400
    assert run(db.folder_get(parent_id))["parent_id"] is None


def test_create_folder_failure_returns_a_useful_error(monkeypatch, harness: OpenShareHarness):
    monkeypatch.setattr(db, "folder_create", AsyncMock(return_value=False))

    response = harness.client.post(
        "/folders",
        headers=harness.owner_headers(),
        data={"name": "Will Fail", "parent_id": ""},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "could not create folder"}


def test_folder_appearance_is_validated_and_persisted(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Photography", color="#12AbEf", icon="📷")
    folder = run(db.folder_get(folder_id))

    assert folder["color"] == "#12abef"
    assert folder["icon"] == "📷"
    listed = next(folder for folder in harness.folders() if folder["id"] == folder_id)
    assert listed["color"] == "#12abef"
    assert listed["icon"] == "📷"

    invalid = harness.client.post(
        "/folders",
        headers=harness.owner_headers(),
        data={"name": "Bad", "parent_id": "", "color": "url(javascript:bad)", "icon": "<script>"},
    )
    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "invalid folder color"}

    full_picker_icon = harness.client.post(
        "/folders",
        headers=harness.owner_headers(),
        data={"name": "Team", "parent_id": "", "color": "#123456", "icon": "👩🏽‍💻"},
        follow_redirects=False,
    )
    assert full_picker_icon.status_code == 303
    assert next(folder for folder in harness.folders() if folder["name"] == "Team")["icon"] == "👩🏽‍💻"


def test_edit_folder_updates_name_color_and_emoji(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Draft")

    response = harness.client.post(
        f"/folders/{folder_id}/update",
        headers=harness.owner_headers(),
        data={"name": "Published", "color": "#c83cff", "icon": "🚀", "stay": "self"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/folder/{folder_id}"
    updated = run(db.folder_get(folder_id))
    assert updated["name"] == "Published"
    assert updated["color"] == "#c83cff"
    assert updated["icon"] == "🚀"
    assert updated["preview_mode"] == "icon"


def test_folder_preview_requires_an_owned_image_from_the_same_folder(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Gallery")
    other_id = create_folder(harness, "Other")
    image_id = harness.upload(("cover.png", PNG_1X1, "image/png"), folder_id=folder_id).json()["saved"][0]["id"]
    other_image_id = harness.upload(("other.png", PNG_1X1 + b"other", "image/png"), folder_id=other_id).json()["saved"][0]["id"]

    custom = harness.client.post(
        f"/folders/{folder_id}/update",
        headers=harness.owner_headers(),
        data={"name": "Gallery", "color": "#4f9cf9", "icon": "📁", "stay": "self", "preview_mode": "custom", "preview_media_id": image_id},
        follow_redirects=False,
    )
    denied = harness.client.post(
        f"/folders/{folder_id}/update",
        headers=harness.owner_headers(),
        data={"name": "Gallery", "color": "#4f9cf9", "icon": "📁", "stay": "self", "preview_mode": "custom", "preview_media_id": other_image_id},
        follow_redirects=False,
    )

    assert custom.status_code == 303
    assert denied.status_code == 400
    folder = run(db.folder_get(folder_id))
    assert folder["preview_mode"] == "custom"
    assert folder["preview_media_id"] == image_id
    assert run(db.folder_preview_images(OWNER["sub"]))[folder_id][0]["id"] == image_id


def test_recorded_share_links_can_be_listed_opened_and_revoked(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Shared")

    created = harness.client.post(
        f"/folders/{folder_id}/shares", headers=harness.owner_headers()
    )
    payload = created.json()
    listed = harness.client.get("/api/share-links", headers=harness.owner_headers())
    opened = harness.client.get(f"/s/{payload['id']}")
    revoked = harness.client.post(
        f"/shares/{payload['id']}/revoke", headers=harness.owner_headers()
    )
    missing = harness.client.get(f"/s/{payload['id']}")

    assert created.status_code == 200
    assert payload["url"].endswith(f"/s/{payload['id']}")
    assert listed.json()[0]["folderName"] == "Shared"
    assert opened.status_code == 200
    assert revoked.json() == {"revoked": True}
    assert missing.status_code == 404


def test_existing_owned_folder_link_can_be_added_to_shared_links(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Legacy Shared")
    legacy_url = f"https://share.example.test/f/{folder_id}"

    imported = harness.client.post(
        "/shares/import", headers=harness.owner_headers(), data={"url": legacy_url}
    )
    repeated = harness.client.post(
        "/shares/import", headers=harness.owner_headers(), data={"url": legacy_url}
    )
    removed = harness.client.post(
        f"/shares/{imported.json()['id']}/revoke", headers=harness.owner_headers()
    )
    restored = harness.client.post(
        "/shares/import", headers=harness.owner_headers(), data={"url": legacy_url}
    )
    listed = harness.client.get("/api/share-links", headers=harness.owner_headers())

    assert imported.status_code == 200
    assert repeated.status_code == 200
    assert removed.json() == {"revoked": True}
    assert restored.status_code == 200
    assert restored.json()["revokedAt"] is None
    assert imported.json()["url"] == legacy_url
    assert imported.json()["legacy"] is True
    assert [link["url"] for link in listed.json()] == [legacy_url]


def test_existing_share_link_import_is_same_server_and_owner_scoped(harness: OpenShareHarness):
    other_folder = create_folder(harness, "Other", owner=OTHER_OWNER)

    wrong_server = harness.client.post(
        "/shares/import", headers=harness.owner_headers(),
        data={"url": f"https://evil.example/f/{other_folder}"},
    )
    wrong_owner = harness.client.post(
        "/shares/import", headers=harness.owner_headers(),
        data={"url": f"https://share.example.test/f/{other_folder}"},
    )
    malformed = harness.client.post(
        "/shares/import", headers=harness.owner_headers(), data={"url": "https://share.example.test/raw/file"}
    )

    assert wrong_server.status_code == 400
    assert wrong_owner.status_code == 404
    assert malformed.status_code == 400


def test_edit_folder_is_owner_scoped_and_validates_return_target(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Private")
    payload = {"name": "Changed", "color": "#112233", "icon": "📁", "stay": "parent"}

    denied = harness.client.post(
        f"/folders/{folder_id}/update",
        headers=harness.owner_headers(OTHER_OWNER),
        data=payload,
        follow_redirects=False,
    )
    invalid_target = harness.client.post(
        f"/folders/{folder_id}/update",
        headers=harness.owner_headers(),
        data=payload | {"stay": "https://evil.example"},
        follow_redirects=False,
    )

    assert denied.status_code == 404
    assert invalid_target.status_code == 400
    assert run(db.folder_get(folder_id))["name"] == "Private"


def test_folder_page_renders_react_workspace_data_and_active_orbit(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Design", color="#8b7cf6", icon="🎨")
    response = harness.client.get(f"/folder/{folder_id}", headers=harness.owner_headers())

    assert response.status_code == 200
    assert 'id="folder-workspace"' in response.text
    assert 'id="folder-workspace-data"' in response.text
    assert '/static/react/assets/openshare.js' in response.text
    assert '/static/react/assets/openshare.css' in response.text
    assert '"currentFolder"' in response.text
    assert '"allFolders"' in response.text
    assert '"color": "#8b7cf6"' in response.text
    assert '"icon"' in response.text


def test_folder_access_is_owner_scoped(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Private")

    view = harness.client.get(f"/folder/{folder_id}", headers=harness.owner_headers(OTHER_OWNER))
    rename = harness.client.post(
        f"/folders/{folder_id}/rename",
        headers=harness.owner_headers(OTHER_OWNER),
        data={"name": "Stolen"},
        follow_redirects=False,
    )

    assert view.status_code == 404
    assert rename.status_code == 404
    assert run(db.folder_get(folder_id))["name"] == "Private"


def test_delete_folder_reparents_children_and_media(harness: OpenShareHarness):
    parent_id = create_folder(harness, "Parent")
    child_id = create_folder(harness, "Child", parent_id)
    upload = harness.upload(("pixel.png", PNG_1X1, "image/png"), folder_id=parent_id)
    media_id = upload.json()["saved"][0]["id"]

    response = harness.client.post(
        f"/folders/{parent_id}/delete",
        headers=harness.owner_headers(),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert run(db.folder_get(parent_id)) is None
    assert run(db.folder_get(child_id))["parent_id"] is None
    assert harness.media(media_id)["folder_id"] is None


def test_move_and_bulk_move_respect_folder_ownership(harness: OpenShareHarness):
    owner_folder = create_folder(harness, "Owner Folder")
    other_folder = create_folder(harness, "Other Folder", owner=OTHER_OWNER)
    first_id = harness.upload(("one.png", PNG_1X1, "image/png")).json()["saved"][0]["id"]
    second_bytes = PNG_1X1 + b"different"
    second_id = harness.upload(("two.png", second_bytes, "image/png")).json()["saved"][0]["id"]

    moved = harness.client.post(
        "/bulk/move",
        headers=harness.owner_headers(),
        json={"ids": [first_id, second_id], "folder_id": owner_folder},
    )
    denied = harness.client.post(
        f"/move/{first_id}",
        headers=harness.owner_headers(),
        data={"folder_id": other_folder},
        follow_redirects=False,
    )

    assert moved.json() == {"moved": 2}
    assert denied.status_code == 400
    assert harness.media(first_id)["folder_id"] == owner_folder
    assert harness.media(second_id)["folder_id"] == owner_folder


def test_bulk_delete_removes_only_owned_rows_and_files(harness: OpenShareHarness):
    owner_id = harness.upload(("owner.png", PNG_1X1, "image/png"), owner=OWNER).json()["saved"][0]["id"]
    other_id = harness.upload(("other.png", PNG_1X1, "image/png"), owner=OTHER_OWNER).json()["saved"][0]["id"]
    owner_path = harness.media(owner_id)["storage_path"]
    other_path = harness.media(other_id)["storage_path"]

    response = harness.client.post(
        "/bulk/delete",
        headers=harness.owner_headers(),
        json={"ids": [owner_id, other_id]},
    )

    assert response.json() == {"deleted": 1}
    assert harness.media(owner_id) is None
    assert harness.media(other_id) is not None
    assert not Path(owner_path).exists()
    assert Path(other_path).exists()


def test_search_and_public_folder_views_use_expected_visibility(harness: OpenShareHarness):
    folder_id = create_folder(harness, "Launch Assets")
    harness.upload(("roadmap.txt", b"launch plan", "text/plain"), folder_id=folder_id)
    harness.upload(("secret.txt", b"other", "text/plain"), owner=OTHER_OWNER)

    search = harness.client.get("/search?q=roadmap", headers=harness.owner_headers())
    public = harness.client.get(f"/f/{folder_id}")
    missing = harness.client.get("/f/not-a-folder")

    assert search.status_code == 200
    assert "roadmap.txt" in search.text
    assert "secret.txt" not in search.text
    assert public.status_code == 200
    assert "Launch Assets" in public.text
    assert "roadmap.txt" in public.text
    assert missing.status_code == 404


def test_search_suggestions_are_useful_and_owner_scoped(harness: OpenShareHarness):
    create_folder(harness, "Launch Assets")
    harness.upload(("summer-roadmap.png", PNG_1X1, "image/png"))
    harness.upload(("private-roadmap.png", PNG_1X1, "image/png"), owner=OTHER_OWNER)

    suggested = harness.client.get(
        "/api/search/suggestions?q=road", headers=harness.owner_headers()
    )
    by_type = harness.client.get("/search?q=image", headers=harness.owner_headers())

    assert suggested.status_code == 200
    assert suggested.headers["cache-control"] == "private, max-age=30"
    values = [entry["value"] for entry in suggested.json()["suggestions"]]
    assert "summer-roadmap" in values
    assert "private-roadmap" not in values
    assert "summer-roadmap.png" in by_type.text
    assert "private-roadmap.png" not in by_type.text


def test_media_share_links_are_recorded_listed_opened_and_revoked(harness: OpenShareHarness):
    media_id = harness.upload(("share-me.png", PNG_1X1, "image/png")).json()["saved"][0]["id"]

    created = harness.client.post(
        f"/media/{media_id}/shares", headers=harness.owner_headers()
    )
    payload = created.json()
    listed = harness.client.get("/api/share-links", headers=harness.owner_headers())
    opened = harness.client.get(f"/ms/{payload['id']}", follow_redirects=False)
    revoked = harness.client.post(
        f"/shares/{payload['id']}/revoke", headers=harness.owner_headers()
    )
    missing = harness.client.get(f"/ms/{payload['id']}")

    assert created.status_code == 200
    assert payload["url"].endswith(f"/ms/{payload['id']}")
    assert listed.json()[0]["resourceName"] == "share-me.png"
    assert listed.json()[0]["resourceType"] == "image"
    assert opened.status_code == 307
    assert opened.headers["location"] == f"/i/{media_id}"
    assert revoked.json() == {"revoked": True}
    assert missing.status_code == 404
