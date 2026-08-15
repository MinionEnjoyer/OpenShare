import pytest
from pathlib import Path
from unittest.mock import AsyncMock

import auth
import main
from conftest import OWNER, OpenShareHarness


@pytest.mark.unit
@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ({}, None),
        ({"user": {}}, None),
        (
            {"user": {"sub": "user-1", "preferred_username": "preferred", "email": "p@example.test"}},
            {"sub": "user-1", "username": "preferred", "email": "p@example.test", "name": None},
        ),
        (
            {"user": {"sub": "user-2", "nickname": "nickname"}},
            {"sub": "user-2", "username": "nickname", "email": None, "name": None},
        ),
        (
            {"user": {"sub": "user-3", "email": "email@example.test", "name": "Example"}},
            {
                "sub": "user-3",
                "username": "email@example.test",
                "email": "email@example.test",
                "name": "Example",
            },
        ),
    ],
)
def test_user_from_session_normalizes_oidc_claims(session, expected):
    assert auth.user_from_session(session) == expected


@pytest.mark.integration
def test_logged_out_home_renders_login_page(harness: OpenShareHarness):
    response = harness.client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
    assert '<h1>OpenShare</h1>' in response.text
    assert 'href="/auth/login"' in response.text


@pytest.mark.integration
def test_logged_in_home_renders_gallery(monkeypatch, harness: OpenShareHarness):
    monkeypatch.setattr(main.auth, "user_from_session", lambda _session: OWNER)

    response = harness.client.get("/")

    assert response.status_code == 200
    assert 'id="folder-workspace"' in response.text
    assert 'id="folder-workspace-data"' in response.text
    assert '/static/react/assets/openshare.js' in response.text
    assert '"items"' in response.text
    assert f"OpenShare v{main.APP_VERSION}" in response.text
    assert "Sign in" not in response.text
    assert '<footer class="app-version"' in response.text


def test_health_reports_the_canonical_version(harness: OpenShareHarness):
    response = harness.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": main.APP_VERSION}
    assert (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip() == main.APP_VERSION


@pytest.mark.unit
@pytest.mark.parametrize("path", sorted(main._REVALIDATED_APP_ASSETS))
def test_stable_app_assets_revalidate_instead_of_staying_stale(path):
    response = main.Response()

    main.apply_browser_cache_policy(path, response)

    assert response.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"


@pytest.mark.unit
def test_hashed_app_chunks_are_immutable():
    response = main.Response()

    main.apply_browser_cache_policy("/static/react/assets/LibraryApp-DWrJABGU.js", response)

    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_active_folder_orbit_is_concentric_and_respects_reduced_motion():
    stylesheet = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text()

    assert ".active-folder-orbit::before" in stylesheet
    assert "background:conic-gradient(" in stylesheet
    assert "@keyframes folder-orbit-spin { to { transform: rotate(1turn); } }" in stylesheet
    assert ".active-folder-orbit::before { animation: none; }" in stylesheet
    assert "@keyframes oc-orbit-glow" in stylesheet
    assert ".oc-spinner::before { animation:oc-spin 1.15s linear infinite,oc-orbit-glow" in stylesheet
    assert ".app-version { display:flex; align-items:center; justify-content:center; width:100%" in stylesheet


@pytest.mark.integration
def test_callback_establishes_session_and_logout_clears_it(monkeypatch, harness: OpenShareHarness):
    monkeypatch.setattr(
        main.auth.oauth.authentik,
        "authorize_access_token",
        AsyncMock(return_value={"userinfo": {"sub": OWNER["sub"], "preferred_username": OWNER["username"]}}),
    )

    callback = harness.client.get("/auth/callback", follow_redirects=False)
    authenticated_home = harness.client.get("/")
    response = harness.client.get("/auth/logout", follow_redirects=False)
    logged_out_home = harness.client.get("/")

    assert callback.status_code == 302
    assert callback.headers["location"] == "/"
    assert 'id="folder-workspace"' in authenticated_home.text
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert "session=null" in response.headers.get("set-cookie", "")
    assert 'href="/auth/login"' in logged_out_home.text
