# OpenShare

<p align="center">
  <img src="https://raw.githubusercontent.com/MinionEnjoyer/OpenShare/main/static/logo.png" alt="OpenShare logo" width="144" height="144" />
</p>

[OpenShare](https://github.com/MinionEnjoyer/OpenShare) is a self-hosted file and media library
with OpenID Connect authentication, responsive React viewers, folders, search, thumbnails, and
recorded share links. It also serves as the native attachment and media backend for
[OpenChat](https://github.com/MinionEnjoyer/OpenChat).

The single container includes the FastAPI service, production React client, and media-processing
integration points. Your SQLite database, uploaded files, thumbnails, and other persistent data
remain in operator-controlled volumes.

## Features

- Image, video, audio, PDF, text, archive, and 3D-model viewers
- Automatic thumbnails and stored audio waveforms
- Nested folders with colors, emoji icons, covers, tree navigation, and bulk actions
- Progressive owner-scoped search across folders and files
- Revocable folder and media share links recorded in My Shared Links
- Dedicated OpenChat companion collections for attachments, stickers, avatars, and soundboard media
- Light, dark, and system themes with responsive desktop and web-mobile layouts
- Optional authenticated asset replication across a private reliability cluster

## Recommended deployment

```bash
git clone https://github.com/MinionEnjoyer/OpenShare.git
cd OpenShare
cp .env.example .env
# Configure OIDC, the public URL, storage, and trusted origins in .env.
OPENSHARE_IMAGE=minionenjoyer/openshare \
OPENSHARE_VERSION=0.2.35 \
docker compose -f docker-compose.public.yml pull
OPENSHARE_IMAGE=minionenjoyer/openshare \
OPENSHARE_VERSION=0.2.35 \
docker compose -f docker-compose.public.yml up -d
```

OpenShare listens on port `8800` by default. Deploy it behind a TLS-terminating reverse proxy and
persist both the database and storage paths described in the configuration template.

## Image tags

- `latest`: newest CI-verified `main` build
- `0.2.35`: current stable release
- `sha-<commit>`: immutable build for a verified source commit

Images are published for `linux/amd64` and `linux/arm64`. Docker Hub receives the exact digest
first published to GHCR after the source commit passes the complete OpenShare test suite.

## OpenChat integration

Set the same random `SHARE_API_KEY` in both applications, point OpenChat's `SHARE_BASE_URL` at the
OpenShare public URL, and add the OpenChat origin to OpenShare's `ALLOWED_ORIGINS`. OpenChat can then
upload attachments, stickers, avatars, voice clips, and soundboard media without mixing those
assets into the user's personal library.

## Configuration and documentation

No production credentials or environment-specific defaults are baked into the image. Supply OIDC,
session, public URL, origin, storage, and optional integration settings through a local gitignored
`.env` file.

- [Project README](https://github.com/MinionEnjoyer/OpenShare/blob/main/README.md)
- [Configuration template](https://github.com/MinionEnjoyer/OpenShare/blob/main/.env.example)
- [Public Compose stack](https://github.com/MinionEnjoyer/OpenShare/blob/main/docker-compose.public.yml)
- [Source and issue tracker](https://github.com/MinionEnjoyer/OpenShare)

OpenShare is licensed under the MIT License.
