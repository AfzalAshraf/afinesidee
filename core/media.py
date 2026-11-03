"""Sidee Enhanced local media integration.

Scans a folder on this computer for video files, serves them (with HTTP
Range support for seeking) through the built-in web server, and renders a
minimal HTML5 player with basic .srt subtitle support. Nothing is uploaded
anywhere and nothing is transcoded — the browser/TV decodes what it can play.
"""
from __future__ import annotations

import html
import os
import re
from pathlib import Path

from . import storage

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".webm", ".mkv", ".mov", ".ogv"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt"}
CONTENT_TYPES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".mkv": "video/x-matroska", ".mov": "video/quicktime", ".ogv": "video/ogg",
    ".srt": "text/plain; charset=utf-8", ".vtt": "text/vtt; charset=utf-8",
}
MAX_SCAN_FILES = 4000


def set_root(raw: str) -> str:
    """Validate and remember the user's media folder."""
    value = (raw or "").strip()
    if not value:
        storage.save_config({"media_root": ""})
        return ""
    p = Path(value).expanduser()
    if not p.is_dir():
        raise ValueError("That folder does not exist on this computer.")
    p = p.resolve()
    # A convenience symlink under ~/.sidee/media; cosmetic, best-effort only.
    link = storage.media_dir()
    try:
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir():
            pass
        else:
            link.symlink_to(p, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    storage.save_config({"media_root": str(p)})
    return str(p)


def root() -> Path | None:
    value = storage.load_config().get("media_root", "")
    if not value:
        return None
    p = Path(value).expanduser()
    return p if p.is_dir() else None


def _safe_target(rel: str) -> Path | None:
    """Resolve a URL-relative path to a real file inside the media root."""
    base = root()
    if base is None or not rel:
        return None
    # Reject absolute paths, traversal and NULs before touching the filesystem.
    if rel.startswith(("/", "\\")) or "\x00" in rel or ".." in rel.replace("\\", "/").split("/"):
        return None
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    if candidate.suffix.lower() not in VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS:
        return None
    return candidate


def file_path(rel: str) -> Path | None:
    return _safe_target(rel)


def subtitle_for(video: Path) -> Path | None:
    for ext in (".srt", ".vtt"):
        candidate = video.with_suffix(ext)
        if candidate.is_file():
            return candidate
    # Also handle "Movie.en.srt" style names.
    for candidate in sorted(video.parent.glob(video.stem + ".*.srt")):
        return candidate
    return None


def srt_to_vtt(text: str) -> str:
    """Minimal SRT -> WebVTT conversion so <track> works on every browser."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    text = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    text = re.sub(r"(\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    if not text.lstrip().startswith("WEBVTT"):
        text = "WEBVTT\n\n" + text
    return text


def scan() -> list[dict]:
    """Return the video files found in the configured folder, newest first."""
    base = root()
    if base is None:
        return []
    found: list[dict] = []
    try:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                rel = p.relative_to(base).as_posix()
                stat = p.stat()
                sub = subtitle_for(p)
                found.append({
                    "title": p.stem,
                    "file": rel,
                    "size": stat.st_size,
                    "subtitle": bool(sub),
                    "subtitle_file": sub.relative_to(base).as_posix() if sub else "",
                    "ext": p.suffix.lower(),
                })
                if len(found) >= MAX_SCAN_FILES:
                    break
            if len(found) >= MAX_SCAN_FILES:
                break
    except OSError:
        return []
    return found


def player_page(videos: list[dict], key: str) -> str:
    """A dark, remote-friendly HTML5 player page (served at /player)."""
    from urllib.parse import quote
    items = []
    for i, v in enumerate(videos):
        src = "/media/raw/" + quote(v["file"], safe="/") + "?key=" + quote(key, safe="")
        sub = v.get("subtitle_file", "")
        track = ""
        if sub:
            href = "/media/sub/" + quote(sub, safe="/") + "?key=" + quote(key, safe="")
            track = (f'<track kind="subtitles" srclang="en" label="Subtitles" '
                     f'src="{html.escape(href, quote=True)}" default>')
        size = v["size"] / (1024 * 1024)
        items.append(
            f'<button class="item" data-src="{html.escape(src, quote=True)}" '
            f'data-track="{html.escape(track, quote=True)}" '
            f'data-title="{html.escape(v["title"], quote=True)}">'
            f'<span class="badge">{html.escape(v["ext"].lstrip(".").upper())}</span>'
            f'<span class="label">{html.escape(v["title"])}</span>'
            f'<span class="size">{size:.0f} MB</span></button>')
    listing = "\n".join(items) or '<p class="empty">No videos found in this folder yet.</p>'
    first = videos[0] if videos else None
    first_src = ""
    first_track = ""
    if first:
        first_src = "/media/raw/" + quote(first["file"], safe="/") + "?key=" + quote(key, safe="")
        if first.get("subtitle_file"):
            href = "/media/sub/" + quote(first["subtitle_file"], safe="/") + "?key=" + quote(key, safe="")
            first_track = (f'<track kind="subtitles" srclang="en" label="Subtitles" '
                           f'src="{html.escape(href, quote=True)}" default>')
    return _PLAYER_HTML.replace("__LISTING__", listing) \
                       .replace("__FIRST_SRC__", html.escape(first_src, quote=True)) \
                       .replace("__FIRST_TRACK__", first_track) \
                       .replace("__COUNT__", str(len(videos)))


_PLAYER_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sidee — Local Media</title>
<style>
  :root{color-scheme:dark;--accent:#ffe600;--bg:#0d0f14;--panel:#171a22;--ink:#f2f4f8;--muted:#99a0af}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
  header{display:flex;align-items:center;justify-content:space-between;gap:16px;
    padding:18px clamp(16px,4vw,40px);border-bottom:1px solid #23273400}
  h1{font-size:20px;letter-spacing:-.03em;margin:0}
  h1 span{color:var(--accent)}
  .count{color:var(--muted);font-size:13px}
  .wrap{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:24px;
    padding:24px clamp(16px,4vw,40px)}
  .stage{background:#000;border-radius:18px;overflow:hidden;aspect-ratio:16/9;
    display:flex;align-items:center;justify-content:center}
  video{width:100%;height:100%;background:#000;outline:none}
  video:focus-visible{outline:3px solid var(--accent)}
  .list{display:flex;flex-direction:column;gap:8px;max-height:70vh;overflow:auto}
  .item{display:flex;align-items:center;gap:10px;text-align:left;background:var(--panel);
    border:1px solid #262a36;color:var(--ink);border-radius:12px;padding:12px 14px;cursor:pointer;
    font-size:14px}
  .item:hover,.item:focus-visible,.item.active{border-color:var(--accent);outline:none}
  .item.active{background:#22262f}
  .badge{font-size:10px;font-weight:700;background:#2b3040;border-radius:6px;padding:3px 6px;color:var(--accent)}
  .label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .size{font-size:11px;color:var(--muted)}
  .empty{color:var(--muted);font-size:14px}
  .hint{color:var(--muted);font-size:12px;padding:0 clamp(16px,4vw,40px) 32px}
  @media(max-width:820px){.wrap{grid-template-columns:1fr}}
</style></head>
<body>
<header><h1>Sidee <span>Media</span></h1><span class="count">__COUNT__ videos · local only</span></header>
<div class="wrap">
  <div class="stage"><video id="video" controls playsinline preload="metadata"
    src="__FIRST_SRC__">__FIRST_TRACK__</video></div>
  <div class="list" id="list">__LISTING__</div>
</div>
<p class="hint">Files are streamed directly from this computer. MKV playback depends on your
TV browser's codec support; MP4 (H.264) and WebM work most broadly. Subtitles load from a
matching .srt/.vtt file in the same folder.</p>
<script>
  const video=document.getElementById('video');
  document.querySelectorAll('.item').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.item').forEach(x=>x.classList.remove('active'));
    btn.classList.add('active');
    video.replaceChildren();
    const track=btn.dataset.track;
    if(track){const t=document.createElement('template');t.innerHTML=track;video.appendChild(t.content);}
    video.src=btn.dataset.src;video.play().catch(()=>{});video.focus();
    document.title=btn.dataset.title+' — Sidee Media';
  }));
  // A "Play" link may target one specific video via #f=<relative path>.
  const wanted=decodeURIComponent((location.hash||'').replace(/^#f=/,''));
  if(wanted){
    const match=Array.from(document.querySelectorAll('.item')).find(b=>b.dataset.src.indexOf(encodeURIComponent(wanted))>=0);
    if(match) match.click();
  }
</script>
</body></html>"""
