import pytest

import db
from conftest import OpenShareHarness, OTHER_OWNER, OWNER, run


pytestmark = pytest.mark.integration


def contact_payload(**overrides):
    payload = {
        "displayName": "Ada Lovelace",
        "givenName": "Ada",
        "familyName": "Lovelace",
        "company": "Analytical Engines",
        "jobTitle": "Mathematician",
        "emails": ["ada@example.test"],
        "phones": ["+1 555 0100"],
        "addresses": ["12 Computing Lane"],
        "notes": "Prefers written correspondence",
        "birthday": "1815-12-10",
        "openChatUsername": "ada",
        "openChatFriendCode": "12345678",
        "groupIds": [],
    }
    payload.update(overrides)
    return payload


def test_contact_crud_search_and_owner_isolation(harness: OpenShareHarness):
    created = harness.client.post(
        "/api/contacts", headers=harness.owner_headers(), json=contact_payload()
    )
    contact = created.json()

    assert created.status_code == 201
    assert contact["displayName"] == "Ada Lovelace"
    assert contact["openChatFriendCode"] == "12345678"
    assert harness.client.get(
        "/api/contacts?q=analytical", headers=harness.owner_headers()
    ).json()["contacts"][0]["id"] == contact["id"]
    assert harness.client.get(
        "/api/contacts", headers=harness.owner_headers(OTHER_OWNER)
    ).json() == {"contacts": []}

    updated = harness.client.put(
        f"/api/contacts/{contact['id']}",
        headers=harness.owner_headers(),
        json=contact_payload(displayName="Ada King"),
    )
    assert updated.status_code == 200
    assert updated.json()["displayName"] == "Ada King"
    assert harness.client.put(
        f"/api/contacts/{contact['id']}",
        headers=harness.owner_headers(OTHER_OWNER),
        json=contact_payload(),
    ).status_code == 404

    deleted = harness.client.delete(
        f"/api/contacts/{contact['id']}", headers=harness.owner_headers()
    )
    assert deleted.status_code == 204
    assert run(db.contact_get(contact["id"], OWNER["sub"])) is None


def test_contact_groups_are_owner_scoped_and_filterable(harness: OpenShareHarness):
    group = harness.client.post(
        "/api/contact-groups",
        headers=harness.owner_headers(),
        json={"name": "Research", "color": "#18d5ad"},
    ).json()
    contact = harness.client.post(
        "/api/contacts",
        headers=harness.owner_headers(),
        json=contact_payload(groupIds=[group["id"]]),
    ).json()

    filtered = harness.client.get(
        f"/api/contacts?group_id={group['id']}", headers=harness.owner_headers()
    ).json()["contacts"]
    groups = harness.client.get(
        "/api/contact-groups", headers=harness.owner_headers()
    ).json()["groups"]

    assert [item["id"] for item in filtered] == [contact["id"]]
    assert groups[0]["contact_count"] == 1
    assert harness.client.delete(
        f"/api/contact-groups/{group['id']}", headers=harness.owner_headers(OTHER_OWNER)
    ).status_code == 404


def test_contact_import_export_and_page_mount(harness: OpenShareHarness):
    vcard = b"""BEGIN:VCARD\r
VERSION:4.0\r
FN:Grace Hopper\r
N:Hopper;Grace;;;\r
EMAIL:grace@example.test\r
X-OPENCHAT-FRIEND-CODE:87654321\r
END:VCARD\r
"""
    imported = harness.client.post(
        "/api/contacts/import",
        headers=harness.owner_headers(),
        files={"file": ("contacts.vcf", vcard, "text/vcard")},
    )
    exported = harness.client.get(
        "/api/contacts/export.vcf", headers=harness.owner_headers()
    )
    page = harness.client.get("/contacts", headers=harness.owner_headers())

    assert imported.status_code == 200
    assert imported.json()["imported"] == 1
    assert imported.json()["contacts"][0]["openChatFriendCode"] == "87654321"
    assert exported.status_code == 200
    assert "FN:Grace Hopper" in exported.text
    assert "X-OPENCHAT-FRIEND-CODE:87654321" in exported.text
    assert 'id="contact-manager-root"' in page.text


@pytest.mark.parametrize("friend_code", ["123", "abcdefgh", "123456789"])
def test_contact_rejects_invalid_openchat_friend_codes(
    harness: OpenShareHarness, friend_code: str
):
    response = harness.client.post(
        "/api/contacts",
        headers=harness.owner_headers(),
        json=contact_payload(openChatFriendCode=friend_code),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "OpenChat friend code must be 8 digits"
