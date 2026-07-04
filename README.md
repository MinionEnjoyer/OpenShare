# OpenShare

A self-hosted file & media service: upload, store, view, and share files behind your own
OpenID Connect login. It provides in-browser viewers, automatic thumbnails, folders, and clean
share links — and doubles as the upload/attachment backend for
**[OpenChat](https://github.com/MinionEnjoyer/OpenChat)**.

If you found this project useful, consider supporting me here: https://buymeacoffee.com/minionenjoyer Thank you!

## Features

- **In-browser viewers** for images, video, PDFs, text/code, archives (browse inside `.zip`),
  and **3D models** (rendered previews).
- **Automatic thumbnails** for images, video frames, PDFs, and 3D models.
- **Content-hash de-duplication** — the same file uploaded twice is stored once.
- **Folders** with nesting, rename, move, and bulk actions.
- **Clean share links** — `/(i|v|d|t|m|a)/‹id›` viewer URLs plus `/raw` and `/thumb` for direct bytes.
- **SSO** via any OpenID Connect provider (Authentik, Keycloak, …); sessions are cookie-based.
- **Embeds anywhere** — set `ALLOWED_ORIGINS` so a trusted client (e.g. your OpenChat) can upload
  with credentials and render Share links inline.

## Tech

FastAPI (Python 3.12) · SQLite · Authlib (OIDC) · Pillow / ffmpeg / poppler / pyrender for
thumbnails · Jinja2 templates. Ships as a single Docker image.

## Quick start

```bash
cp .env.example .env      # fill in every CHANGE_ME (see below)
docker compose up -d --build
```

OpenShare listens on `PORT` (default `8800`). Put it behind a reverse proxy that terminates TLS
and set `PUBLIC_URL` to the public HTTPS URL.

### Configuration

Everything is environment-driven via `.env` (the one local, gitignored config file):

| Variable | What it is |
|---|---|
| `SESSION_SECRET` | Cookie signing key — `openssl rand -base64 48` |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_ISSUER` | Your OIDC app credentials + issuer URL |
| `PUBLIC_URL` | Public base URL (used for OIDC redirect + share links) |
| `ALLOWED_ORIGINS` | Comma-separated origins allowed to upload with credentials (e.g. your OpenChat URL) |
| `STORAGE_ROOT` | In-container path for files/thumbnails (matches the compose mount) |
| `STORAGE_PATH` | Host path bind-mounted for storage — point at a big disk or NAS |
| `PORT` | Host port to expose |
| `ARCHIVE_MAX_MB` | Largest archive OpenShare will expand for browsing |

Your OIDC provider needs an application for OpenShare whose redirect URI is
`‹PUBLIC_URL›/auth/callback`.

## Using OpenShare as OpenChat's file backend

The pair is designed to run together:

1. Deploy OpenShare and note its `PUBLIC_URL` (e.g. `https://share.example.com`).
2. In OpenShare's `.env`, add your OpenChat origin to `ALLOWED_ORIGINS`
   (e.g. `https://chat.example.com`).
3. In OpenChat's `.env`, set `SHARE_BASE_URL` to OpenShare's `PUBLIC_URL`.

Uploads from OpenChat then land in OpenShare, and OpenChat renders the resulting links as inline
embeds. Both apps share the same OIDC provider, so a logged-in user is authorized to both.
OpenChat also runs fine **without** OpenShare — it simply hides file/image uploads.

## Storage layout

- Uploaded files + thumbnails live under `STORAGE_ROOT` (bind-mounted from `STORAGE_PATH`).
- File metadata (owners, folders, hashes) lives in a small SQLite DB on the `openshare_data` volume.

Both persist across rebuilds; neither is ever committed to git.
