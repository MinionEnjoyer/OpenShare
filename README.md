<p align="center">
  <img src="static/logo.png" alt="OpenShare" width="120" height="120" />
</p>

# OpenShare

A self-hosted file & media service: upload, store, view, and share files behind your own
OpenID Connect login. It provides in-browser viewers, automatic thumbnails, folders, and clean
share links — and doubles as the upload/attachment backend for
**[OpenChat](https://github.com/MinionEnjoyer/OpenChat)**.

## If you found this project useful, consider supporting me here: https://buymeacoffee.com/minionenjoyer Thank you!

## Features

- **In-browser viewers** for images, video, **audio** (a waveform player with scrubbing), PDFs,
  text/code, archives (browse inside `.zip`), and **3D models** (rendered previews).
- **Automatic thumbnails** for images, video frames, PDFs, and 3D models; audio uploads get a
  stored **waveform** (audio-level peaks) + duration, served at `/waveform/<id>`.
- **Content-hash de-duplication** — the same file uploaded twice is stored once.
- **Folders** with nesting, rename, move, and bulk actions.
- **Clean share links** — `/(i|v|au|d|t|m|a)/‹id›` viewer URLs plus `/raw` and `/thumb` for direct bytes.
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
| `ALLOWED_ORIGINS` | Comma-separated trusted application origins (e.g. your OpenChat URL) |
| `SHARE_API_KEY` | Shared secret scoped to OpenChat upload and waveform requests; other owner operations always require an OpenShare session |
| `STORAGE_ROOT` | In-container path for files/thumbnails (matches the compose mount) |
| `STORAGE_PATH` | Host path bind-mounted for storage — point at a big disk or NAS |
| `PORT` | Host port to expose |
| `FORWARDED_ALLOW_IPS` | Reverse-proxy IPs/CIDRs trusted for forwarded headers (default `127.0.0.1`) |
| `DATABASE_FILE` | SQLite file inside the container (default `/data/gallery.db`) |
| `UPLOAD_MAX_FILES`, `UPLOAD_MAX_MB`, `UPLOAD_TOTAL_MAX_MB` | Optional operator upload limits; unset means unlimited |
| `ARCHIVE_MAX_MB`, `ARCHIVE_EXPANDED_MAX_MB`, `ARCHIVE_MAX_ENTRIES` | Optional archive safety limits; unset means unlimited |
| `WAVEFORM_MAX_MB`, `PROCESSING_MAX_CONCURRENCY`, `PROCESSING_TIMEOUT_SECONDS` | Optional media-processing limits; unset means unlimited |

Your OIDC provider needs an application for OpenShare whose redirect URI is
`‹PUBLIC_URL›/auth/callback`.

## Using OpenShare as OpenChat's file backend

The pair is designed to run together:

1. Deploy OpenShare and note its `PUBLIC_URL` (e.g. `https://share.example.com`).
2. In OpenShare's `.env`, add your OpenChat origin to `ALLOWED_ORIGINS`
   (e.g. `https://chat.example.com`) and set `SHARE_API_KEY` to a random secret.
3. In OpenChat's `.env`, set `SHARE_BASE_URL` to OpenShare's `PUBLIC_URL` and `SHARE_API_KEY`
   to the **same** secret from step 2.

OpenChat's API uploads and requests waveform analysis on the user's behalf using that shared key
(so it works even for users who've never opened OpenShare), while browsers render public share
assets directly. Both apps share the same
OIDC provider, so a logged-in user is authorized to both. OpenChat also runs fine **without**
OpenShare — it simply hides file/image uploads.

## Storage layout

- Uploaded files + thumbnails live under `STORAGE_ROOT` (bind-mounted from `STORAGE_PATH`).
- File metadata (owners, folders, hashes) lives in a small SQLite DB on the `openshare_data` volume.

Both persist across rebuilds; neither is ever committed to git.
