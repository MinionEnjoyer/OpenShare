import asyncio
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import zipfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends, Body
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.base_client import OAuthError

import auth
import db
import thumbs
import mirror

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/srv/gallery"))
FILES_DIR = STORAGE_ROOT / "files"
THUMBS_DIR = STORAGE_ROOT / "thumbs"
APP_VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()
SESSION_SECRET = os.environ["SESSION_SECRET"]
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")
# Cross-origin clients allowed to upload with credentials (e.g. your OpenChat URL).
# Comma-separated list of origins; empty = same-origin only.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
# Tauri desktop webviews (fetching sound files for the soundboard, uploads, etc.).
NATIVE_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]
# Shared secret for trusted service-to-service calls (e.g. the OpenChat API uploading
# on a user's behalf). When set, a request bearing this key + an X-Share-User-Sub header
# is treated as that user. Empty = feature disabled (session auth only).
SHARE_API_KEY = os.environ.get("SHARE_API_KEY", "").strip()


def optional_positive_int(name: str) -> int | None:
    """Return a positive configured integer; unset/zero means no operator limit."""
    raw = os.environ.get(name, "").strip()
    if not raw or raw == "0":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer or unset") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer or unset")
    return value


UPLOAD_MAX_FILES = optional_positive_int("UPLOAD_MAX_FILES")
UPLOAD_MAX_BYTES = (value * 1024 * 1024 if (value := optional_positive_int("UPLOAD_MAX_MB")) else None)
UPLOAD_TOTAL_MAX_BYTES = (value * 1024 * 1024 if (value := optional_positive_int("UPLOAD_TOTAL_MAX_MB")) else None)
ARCHIVE_MAX_BYTES = (value * 1024 * 1024 if (value := optional_positive_int("ARCHIVE_MAX_MB")) else None)
ARCHIVE_EXPANDED_MAX_BYTES = (value * 1024 * 1024 if (value := optional_positive_int("ARCHIVE_EXPANDED_MAX_MB")) else None)
ARCHIVE_MAX_ENTRIES = optional_positive_int("ARCHIVE_MAX_ENTRIES")
PROCESSING_MAX_CONCURRENCY = optional_positive_int("PROCESSING_MAX_CONCURRENCY")
PROCESSING_TIMEOUT_SECONDS = optional_positive_int("PROCESSING_TIMEOUT_SECONDS")
WAVEFORM_MAX_BYTES = (value * 1024 * 1024 if (value := optional_positive_int("WAVEFORM_MAX_MB")) else None)
_processing_semaphore = asyncio.Semaphore(PROCESSING_MAX_CONCURRENCY) if PROCESSING_MAX_CONCURRENCY else None

IMAGE_MIMES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/heic", "image/heif", "image/avif",
    "image/bmp", "image/tiff", "image/x-tiff",
}
VIDEO_MIMES = {
    "video/mp4", "video/webm", "video/quicktime", "video/x-matroska",
    "video/x-msvideo", "video/avi",
    "video/x-ms-wmv", "video/x-ms-asf",
    "video/mpeg", "video/3gpp", "video/3gpp2",
    "video/ogg", "video/x-m4v", "video/mp2t", "video/x-flv",
}
PDF_MIMES = {"application/pdf", "application/x-pdf"}
AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac", "audio/x-m4a",
    "audio/ogg", "audio/opus", "audio/wav", "audio/x-wav", "audio/wave",
    "audio/webm", "audio/flac", "audio/x-flac",
}
MODEL_MIMES = {
    "model/stl", "application/sla", "application/vnd.ms-pki.stl",
    "model/obj", "application/wavefront-obj",
    "model/3mf", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
    # FBX has no registered MIME — almost always uploaded as application/octet-stream
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".avif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".m4v", ".webm", ".mov", ".mkv", ".avi", ".wmv", ".asf",
              ".mpg", ".mpeg", ".3gp", ".3g2", ".ogv", ".ts", ".flv"}
PDF_EXTS = {".pdf"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac", ".weba"}
MODEL_EXTS = {".stl", ".obj", ".fbx", ".3mf", ".step", ".stp"}
# File types that may legitimately accompany a 3D model in a bundle (materials + textures)
MODEL_AUX_EXTS = {".mtl", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".dds"}

# Text / source code files
TEXT_EXTS = {
    ".txt", ".text", ".md", ".markdown", ".rst",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".scss", ".sass",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".py", ".pyi", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx",
    ".java", ".kt", ".scala", ".go", ".rs", ".rb", ".php",
    ".sql", ".log", ".env", ".dockerfile", ".gitignore",
    ".lua", ".pl", ".r", ".swift", ".m", ".mm",
}

# Archives / packed binaries — stored and downloadable, no inline preview.
ARCHIVE_MIMES = {
    "application/zip", "application/x-zip-compressed",
    "application/x-rar-compressed", "application/vnd.rar",
    "application/x-7z-compressed",
    "application/x-tar", "application/gzip", "application/x-gzip",
    "application/x-bzip2", "application/x-xz",
}
ARCHIVE_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
    ".vpk", ".pak",
}

def classify_upload(filename: str, content_type: str) -> tuple[str | None, str]:
    """Return (media_type, normalized_mime). media_type is 'image', 'video',
    'pdf', 'model', 'text', 'archive', or None."""
    # Strip any MIME parameters (e.g. "audio/webm;codecs=opus" -> "audio/webm") so
    # codec-annotated uploads (common from MediaRecorder) still match the type sets.
    mime = (content_type or "").split(";")[0].strip().lower()
    ext = Path(filename or "").suffix.lower()
    if mime in IMAGE_MIMES:
        return "image", mime
    if mime in VIDEO_MIMES:
        return "video", mime
    if mime in PDF_MIMES:
        return "pdf", "application/pdf"
    if mime in MODEL_MIMES:
        return "model", mime
    if mime in AUDIO_MIMES:
        return "audio", mime
    # text/* family (text/plain, text/x-python, application/json, etc.)
    if mime.startswith("text/") or mime in {"application/json", "application/xml", "application/x-yaml"}:
        return "text", mime
    if mime in ARCHIVE_MIMES:
        return "archive", mime
    # Browser didn't supply a usable MIME (octet-stream or empty) — fall back to extension.
    if ext in IMAGE_EXTS:
        guessed = mimetypes.types_map.get(ext) or "application/octet-stream"
        return "image", guessed
    if ext in VIDEO_EXTS:
        guessed = mimetypes.types_map.get(ext) or "application/octet-stream"
        return "video", guessed
    if ext in PDF_EXTS:
        return "pdf", "application/pdf"
    if ext in AUDIO_EXTS:
        return "audio", mimetypes.types_map.get(ext) or "application/octet-stream"
    if ext in MODEL_EXTS:
        return "model", "application/octet-stream"
    if ext in TEXT_EXTS:
        return "text", "text/plain; charset=utf-8"
    if ext in ARCHIVE_EXTS:
        return "archive", mimetypes.types_map.get(ext) or "application/octet-stream"
    return None, mime

ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def new_id(n: int = 22) -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(n))


async def bounded_processing(awaitable):
    """Apply optional operator-configured concurrency and timeout controls."""
    async def run():
        if PROCESSING_TIMEOUT_SECONDS:
            return await asyncio.wait_for(awaitable, timeout=PROCESSING_TIMEOUT_SECONDS)
        return await awaitable

    if _processing_semaphore is None:
        return await run()
    async with _processing_semaphore:
        return await run()


def humanize_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} TB"


async def _storage_for(user: dict) -> str:
    return humanize_bytes(await db.owner_storage_bytes(user["sub"]))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    await db.init()
    backfill = asyncio.create_task(_backfill_model_thumbs())
    mirror_delivery = asyncio.create_task(mirror.delivery_loop()) if mirror.CONFIG.enabled else None
    try:
        yield
    finally:
        for task in (backfill, mirror_delivery):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=True, same_site="lax")
# Allow configured client origins (e.g. your OpenChat instance) to upload via credentialed fetch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS + NATIVE_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Share-User-Sub", "X-Share-User-Name"],
)

def normalize_origin(value: str) -> str:
    """Return a canonical, origin-only URL or an empty string when invalid."""
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https", "tauri"} or not parsed.hostname:
            return ""
        if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return ""
        host = parsed.hostname.lower()
        port = parsed.port
        if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
            host = f"{host}:{port}"
        return f"{parsed.scheme.lower()}://{host}"
    except ValueError:
        return ""


public_origin = normalize_origin(PUBLIC_URL)
trusted_origins = {
    origin
    for value in (PUBLIC_URL, *ALLOWED_ORIGINS, *NATIVE_ORIGINS)
    if (origin := normalize_origin(value))
}


@app.middleware("http")
async def security_boundary(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        authorization = request.headers.get("authorization", "")
        service_upload = request.url.path in {"/upload", "/waveform", "/api/assets"} and authorization.startswith("Bearer ")
        mirror_transfer = request.url.path == "/mirror/v1/assets" and bool(request.headers.get("x-openshare-node"))
        if not service_upload and not mirror_transfer:
            origin = normalize_origin(request.headers.get("origin", ""))
            if origin not in trusted_origins:
                return JSONResponse({"detail": "untrusted request origin"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
        "connect-src 'self' https://cdn.jsdelivr.net https://unpkg.com"
    )
    return response
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["app_version"] = APP_VERSION


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/mirror/v1/status")
async def mirror_status():
    return {
        "enabled": mirror.CONFIG.enabled,
        "nodeId": mirror.CONFIG.node_id if mirror.CONFIG.enabled else None,
        "peers": len(mirror.CONFIG.peers),
        "pending": await db.mirror_pending_count() if mirror.CONFIG.enabled else 0,
    }


@app.post("/mirror/v1/assets")
async def receive_mirrored_asset(
    request: Request,
    metadata: str = Form(...),
    file: UploadFile = File(...),
):
    try:
        envelope = json.loads(metadata)
        mirror.validate_envelope(
            envelope,
            node_id=request.headers.get("x-openshare-node", ""),
            timestamp=request.headers.get("x-openshare-timestamp", ""),
            signature=request.headers.get("x-openshare-signature", ""),
        )
    except PermissionError as exc:
        raise HTTPException(401, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    temporary = FILES_DIR / f".mirror-{new_id()}.part"
    try:
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                await asyncio.to_thread(output.write, chunk)
        applied = await mirror.apply_received_asset(envelope, temporary, FILES_DIR)
        return {"accepted": True, "duplicate": not applied}
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)


async def _backfill_model_thumbs():
    """One-shot best-effort: render thumbnails for any 3D models still missing them."""
    try:
        rows = await db.list_media_missing_thumbs("model")
    except Exception:
        return
    for item in rows:
        try:
            src = Path(item["storage_path"])
            if not src.exists():
                continue
            ext = src.suffix.lower()
            if ext not in {".stl", ".obj", ".3mf", ".ply", ".off", ".fbx"}:
                continue
            thumb_path = THUMBS_DIR / f"{item['id']}.jpg"
            await bounded_processing(thumbs.make_model_thumb(src, thumb_path))
            if thumb_path.exists():
                await db.update_thumb_path(item["id"], str(thumb_path))
        except Exception:
            continue


def require_user(request: Request) -> dict:
    """Browser owner operations require an OpenShare session."""
    u = auth.user_from_session(request.session)
    if not u:
        raise HTTPException(status_code=401, detail="not logged in")
    return u


def require_upload_user(request: Request) -> dict:
    """Upload/processing accepts a browser session or the scoped OpenChat service key."""
    header = request.headers.get("authorization", "")
    if header:
        if not SHARE_API_KEY:
            raise HTTPException(status_code=401, detail="service uploads are disabled")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        if supplied and secrets.compare_digest(supplied, SHARE_API_KEY):
            sub = request.headers.get("x-share-user-sub", "").strip()
            if sub:
                return {"sub": sub, "username": request.headers.get("x-share-user-name", "").strip() or sub}
        raise HTTPException(status_code=401, detail="invalid service credentials")
    return require_user(request)


def require_legacy_service_user(request: Request) -> dict:
    """Authenticate OpenChat's former /api/assets broker without restoring dev-login."""
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    if not SHARE_API_KEY or not supplied or not secrets.compare_digest(supplied, SHARE_API_KEY):
        raise HTTPException(status_code=401, detail="invalid service credentials")
    sub = request.headers.get("x-share-user-sub", "").strip() or "openchat-service"
    username = request.headers.get("x-share-user-name", "").strip() or sub
    return {"sub": sub, "username": username}


async def _owner_folder(folder_id: str, owner_sub: str) -> dict:
    f = await db.folder_get(folder_id)
    if not f or f["owner_sub"] != owner_sub:
        raise HTTPException(404)
    return f


async def _render_owner_view(request, user, folder):
    folder_id = folder["id"] if folder else None
    items, subfolders, breadcrumb, all_folders, storage_bytes = await asyncio.gather(
        db.list_media_in_folder(user["sub"], folder_id),
        db.folder_list_children(user["sub"], folder_id),
        db.folder_breadcrumb(folder_id),
        db.folder_list_all_for_owner(user["sub"]),
        db.owner_storage_bytes(user["sub"]),
    )
    return templates.TemplateResponse(
        request=request,
        name="gallery.html",
        context={
            "user": user,
            "user_storage": humanize_bytes(storage_bytes),
            "folder": folder,
            "breadcrumb": breadcrumb,
            "subfolders": subfolders,
            "items": items,
            "all_folders": all_folders,
            "folder_emojis": FOLDER_EMOJIS,
            "public_url": PUBLIC_URL,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = auth.user_from_session(request.session)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"public_url": PUBLIC_URL},
        )
    return await _render_owner_view(request, user, None)


@app.get("/folder/{folder_id}", response_class=HTMLResponse)
async def view_folder(folder_id: str, request: Request, user: dict = Depends(require_user)):
    folder = await _owner_folder(folder_id, user["sub"])
    return await _render_owner_view(request, user, folder)


# ---------- OIDC ----------

@app.get("/auth/login")
async def auth_login(request: Request):
    redirect_uri = f"{PUBLIC_URL}/auth/callback"
    return await auth.oauth.authentik.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await auth.oauth.authentik.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"oauth error: {e.error}")
    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await auth.oauth.authentik.userinfo(token=token)
    request.session["user"] = dict(userinfo)
    return RedirectResponse(url="/", status_code=302)


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


# ---------- Folders ----------

FOLDER_EMOJIS = (
    {"emoji": "📁", "label": "Folder"}, {"emoji": "📷", "label": "Camera"},
    {"emoji": "🎨", "label": "Art"}, {"emoji": "🎵", "label": "Music"},
    {"emoji": "🎬", "label": "Film"}, {"emoji": "📚", "label": "Books"},
    {"emoji": "💼", "label": "Work"}, {"emoji": "🧪", "label": "Science"},
    {"emoji": "⭐", "label": "Star"}, {"emoji": "🗃️", "label": "Archive"},
    {"emoji": "🏠", "label": "Home"}, {"emoji": "🌎", "label": "World"},
    {"emoji": "🚀", "label": "Rocket"}, {"emoji": "💡", "label": "Ideas"},
    {"emoji": "💬", "label": "Chat"}, {"emoji": "❤️", "label": "Heart"},
    {"emoji": "🔥", "label": "Fire"}, {"emoji": "✨", "label": "Sparkles"},
    {"emoji": "🎮", "label": "Games"}, {"emoji": "💻", "label": "Code"},
    {"emoji": "🛠️", "label": "Tools"}, {"emoji": "🔒", "label": "Private"},
    {"emoji": "🛒", "label": "Shopping"}, {"emoji": "🍽️", "label": "Food"},
    {"emoji": "🐾", "label": "Pets"}, {"emoji": "✈️", "label": "Travel"},
    {"emoji": "🏋️", "label": "Fitness"}, {"emoji": "🌿", "label": "Nature"},
    {"emoji": "📅", "label": "Calendar"}, {"emoji": "🏆", "label": "Trophy"},
    {"emoji": "🎁", "label": "Gifts"}, {"emoji": "💰", "label": "Finance"},
    {"emoji": "📝", "label": "Notes"}, {"emoji": "🔖", "label": "Bookmarks"},
    {"emoji": "🧭", "label": "Explore"}, {"emoji": "☁️", "label": "Cloud"},
    {"emoji": "🌙", "label": "Night"}, {"emoji": "☀️", "label": "Day"},
    {"emoji": "🎓", "label": "Education"}, {"emoji": "🧰", "label": "Projects"},
)
FOLDER_ICONS = frozenset(choice["emoji"] for choice in FOLDER_EMOJIS)
FOLDER_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_folder_appearance(color: str, icon: str) -> tuple[str, str]:
    color = color.strip().lower()
    if not FOLDER_COLOR_RE.fullmatch(color):
        raise HTTPException(400, detail="invalid folder color")
    if icon not in FOLDER_ICONS:
        raise HTTPException(400, detail="invalid folder icon")
    return color, icon

@app.post("/folders")
async def create_folder(
    request: Request,
    name: str = Form(...),
    parent_id: str = Form(""),
    color: str = Form("#4f9cf9"),
    icon: str = Form("📁"),
    user: dict = Depends(require_user),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, detail="name required")
    color, icon = validate_folder_appearance(color, icon)
    parent = parent_id or None
    if parent is not None:
        await _owner_folder(parent, user["sub"])
    fid = new_id()
    ok = await db.folder_create(fid, user["sub"], name, parent, color, icon)
    if not ok:
        raise HTTPException(400, detail="could not create folder")
    target = f"/folder/{parent}" if parent else "/"
    return RedirectResponse(url=target, status_code=303)


@app.post("/folders/{folder_id}/rename")
async def rename_folder(
    folder_id: str,
    name: str = Form(...),
    user: dict = Depends(require_user),
):
    await _owner_folder(folder_id, user["sub"])
    ok = await db.folder_rename(folder_id, user["sub"], name)
    if not ok:
        raise HTTPException(400)
    return RedirectResponse(url=f"/folder/{folder_id}", status_code=303)


@app.post("/folders/{folder_id}/update")
async def update_folder(
    folder_id: str,
    name: str = Form(...),
    color: str = Form(...),
    icon: str = Form(...),
    stay: str = Form("parent"),
    user: dict = Depends(require_user),
):
    folder = await _owner_folder(folder_id, user["sub"])
    name = name.strip()
    if not name:
        raise HTTPException(400, detail="name required")
    color, icon = validate_folder_appearance(color, icon)
    if stay not in {"self", "parent"}:
        raise HTTPException(400, detail="invalid return target")
    ok = await db.folder_update(folder_id, user["sub"], name, color, icon)
    if not ok:
        raise HTTPException(400, detail="could not update folder")
    parent = folder["parent_id"]
    target = f"/folder/{folder_id}" if stay == "self" else (f"/folder/{parent}" if parent else "/")
    return RedirectResponse(url=target, status_code=303)


@app.post("/folders/{folder_id}/delete")
async def delete_folder(folder_id: str, user: dict = Depends(require_user)):
    folder = await _owner_folder(folder_id, user["sub"])
    parent = folder["parent_id"]
    await db.folder_delete(folder_id, user["sub"])
    target = f"/folder/{parent}" if parent else "/"
    return RedirectResponse(url=target, status_code=303)


@app.post("/folders/{folder_id}/move")
async def move_folder(
    folder_id: str,
    parent_id: str = Form(""),
    user: dict = Depends(require_user),
):
    await _owner_folder(folder_id, user["sub"])
    new_parent = parent_id or None
    ok = await db.folder_move(folder_id, user["sub"], new_parent)
    if not ok:
        raise HTTPException(400, detail="invalid move (would cycle, or target not owned)")
    return RedirectResponse(url=f"/folder/{folder_id}", status_code=303)


# ---------- Upload ----------

def _classify_file_list(files: list[UploadFile]) -> tuple[list[UploadFile], list[UploadFile]]:
    """Split UploadFiles into 3D primaries vs. everything else."""
    primaries, aux = [], []
    for f in files:
        mt, _ = classify_upload(f.filename or "", f.content_type or "")
        (primaries if mt == "model" else aux).append(f)
    return primaries, aux


def _looks_like_model_bundle(files: list[UploadFile]) -> tuple[UploadFile, list[UploadFile]] | None:
    """Detect (exactly 1 model file + ≥1 aux files where aux are MTL/textures only)."""
    primaries, aux = _classify_file_list(files)
    if len(primaries) != 1 or len(aux) == 0:
        return None
    if not all(Path(a.filename or "").suffix.lower() in MODEL_AUX_EXTS for a in aux):
        return None
    return primaries[0], aux


async def _save_bundle(mid: str, primary: UploadFile, aux: list[UploadFile]) -> tuple[Path, int]:
    """Save primary + aux into FILES_DIR/<mid>/. Returns (primary_path, total_size)."""
    bundle_dir = FILES_DIR / mid
    bundle_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    out_paths = []
    for f in [primary, *aux]:
        # Strip any path components — store by basename only
        name = Path(f.filename or "file").name
        dest = bundle_dir / name
        file_size = 0
        with open(dest, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                file_size += len(chunk)
                total += len(chunk)
                if UPLOAD_MAX_BYTES and file_size > UPLOAD_MAX_BYTES:
                    raise HTTPException(413, f"file exceeds configured {UPLOAD_MAX_BYTES // (1024 * 1024)} MB limit")
                if UPLOAD_TOTAL_MAX_BYTES and total > UPLOAD_TOTAL_MAX_BYTES:
                    raise HTTPException(413, "upload exceeds configured total size limit")
                await asyncio.to_thread(out.write, chunk)
        out_paths.append(dest)
    primary_path = bundle_dir / Path(primary.filename or "").name
    return primary_path, total


def _extract_zip_bundle(zip_path: Path, mid: str) -> tuple[Path, int, str] | None:
    """If the zip contains a 3D primary + only model-aux files, extract to bundle dir.
    Returns (primary_path, total_size, primary_name) or None."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if ARCHIVE_MAX_ENTRIES and len(members) > ARCHIVE_MAX_ENTRIES:
                raise HTTPException(413, "archive exceeds configured entry limit")
            expanded_size = sum(member.file_size for member in members)
            if ARCHIVE_EXPANDED_MAX_BYTES and expanded_size > ARCHIVE_EXPANDED_MAX_BYTES:
                raise HTTPException(413, "archive exceeds configured expanded-size limit")
            # Use basenames to flatten any internal directories
            basenames = [Path(m.filename).name for m in members]
            primary_idx = [
                i for i, n in enumerate(basenames)
                if Path(n).suffix.lower() in MODEL_EXTS and n
            ]
            if len(primary_idx) != 1:
                return None
            aux_idx = [i for i, n in enumerate(basenames) if i != primary_idx[0]]
            if not all(Path(basenames[i]).suffix.lower() in MODEL_AUX_EXTS for i in aux_idx):
                return None
            bundle_dir = FILES_DIR / mid
            bundle_dir.mkdir(parents=True, exist_ok=True)
            total = 0
            for member, name in zip(members, basenames):
                if not name:
                    continue
                dest = bundle_dir / name
                with zf.open(member) as src, open(dest, "wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        total += len(chunk)
                        if ARCHIVE_EXPANDED_MAX_BYTES and total > ARCHIVE_EXPANDED_MAX_BYTES:
                            raise HTTPException(413, "archive exceeds configured expanded-size limit")
                        dst.write(chunk)
            primary_name = basenames[primary_idx[0]]
            return bundle_dir / primary_name, total, primary_name
    except HTTPException:
        raise
    except (zipfile.BadZipFile, KeyError, OSError):
        return None


async def _persist_media(item: dict, source: str) -> None:
    await db.insert_media(item)
    await mirror.queue_media(item, source)


@app.post("/upload")
async def upload(
    request: Request,
    files: list[UploadFile] = File(...),
    folder_id: str = Form(""),
    source: str = Form(""),
    user: dict = Depends(require_upload_user),
):
    if UPLOAD_MAX_FILES and len(files) > UPLOAD_MAX_FILES:
        raise HTTPException(413, f"upload exceeds configured {UPLOAD_MAX_FILES}-file limit")
    target_folder = folder_id or None
    if target_folder is not None:
        await _owner_folder(target_folder, user["sub"])
    # Chat attachments land in a dedicated per-user "Chat" folder so they don't clutter the gallery.
    elif source == "chat":
        target_folder = await db.folder_find_or_create(user["sub"], "Chat", new_id())

    saved: list = []
    rejected: list = []

    # Path 1 — multi-file model bundle (e.g. .obj + .mtl + textures)
    bundle = _looks_like_model_bundle(files)
    if bundle:
        primary, aux = bundle
        mid = new_id()
        try:
            primary_path, total_size = await _save_bundle(mid, primary, aux)
            thumb_path = THUMBS_DIR / f"{mid}.jpg"
            ext = primary_path.suffix.lower()
            w = h = None
            if ext in {".stl", ".obj", ".3mf", ".ply", ".off", ".fbx"}:
                w, h = await bounded_processing(thumbs.make_model_thumb(primary_path, thumb_path))
            if not thumb_path.exists():
                thumb_path = None
            _, primary_mime = classify_upload(primary.filename or "", primary.content_type or "")
            item = {
                "id": mid, "owner_sub": user["sub"], "owner_username": user["username"],
                "media_type": "model", "original_name": primary.filename or "model",
                "storage_path": str(primary_path),
                "thumb_path": str(thumb_path) if thumb_path else None,
                "mime_type": primary_mime, "size_bytes": total_size,
                "width": w, "height": h, "duration_s": None,
                "folder_id": target_folder,
            }
            await _persist_media(item, source)
            saved.append({"id": mid, "media_type": "model", "bundle": True})
            return JSONResponse({"saved": saved, "rejected": rejected})
        except Exception as e:
            shutil.rmtree(FILES_DIR / mid, ignore_errors=True)
            rejected.append({"name": primary.filename or "(model)", "reason": f"bundle save failed: {e}"})
            return JSONResponse({"saved": saved, "rejected": rejected})

    # Path 2 — per-file processing (existing behavior, plus zip-bundle handling)
    request_total = 0
    for f in files:
        media_type, mime = classify_upload(f.filename or "", f.content_type or "")
        is_zip = (Path(f.filename or "").suffix.lower() == ".zip")
        # Unknown type: don't reject outright — it may be audio in a container we don't play
        # natively (e.g. .wma, .aiff). Save it, then probe/transcode to MP3 below.
        maybe_audio = media_type is None and not is_zip

        mid = new_id()
        ext = (Path(f.filename or "").suffix or mimetypes.guess_extension(mime) or "").lower()
        if not ext:
            ext = ".bin"
        storage_path = FILES_DIR / f"{mid}{ext}"
        thumb_path = THUMBS_DIR / f"{mid}.jpg"

        size = 0
        too_big = False
        hasher = hashlib.sha256()
        with open(storage_path, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                request_total += len(chunk)
                if UPLOAD_MAX_BYTES and size > UPLOAD_MAX_BYTES:
                    too_big = True
                    break
                if UPLOAD_TOTAL_MAX_BYTES and request_total > UPLOAD_TOTAL_MAX_BYTES:
                    too_big = True
                    break
                if media_type == "archive" and ARCHIVE_MAX_BYTES and size > ARCHIVE_MAX_BYTES:
                    too_big = True
                    break
                hasher.update(chunk)
                await asyncio.to_thread(out.write, chunk)
        digest = hasher.hexdigest()
        if too_big:
            storage_path.unlink(missing_ok=True)
            shutil.rmtree(FILES_DIR / mid, ignore_errors=True)
            rejected.append({"name": f.filename or "(file)",
                             "reason": "file exceeds an operator-configured upload limit"})
            continue

        # Unknown container that turned out to be audio → transcode to MP3 so it both
        # uploads and plays; otherwise it's genuinely unsupported and we reject it.
        if maybe_audio:
            mp3_path = FILES_DIR / f"{mid}.mp3"
            ok = await bounded_processing(thumbs.transcode_audio_to_mp3(storage_path, mp3_path))
            storage_path.unlink(missing_ok=True)  # drop the original container regardless
            if not ok:
                mp3_path.unlink(missing_ok=True)
                rejected.append({"name": f.filename or "(unnamed)", "reason": f"unsupported type ({mime or 'unknown'})"})
                continue
            storage_path = mp3_path
            ext, mime, media_type = ".mp3", "audio/mpeg", "audio"
            size = storage_path.stat().st_size
            # keep `digest` = the original file's hash so re-uploads still de-duplicate

        # ZIP path: if this zip is a 3D bundle, extract and treat as 'model'.
        # Otherwise keep the .zip as a plain downloadable archive (fall through).
        if is_zip:
            bundle_info = await asyncio.to_thread(_extract_zip_bundle, storage_path, mid)
            if bundle_info is not None:
                storage_path.unlink(missing_ok=True)  # extracted; drop the raw zip
                primary_path, size, primary_name = bundle_info
                ext = primary_path.suffix.lower()
                w = h = None
                try:
                    if ext in {".stl", ".obj", ".3mf", ".ply", ".off", ".fbx"}:
                        w, h = await bounded_processing(thumbs.make_model_thumb(primary_path, thumb_path))
                except Exception:
                    pass
                if not thumb_path.exists():
                    thumb_path = None
                item = {
                    "id": mid, "owner_sub": user["sub"], "owner_username": user["username"],
                    "media_type": "model", "original_name": primary_name,
                    "storage_path": str(primary_path),
                    "thumb_path": str(thumb_path) if thumb_path else None,
                    "mime_type": "application/octet-stream", "size_bytes": size,
                    "width": w, "height": h, "duration_s": None,
                    "folder_id": target_folder,
                }
                await _persist_media(item, source)
                saved.append({"id": mid, "media_type": "model", "bundle": True})
                continue
            # Not a 3D bundle — clean any partial extraction, keep the zip as an archive.
            shutil.rmtree(FILES_DIR / mid, ignore_errors=True)
            media_type = "archive"

        # De-duplicate: if this owner already uploaded an identical file, reuse it instead of
        # creating a second copy (fixes the same image appearing multiple times from chat/avatars).
        existing = await db.find_media_by_hash(user["sub"], digest)
        if existing:
            storage_path.unlink(missing_ok=True)
            saved.append({"id": existing["id"], "media_type": existing["media_type"]})
            continue

        # Single-file path (existing)
        w = h = duration = None
        waveform_json = None
        try:
            if media_type == "image":
                w, h = await bounded_processing(asyncio.to_thread(thumbs.make_image_thumb, storage_path, thumb_path))
            elif media_type == "video":
                w, h, duration = await bounded_processing(thumbs.make_video_thumb(storage_path, thumb_path))
            elif media_type == "pdf":
                w, h = await bounded_processing(thumbs.make_pdf_thumb(storage_path, thumb_path))
            elif media_type == "audio":
                # No thumbnail; store peaks (audio-level preview) + duration instead.
                peaks, duration = await bounded_processing(thumbs.make_audio_waveform(storage_path))
                if peaks:
                    waveform_json = json.dumps(peaks)
                thumb_path = None
            elif media_type == "model":
                if ext in {".stl", ".obj", ".3mf", ".ply", ".off", ".fbx"}:
                    w, h = await bounded_processing(thumbs.make_model_thumb(storage_path, thumb_path))
                if not thumb_path.exists():
                    thumb_path = None
            elif media_type == "text":
                w, h = await bounded_processing(thumbs.make_text_thumb(storage_path, thumb_path))
        except Exception:
            thumb_path.unlink(missing_ok=True)
            thumb_path = None
        # Archives (and any type that produced no thumb) get no thumbnail.
        if thumb_path is not None and not thumb_path.exists():
            thumb_path = None

        item = {
            "id": mid, "owner_sub": user["sub"], "owner_username": user["username"],
            "media_type": media_type, "original_name": f.filename or "untitled",
            "storage_path": str(storage_path),
            "thumb_path": str(thumb_path) if thumb_path else None,
            "mime_type": mime, "size_bytes": size,
            "width": w, "height": h, "duration_s": duration,
            "folder_id": target_folder, "sha256": digest, "waveform": waveform_json,
        }
        await _persist_media(item, source)
        saved.append({"id": mid, "media_type": media_type})

    return JSONResponse({"saved": saved, "rejected": rejected})


@app.post("/api/assets")
async def legacy_service_upload(
    request: Request,
    file: list[UploadFile] = File(...),
    source: str = Form("chat"),
    user: dict = Depends(require_legacy_service_user),
):
    """Compatibility lane for released OpenChat APIs that predate the scoped /upload path."""
    if len(file) != 1:
        raise HTTPException(400, detail="legacy service uploads accept exactly one file")
    response = await upload(request, files=file, folder_id="", source=source, user=user)
    payload = json.loads(response.body)
    if not payload.get("saved"):
        reason = (payload.get("rejected") or [{}])[0].get("reason", "upload rejected")
        raise HTTPException(422, detail=reason)
    item = await db.get_media(payload["saved"][0]["id"])
    if not item:
        raise HTTPException(500, detail="uploaded asset metadata is unavailable")
    return {
        "id": item["id"],
        "filename": item["original_name"],
        "mimeType": item["mime_type"],
        "size": item["size_bytes"],
        "mediaType": item["media_type"],
        "width": item["width"],
        "height": item["height"],
        "durationMs": round(item["duration_s"] * 1000) if item["duration_s"] is not None else None,
        "sha256": item.get("sha256") or "",
    }


# ---------- Owner: delete + move media ----------

def _remove_storage_for(item: dict) -> None:
    """Remove the media's storage (file or bundle dir) + its thumb, if present."""
    bundle_dir = _bundle_dir_for(item)
    if bundle_dir is not None:
        shutil.rmtree(bundle_dir, ignore_errors=True)
    else:
        Path(item["storage_path"]).unlink(missing_ok=True)
    if item["thumb_path"]:
        Path(item["thumb_path"]).unlink(missing_ok=True)


@app.post("/delete/{media_id}")
async def delete(media_id: str, request: Request, user: dict = Depends(require_user)):
    item = await db.get_media(media_id)
    if not item:
        raise HTTPException(404)
    ok = await db.delete_media(media_id, user["sub"])
    if not ok:
        raise HTTPException(403)
    _remove_storage_for(item)
    parent_folder = item.get("folder_id")
    target = f"/folder/{parent_folder}" if parent_folder else "/"
    return RedirectResponse(url=target, status_code=303)


@app.post("/move/{media_id}")
async def move_item(
    media_id: str,
    folder_id: str = Form(""),
    user: dict = Depends(require_user),
):
    new_folder = folder_id or None
    ok = await db.move_media(media_id, user["sub"], new_folder)
    if not ok:
        raise HTTPException(400, detail="move failed (not owned or target invalid)")
    target = f"/folder/{new_folder}" if new_folder else "/"
    return RedirectResponse(url=target, status_code=303)


@app.post("/bulk/move")
async def bulk_move(
    payload: dict = Body(...),
    user: dict = Depends(require_user),
):
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise HTTPException(400, detail="ids must be a list of strings")
    folder_id = payload.get("folder_id") or None
    n = await db.bulk_move_media(ids, user["sub"], folder_id)
    return {"moved": n}


@app.post("/bulk/delete")
async def bulk_delete(
    payload: dict = Body(...),
    user: dict = Depends(require_user),
):
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise HTTPException(400, detail="ids must be a list of strings")
    deleted = await db.bulk_delete_media(ids, user["sub"])
    for row in deleted:
        _remove_storage_for(row)
    return {"deleted": len(deleted)}


# ---------- Public view pages ----------

async def _view(request: Request, media_id: str, expected: str):
    item = await db.get_media(media_id)
    if not item or item["media_type"] != expected:
        raise HTTPException(404)
    template = "view_image.html" if expected == "image" else "view_video.html"
    return templates.TemplateResponse(request=request, name=template, context={
        "item": item,
        "public_url": PUBLIC_URL,
    })


@app.get("/i/{media_id}", response_class=HTMLResponse)
async def view_image(request: Request, media_id: str):
    return await _view(request, media_id, "image")


@app.get("/v/{media_id}", response_class=HTMLResponse)
async def view_video(request: Request, media_id: str):
    return await _view(request, media_id, "video")


@app.get("/d/{media_id}", response_class=HTMLResponse)
async def view_pdf(request: Request, media_id: str):
    item = await db.get_media(media_id)
    if not item or item["media_type"] != "pdf":
        raise HTTPException(404)
    return templates.TemplateResponse(request=request, name="view_pdf.html", context={
        "item": item,
        "public_url": PUBLIC_URL,
    })


_HLJS_LANG_BY_EXT = {
    ".py": "python", ".pyi": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".md": "markdown", ".markdown": "markdown",
    ".html": "xml", ".htm": "xml", ".xml": "xml", ".css": "css", ".scss": "scss",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".fish": "bash", ".ps1": "powershell",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".java": "java", ".kt": "kotlin", ".go": "go", ".rs": "rust", ".rb": "ruby",
    ".php": "php", ".sql": "sql", ".dockerfile": "dockerfile",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini", ".env": "ini",
    ".csv": "plaintext", ".tsv": "plaintext", ".log": "plaintext", ".txt": "plaintext",
    ".swift": "swift", ".m": "objectivec", ".mm": "objectivec",
    ".lua": "lua", ".pl": "perl", ".r": "r",
}

TEXT_VIEW_LIMIT_BYTES = 256 * 1024  # 256 KB displayed inline


@app.get("/a/{media_id}", response_class=HTMLResponse)
async def view_archive(request: Request, media_id: str):
    item = await db.get_media(media_id)
    if not item or item["media_type"] != "archive":
        raise HTTPException(404)
    return templates.TemplateResponse(request=request, name="view_archive.html", context={
        "item": item,
        "public_url": PUBLIC_URL,
    })


@app.get("/au/{media_id}", response_class=HTMLResponse)
async def view_audio(request: Request, media_id: str):
    item = await db.get_media(media_id)
    if not item or item["media_type"] != "audio":
        raise HTTPException(404)
    return templates.TemplateResponse(request=request, name="view_audio.html", context={
        "item": item,
        "public_url": PUBLIC_URL,
    })


@app.get("/t/{media_id}", response_class=HTMLResponse)
async def view_text(request: Request, media_id: str):
    item = await db.get_media(media_id)
    if not item or item["media_type"] != "text":
        raise HTTPException(404)
    p = Path(item["storage_path"])
    if not p.exists():
        raise HTTPException(404)
    try:
        size = p.stat().st_size
        with p.open(encoding="utf-8", errors="replace") as fp:
            body = fp.read(TEXT_VIEW_LIMIT_BYTES)
        truncated = size > TEXT_VIEW_LIMIT_BYTES
    except Exception:
        body, truncated = "(unable to read file)", False
    ext = Path(item["original_name"]).suffix.lower()
    lang = _HLJS_LANG_BY_EXT.get(ext, "plaintext")
    return templates.TemplateResponse(request=request, name="view_text.html", context={
        "item": item,
        "body": body,
        "lang": lang,
        "truncated": truncated,
        "public_url": PUBLIC_URL,
    })


@app.get("/m/{media_id}", response_class=HTMLResponse)
async def view_model(request: Request, media_id: str):
    item = await db.get_media(media_id)
    if not item or item["media_type"] != "model":
        raise HTTPException(404)
    ext = Path(item["original_name"]).suffix.lower().lstrip(".")
    bundle_dir = _bundle_dir_for(item)
    mtl_name = None
    if bundle_dir is not None:
        for sibling in bundle_dir.iterdir():
            if sibling.suffix.lower() == ".mtl":
                mtl_name = sibling.name
                break
    return templates.TemplateResponse(request=request, name="view_3d.html", context={
        "item": item,
        "ext": ext,
        "mtl_name": mtl_name,
        "public_url": PUBLIC_URL,
    })


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", user: dict = Depends(require_user)):
    q = q.strip()
    items = folders = []
    if q:
        items = await db.search_media(user["sub"], q)
        folders = await db.search_folders(user["sub"], q)
    return templates.TemplateResponse(request=request, name="search.html", context={
        "user": user,
        "user_storage": await _storage_for(user),
        "q": q,
        "items": items,
        "folders": folders,
        "public_url": PUBLIC_URL,
    })


@app.get("/f/{folder_id}", response_class=HTMLResponse)
async def view_folder_public(folder_id: str, request: Request):
    data = await db.folder_public_view(folder_id)
    if not data:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request=request,
        name="public_folder.html",
        context={
            "folder": data["folder"],
            "subfolders": data["subfolders"],
            "items": data["items"],
            "public_url": PUBLIC_URL,
        },
    )


# ---------- Raw file + thumb ----------

def _bundle_dir_for(item: dict) -> Path | None:
    """If item is stored as a bundle, return the bundle directory; else None."""
    p = Path(item["storage_path"])
    parent = p.parent
    if parent.parent == FILES_DIR and parent.name == item["id"]:
        return parent
    return None


@app.post("/waveform")
async def waveform_analyze(
    file: UploadFile = File(...),
    _user: dict = Depends(require_upload_user),
):
    """Compute peaks + duration for an audio clip WITHOUT storing it — used by the recorder
    to bake the waveform right after recording, for the preview."""
    import tempfile
    suffix = Path(file.filename or "").suffix.lower() or ".bin"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="wf_", suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if WAVEFORM_MAX_BYTES and size > WAVEFORM_MAX_BYTES:
                    raise HTTPException(413, "clip exceeds configured waveform limit")
                tmp.write(chunk)
        peaks, duration = await bounded_processing(thumbs.make_audio_waveform(tmp_path))
        return JSONResponse({"peaks": peaks, "duration": duration})
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@app.get("/waveform/{media_id}")
async def waveform(media_id: str):
    """Audio-level peaks + duration for the waveform preview (public, like /raw).
    Returns {"peaks": [..0..100..] | null, "duration": seconds | null}."""
    item = await db.get_media(media_id)
    if not item:
        raise HTTPException(404)
    raw_wf = item.get("waveform")
    peaks = None
    if raw_wf:
        try:
            peaks = json.loads(raw_wf)
        except (ValueError, TypeError):
            peaks = None
    return JSONResponse({"peaks": peaks, "duration": item.get("duration_s")})


@app.get("/raw/{media_id}")
async def raw(media_id: str):
    item = await db.get_media(media_id)
    if not item:
        raise HTTPException(404)
    p = Path(item["storage_path"])
    if not p.exists():
        raise HTTPException(404)
    # If this is a bundle, redirect to /raw/<id>/<primary_filename> so any relative
    # references inside the file (e.g. OBJ's `mtllib foo.mtl`) resolve to siblings.
    if _bundle_dir_for(item) is not None:
        return RedirectResponse(url=f"/raw/{media_id}/{p.name}", status_code=302)
    media_type = "text/plain; charset=utf-8" if item["media_type"] == "text" else item["mime_type"]
    return FileResponse(p, media_type=media_type)


@app.get("/raw/{media_id}/{filename}")
async def raw_bundle_file(media_id: str, filename: str):
    item = await db.get_media(media_id)
    if not item:
        raise HTTPException(404)
    bundle_dir = _bundle_dir_for(item)
    if bundle_dir is None:
        raise HTTPException(404)
    # Path-traversal guard: only allow basenames inside the bundle dir.
    name = Path(filename).name
    if not name or name != filename:
        raise HTTPException(404)
    target = (bundle_dir / name).resolve()
    if not str(target).startswith(str(bundle_dir.resolve()) + os.sep) and target != bundle_dir.resolve() / name:
        raise HTTPException(404)
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    mt, _ = mimetypes.guess_type(name)
    active_types = {
        "text/html", "image/svg+xml", "application/xml", "text/xml",
        "application/javascript", "text/javascript",
    }
    media_type = "text/plain; charset=utf-8" if mt in active_types else (mt or "application/octet-stream")
    return FileResponse(target, media_type=media_type)


@app.get("/thumb/{media_id}")
async def thumb(media_id: str):
    item = await db.get_media(media_id)
    if not item or not item["thumb_path"]:
        raise HTTPException(404)
    p = Path(item["thumb_path"])
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")
