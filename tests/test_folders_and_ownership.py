from pathlib import Path

import pytest

import db
from conftest import OpenShareHarness, OTHER_OWNER, OWNER, PNG_1X1, run


pytestmark = pytest.mark.integration


def create_folder(
    harness: OpenShareHarness,
    name: str,
    parent_id: str = "",
    owner: dict[str, str] = OWNER,
) -> str:
    response = harness.client.post(
        "/folders",
        headers=harness.owner_headers(owner),
        data={"name": name, "parent_id": parent_id},
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
