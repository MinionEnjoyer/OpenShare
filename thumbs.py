"""Thumbnail generation. Images via Pillow; videos via ffmpeg; PDFs via pdftoppm; 3D via pyrender (OpenGL/EGL)."""
import asyncio
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageOps

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

THUMB_MAX = 480
THUMB_QUALITY = 80
WAVEFORM_BARS = 80  # number of peak buckets stored for the audio-level preview


def make_image_thumb(src: Path, dst: Path) -> tuple[int | None, int | None]:
    """Returns (width, height) of the original."""
    with Image.open(src) as im:
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        orig_w, orig_h = im.size
        im.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "JPEG", quality=THUMB_QUALITY, optimize=True)
    return orig_w, orig_h


async def make_video_thumb(src: Path, dst: Path) -> tuple[int | None, int | None, float | None]:
    """Extract a frame ~1s into the video as the thumbnail, return (w, h, duration)."""
    dst.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "default=noprint_wrappers=1:nokey=0",
        str(src),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    width = height = duration = None
    for line in out.decode(errors="ignore").splitlines():
        k, _, v = line.partition("=")
        try:
            if k == "width":
                width = int(v)
            elif k == "height":
                height = int(v)
            elif k == "duration":
                duration = float(v)
        except ValueError:
            pass

    seek = "1" if (duration is None or duration > 1.5) else "0"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-ss", seek,
        "-i", str(src),
        "-frames:v", "1",
        "-vf", f"scale='min({THUMB_MAX},iw)':-2",
        "-q:v", "4",
        str(dst),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if not dst.exists():
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(src),
            "-frames:v", "1",
            "-vf", f"scale='min({THUMB_MAX},iw)':-2",
            "-q:v", "4",
            str(dst),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    return width, height, duration


async def make_audio_waveform(src: Path) -> tuple[list[int] | None, float | None]:
    """Decode audio to mono PCM and return (peaks, duration_s). `peaks` is WAVEFORM_BARS
    integers 0..100 (audio-level preview); reused by the chat player and OpenShare previews.
    Best-effort — returns (None, duration?) if decoding fails."""
    # Duration via ffprobe.
    duration = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(src),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        try:
            duration = float(out.decode(errors="ignore").strip())
        except ValueError:
            duration = None
    except Exception:
        pass

    # Decode to mono 8 kHz signed-16-bit PCM on stdout (small + plenty for a preview).
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error",
            "-i", str(src),
            "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        raw, _ = await proc.communicate()
    except Exception:
        return None, duration
    if not raw:
        return None, duration

    def _peaks(buf: bytes) -> list[int] | None:
        import numpy as np
        samples = np.frombuffer(buf, dtype=np.int16)
        if samples.size == 0:
            return None
        buckets = np.array_split(np.abs(samples.astype(np.int32)), WAVEFORM_BARS)
        vals = np.array([b.max() if b.size else 0 for b in buckets], dtype=np.float64)
        m = vals.max()
        if m <= 0:
            return [0] * WAVEFORM_BARS
        return [int(round(v / m * 100)) for v in vals]

    peaks = await asyncio.to_thread(_peaks, raw)
    return peaks, duration


async def transcode_audio_to_mp3(src: Path, dst: Path) -> bool:
    """If `src` contains an audio stream, transcode it to MP3 at `dst` and return True.
    Lets us accept audio in containers browsers can't play natively (e.g. .wma, .aiff) by
    normalizing to MP3 on upload. Returns False (caller rejects) if there's no audio stream
    or the transcode fails."""
    # Probe for an audio stream first (skip non-audio files entirely).
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(src),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except Exception:
        return False
    if b"audio" not in out:
        return False
    # Transcode the audio stream to MP3 (drop any video / cover art with -vn).
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
            str(dst),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception:
        return False
    return dst.exists() and dst.stat().st_size > 0


def _look_at(eye, target, up):
    """Return a 4x4 camera pose (OpenGL/pyrender convention: cam looks down -Z)."""
    import numpy as np
    f = eye - target
    f /= max(np.linalg.norm(f), 1e-9)
    r = np.cross(up, f)
    r /= max(np.linalg.norm(r), 1e-9)
    u = np.cross(f, r)
    M = np.eye(4)
    M[:3, 0] = r
    M[:3, 1] = u
    M[:3, 2] = f
    M[:3, 3] = eye
    return M


def _render_model_thumb_sync(src: Path, dst: Path) -> tuple[int | None, int | None]:
    """Render a 3D mesh via pyrender (offscreen EGL OpenGL). Returns (w, h) of output."""
    import trimesh
    import numpy as np
    import pyrender

    ext = src.suffix.lower().lstrip(".")
    try:
        loaded = trimesh.load(str(src), force="mesh", file_type=ext or None)
    except Exception:
        return None, None

    if isinstance(loaded, trimesh.Scene):
        geoms = [g for g in loaded.geometry.values() if hasattr(g, "vertices")]
        if not geoms:
            return None, None
        loaded = trimesh.util.concatenate(geoms)

    if not hasattr(loaded, "vertices") or len(loaded.vertices) == 0 or len(loaded.faces) == 0:
        return None, None

    # Center on origin; pyrender uses a Y-up coordinate system, trimesh uses Z-up.
    # Rotate so Z-up meshes look natural in the rendered view.
    bounds = loaded.bounds
    center = bounds.mean(axis=0)
    loaded.apply_translation(-center)
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
    loaded.apply_transform(rot)

    bounds = loaded.bounds
    size = float(np.max(bounds[1] - bounds[0]))
    if size <= 0:
        size = 1.0

    # If the loaded mesh has its own material/textures (e.g. .obj with .mtl + texture in
    # the same directory), preserve them. Otherwise apply our default blue PBR.
    try:
        from trimesh.visual import TextureVisuals
        has_textures = isinstance(loaded.visual, TextureVisuals)
    except Exception:
        has_textures = False

    if has_textures:
        mesh = pyrender.Mesh.from_trimesh(loaded, smooth=True)
    else:
        material = pyrender.MetallicRoughnessMaterial(
            baseColorFactor=[0.31, 0.61, 0.98, 1.0],
            metallicFactor=0.0,
            roughnessFactor=0.55,
            doubleSided=True,
        )
        mesh = pyrender.Mesh.from_trimesh(loaded, material=material, smooth=True)

    scene = pyrender.Scene(
        bg_color=[0.086, 0.094, 0.114, 1.0],  # #16181d
        ambient_light=[0.35, 0.35, 0.35],
    )
    scene.add(mesh)

    cam_dist = size * 1.9
    eye = np.array([cam_dist * 0.85, cam_dist * 0.75, cam_dist])
    cam_pose = _look_at(eye, np.zeros(3), np.array([0.0, 1.0, 0.0]))

    camera = pyrender.PerspectiveCamera(yfov=np.pi / 4.5, aspectRatio=1.0)
    scene.add(camera, pose=cam_pose)

    # Key light from camera, fill from opposite-low side
    key = pyrender.DirectionalLight(color=np.ones(3), intensity=4.5)
    scene.add(key, pose=cam_pose)

    fill_eye = np.array([-cam_dist * 0.6, cam_dist * 0.3, -cam_dist * 0.6])
    fill_pose = _look_at(fill_eye, np.zeros(3), np.array([0.0, 1.0, 0.0]))
    fill = pyrender.DirectionalLight(color=np.ones(3), intensity=1.4)
    scene.add(fill, pose=fill_pose)

    # Render at 2x output res for downsample anti-aliasing
    render_size = 960
    out_size = 480
    try:
        r = pyrender.OffscreenRenderer(viewport_width=render_size, viewport_height=render_size)
    except Exception:
        return None, None
    try:
        color, _ = r.render(scene)
    finally:
        r.delete()

    dst.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(color, mode="RGB")
    img.thumbnail((out_size, out_size), Image.LANCZOS)
    img.save(dst, "JPEG", quality=88, optimize=True)
    return img.size


async def make_model_thumb(src: Path, dst: Path) -> tuple[int | None, int | None]:
    """Async wrapper around the sync renderer. FBX isn't loadable by trimesh directly,
    so we convert it to OBJ via the `assimp` CLI first, then render the OBJ."""
    if src.suffix.lower() == ".fbx":
        import tempfile
        with tempfile.TemporaryDirectory(prefix="fbx-thumb-") as tmpdir:
            obj_path = Path(tmpdir) / "converted.obj"
            proc = await asyncio.create_subprocess_exec(
                "assimp", "export", str(src), str(obj_path),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0 or not obj_path.exists():
                return None, None
            return await asyncio.to_thread(_render_model_thumb_sync, obj_path, dst)
    return await asyncio.to_thread(_render_model_thumb_sync, src, dst)


TEXT_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
)


def _load_mono_font(size: int):
    from PIL import ImageFont
    for p in TEXT_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _render_text_thumb_sync(src: Path, dst: Path) -> tuple[int | None, int | None]:
    """Render the first ~20 lines of a text file as a JPEG thumbnail."""
    from PIL import Image, ImageDraw

    max_lines = 22
    max_line_chars = 72
    try:
        with open(src, "r", encoding="utf-8", errors="replace") as fp:
            lines = []
            for _ in range(max_lines):
                line = fp.readline()
                if line == "":
                    break
                lines.append(line.rstrip("\n").expandtabs(4)[:max_line_chars])
    except Exception:
        return None, None

    W = H = 480
    bg = (22, 24, 29)        # #16181d
    text = (180, 188, 204)   # near var(--fg)
    accent = (79, 156, 249)  # var(--accent) for filename header

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    header_font = _load_mono_font(15)
    body_font = _load_mono_font(13)

    header = src.name
    draw.text((16, 12), header[:48], fill=accent, font=header_font)
    draw.line([(16, 36), (W - 16, 36)], fill=(50, 53, 60), width=1)

    y = 48
    line_h = 17
    for line in lines:
        if y > H - 16:
            break
        draw.text((16, y), line, fill=text, font=body_font)
        y += line_h

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=85, optimize=True)
    return img.size


async def make_text_thumb(src: Path, dst: Path) -> tuple[int | None, int | None]:
    return await asyncio.to_thread(_render_text_thumb_sync, src, dst)


async def make_pdf_thumb(src: Path, dst: Path) -> tuple[int | None, int | None]:
    """Render page 1 of a PDF as a JPEG thumbnail via pdftoppm. Returns (w, h)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    # -singlefile writes straight to <prefix>.jpg with no page-number suffix.
    prefix = dst.with_suffix("")
    proc = await asyncio.create_subprocess_exec(
        "pdftoppm", "-jpeg", "-singlefile",
        "-scale-to", str(THUMB_MAX),
        str(src), str(prefix),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if not dst.exists():
        return None, None
    try:
        with Image.open(dst) as im:
            return im.size
    except Exception:
        return None, None
