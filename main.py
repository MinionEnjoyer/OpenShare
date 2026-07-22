import asyncio
import hashlib
import mimetypes
import os
import secrets
import shutil
import zipfile
from pathlib import Path

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

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/srv/gallery"))
FILES_DIR = STORAGE_ROOT / "files"
THUMBS_DIR = STORAGE_ROOT / "thumbs"
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

# Max size for archive uploads (env ARCHIVE_MAX_MB, default 2048 MB / 2 GiB).
ARCHIVE_MAX_MB = int(os.environ.get("ARCHIVE_MAX_MB", "2048"))
ARCHIVE_MAX_BYTES = ARCHIVE_MAX_MB * 1024 * 1024


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


def new_id(n: int = 8) -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(n))


def humanize_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} TB"


async def _storage_for(user: dict) -> str:
    return humanize_bytes(await db.owner_storage_bytes(user["sub"]))


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=True, same_site="lax")
# Allow configured client origins (e.g. your OpenChat instance) to upload via credentialed fetch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS + NATIVE_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    await db.init()
    asyncio.create_task(_backfill_model_thumbs())


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
            w, h = await thumbs.make_model_thumb(src, thumb_path)
            if thumb_path.exists():
                await db.update_thumb_path(item["id"], str(thumb_path))
        except Exception:
            continue


def require_user(request: Request) -> dict:
    # Trusted service call (chat API uploading for a user): Bearer <SHARE_API_KEY>
    # + X-Share-User-Sub identifies the owner without a browser session.
    if SHARE_API_KEY:
        header = request.headers.get("authorization", "")
        if header == f"Bearer {SHARE_API_KEY}":
            sub = request.headers.get("x-share-user-sub", "").strip()
            if sub:
                return {"sub": sub, "username": request.headers.get("x-share-user-name", "").strip() or sub}
    u = auth.user_from_session(request.session)
    if not u:
        raise HTTPException(status_code=401, detail="not logged in")
    return u


async def _owner_folder(folder_id: str, owner_sub: str) -> dict:
    f = await db.folder_get(folder_id)
    if not f or f["owner_sub"] != owner_sub:
        raise HTTPException(404)
    return f


async def _render_owner_view(request, user, folder):
    folder_id = folder["id"] if folder else None
    items = await db.list_media_in_folder(user["sub"], folder_id)
    subfolders = await db.folder_list_children(user["sub"], folder_id)
    breadcrumb = await db.folder_breadcrumb(folder_id)
    all_folders = await db.folder_list_all_for_owner(user["sub"])
    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "user": user,
            "user_storage": await _storage_for(user),
            "folder": folder,
            "breadcrumb": breadcrumb,
            "subfolders": subfolders,
            "items": items,
            "all_folders": all_folders,
            "public_url": PUBLIC_URL,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = auth.user_from_session(request.session)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "public_url": PUBLIC_URL})
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

@app.post("/folders")
async def create_folder(
    request: Request,
    name: str = Form(...),
    parent_id: str = Form(""),
    user: dict = Depends(require_user),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, detail="name required")
    parent = parent_id or None
    if parent is not None:
        await _owner_folder(parent, user["sub"])
    fid = new_id()
    ok = await db.folder_create(fid, user["sub"], name, parent)
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
        with open(dest, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                total += len(chunk)
                out.write(chunk)
        out_paths.append(dest)
    primary_path = bundle_dir / Path(primary.filename or "").name
    return primary_path, total


def _extract_zip_bundle(zip_path: Path, mid: str) -> tuple[Path, int, str] | None:
    """If the zip contains a 3D primary + only model-aux files, extract to bundle dir.
    Returns (primary_path, total_size, primary_name) or None."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
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
                    shutil.copyfileobj(src, dst)
                total += dest.stat().st_size
            primary_name = basenames[primary_idx[0]]
            return bundle_dir / primary_name, total, primary_name
    except (zipfile.BadZipFile, KeyError, OSError):
        return None


@app.post("/upload")
async def upload(
    request: Request,
    files: list[UploadFile] = File(...),
    folder_id: str = Form(""),
    source: str = Form(""),
    user: dict = Depends(require_user),
):
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
                w, h = await thumbs.make_model_thumb(primary_path, thumb_path)
            if not thumb_path.exists():
                thumb_path = None
            _, primary_mime = classify_upload(primary.filename or "", primary.content_type or "")
            await db.insert_media({
                "id": mid, "owner_sub": user["sub"], "owner_username": user["username"],
                "media_type": "model", "original_name": primary.filename or "model",
                "storage_path": str(primary_path),
                "thumb_path": str(thumb_path) if thumb_path else None,
                "mime_type": primary_mime, "size_bytes": total_size,
                "width": w, "height": h, "duration_s": None,
                "folder_id": target_folder,
            })
            saved.append({"id": mid, "media_type": "model", "bundle": True})
            return JSONResponse({"saved": saved, "rejected": rejected})
        except Exception as e:
            shutil.rmtree(FILES_DIR / mid, ignore_errors=True)
            rejected.append({"name": primary.filename or "(model)", "reason": f"bundle save failed: {e}"})
            return JSONResponse({"saved": saved, "rejected": rejected})

    # Path 2 — per-file processing (existing behavior, plus zip-bundle handling)
    for f in files:
        media_type, mime = classify_upload(f.filename or "", f.content_type or "")
        is_zip = (Path(f.filename or "").suffix.lower() == ".zip")

        if media_type is None and not is_zip:
            rejected.append({"name": f.filename or "(unnamed)", "reason": f"unsupported type ({mime or 'unknown'})"})
            continue

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
                if media_type == "archive" and size > ARCHIVE_MAX_BYTES:
                    too_big = True
                    break
                hasher.update(chunk)
                out.write(chunk)
        digest = hasher.hexdigest()
        if too_big:
            storage_path.unlink(missing_ok=True)
            shutil.rmtree(FILES_DIR / mid, ignore_errors=True)
            rejected.append({"name": f.filename or "(archive)",
                             "reason": f"archive exceeds {ARCHIVE_MAX_MB} MB limit"})
            continue

        # ZIP path: if this zip is a 3D bundle, extract and treat as 'model'.
        # Otherwise keep the .zip as a plain downloadable archive (fall through).
        if is_zip:
            bundle_info = _extract_zip_bundle(storage_path, mid)
            if bundle_info is not None:
                storage_path.unlink(missing_ok=True)  # extracted; drop the raw zip
                primary_path, size, primary_name = bundle_info
                ext = primary_path.suffix.lower()
                w = h = None
                try:
                    if ext in {".stl", ".obj", ".3mf", ".ply", ".off", ".fbx"}:
                        w, h = await thumbs.make_model_thumb(primary_path, thumb_path)
                except Exception:
                    pass
                if not thumb_path.exists():
                    thumb_path = None
                await db.insert_media({
                    "id": mid, "owner_sub": user["sub"], "owner_username": user["username"],
                    "media_type": "model", "original_name": primary_name,
                    "storage_path": str(primary_path),
                    "thumb_path": str(thumb_path) if thumb_path else None,
                    "mime_type": "application/octet-stream", "size_bytes": size,
                    "width": w, "height": h, "duration_s": None,
                    "folder_id": target_folder,
                })
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
        try:
            if media_type == "image":
                w, h = await asyncio.to_thread(thumbs.make_image_thumb, storage_path, thumb_path)
            elif media_type == "video":
                w, h, duration = await thumbs.make_video_thumb(storage_path, thumb_path)
            elif media_type == "pdf":
                w, h = await thumbs.make_pdf_thumb(storage_path, thumb_path)
            elif media_type == "model":
                if ext in {".stl", ".obj", ".3mf", ".ply", ".off", ".fbx"}:
                    w, h = await thumbs.make_model_thumb(storage_path, thumb_path)
                if not thumb_path.exists():
                    thumb_path = None
            elif media_type == "text":
                w, h = await thumbs.make_text_thumb(storage_path, thumb_path)
        except Exception:
            thumb_path.unlink(missing_ok=True)
            thumb_path = None
        # Archives (and any type that produced no thumb) get no thumbnail.
        if thumb_path is not None and not thumb_path.exists():
            thumb_path = None

        await db.insert_media({
            "id": mid, "owner_sub": user["sub"], "owner_username": user["username"],
            "media_type": media_type, "original_name": f.filename or "untitled",
            "storage_path": str(storage_path),
            "thumb_path": str(thumb_path) if thumb_path else None,
            "mime_type": mime, "size_bytes": size,
            "width": w, "height": h, "duration_s": duration,
            "folder_id": target_folder, "sha256": digest,
        })
        saved.append({"id": mid, "media_type": media_type})

    return JSONResponse({"saved": saved, "rejected": rejected})


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
    return templates.TemplateResponse(template, {
        "request": request,
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
    return templates.TemplateResponse("view_pdf.html", {
        "request": request,
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
    return templates.TemplateResponse("view_archive.html", {
        "request": request,
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
        with open(p, "r", encoding="utf-8", errors="replace") as fp:
            body = fp.read(TEXT_VIEW_LIMIT_BYTES)
        truncated = size > TEXT_VIEW_LIMIT_BYTES
    except Exception:
        body, truncated = "(unable to read file)", False
    ext = Path(item["original_name"]).suffix.lower()
    lang = _HLJS_LANG_BY_EXT.get(ext, "plaintext")
    return templates.TemplateResponse("view_text.html", {
        "request": request,
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
    return templates.TemplateResponse("view_3d.html", {
        "request": request,
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
    return templates.TemplateResponse("search.html", {
        "request": request,
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
        "public_folder.html",
        {
            "request": request,
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
    return FileResponse(p, media_type=item["mime_type"])


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
    return FileResponse(target, media_type=mt or "application/octet-stream")


@app.get("/thumb/{media_id}")
async def thumb(media_id: str):
    item = await db.get_media(media_id)
    if not item or not item["thumb_path"]:
        raise HTTPException(404)
    p = Path(item["thumb_path"])
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")
