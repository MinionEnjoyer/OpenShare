"""Authentik OIDC integration via authlib."""
import os
from authlib.integrations.starlette_client import OAuth

CLIENT_ID = os.environ["OIDC_CLIENT_ID"]
CLIENT_SECRET = os.environ["OIDC_CLIENT_SECRET"]
ISSUER = os.environ["OIDC_ISSUER"]

oauth = OAuth()
oauth.register(
    name="authentik",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url=f"{ISSUER.rstrip('/')}/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile email"},
)


def user_from_session(session) -> dict | None:
    u = session.get("user")
    if not u:
        return None
    return {
        "sub": u["sub"],
        "username": u.get("preferred_username") or u.get("nickname") or u.get("email", "user"),
        "email": u.get("email"),
        "name": u.get("name"),
    }
