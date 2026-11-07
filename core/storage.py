"""Sidee Enhanced persistent configuration.

Everything the user creates lives in the Sidee profile directory
(``~/.sidee`` by default, or ``$SIDEE_STATE_DIR`` when set — the tests use
that override)::

    session.json            pairing tokens (owned by client.Session)
    custom_apps.json        user tiles: custom URLs + catalog installs
    dashboard_config.json   layout, colours, widgets and options
    icons/                  user-uploaded icon images
    media/                  optional symlink to a local media folder

There is no telemetry and no cloud storage: reads and writes are local,
atomic, and validated. Arbitrary web URLs are allowed (any domain); only
the URL *shape* is checked. The trust warning is a UI concern, not a block.
"""
from __future__ import annotations

import base64
import copy
import datetime
import hashlib
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from . import platform_support

APPS_FILE = "custom_apps.json"
CONFIG_FILE = "dashboard_config.json"
FORMAT_APPS = "sidee-enhanced/custom-apps"
FORMAT_CONFIG = "sidee-enhanced/dashboard"
FORMAT_EXPORT = "sidee-enhanced/config"
FORMAT_VERSION = 1

# Shown whenever a custom URL is added. Informational only — never a block.
TRUST_WARNING = "Make sure you trust this URL. It will be accessible from your TV."

MAX_URL = 2000
MAX_NAME = 40                 # VIDAA launcher title limit
MAX_IMAGE = 500_000           # allows a self-contained data: URI icon
MAX_ICON_BYTES = 400_000
MAX_APPS = 200
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT_CONFIG: dict = {
    "title": "My TV",
    "accent": "#ffe600",
    "accent2": "#7c5cff",
    "theme": "dark",
    "columns": 4,
    "tile_style": "rounded",
    "show_clock": True,
    "show_date": True,
    "show_weather": False,
    "weather_text": "22°C · Clear",
    "show_labels": True,
    "port": 8080,
    "autostart": False,
    "keep_alive": False,
    "media_root": "",
    "onboarded": False,
}

CONFIG_BOOLS = ("show_clock", "show_date", "show_weather", "show_labels",
                "autostart", "keep_alive", "onboarded")


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------

def profile_dir() -> Path:
    return platform_support.profile_dir()


def path(name: str) -> Path:
    return profile_dir() / name


def icons_dir() -> Path:
    d = profile_dir() / "icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def media_dir() -> Path:
    return profile_dir() / "media"


def _read_json(p: Path, default):
    try:
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return copy.deepcopy(default)


def _write_json(p: Path, obj) -> None:
    """Atomic, private (mode 600) JSON write."""
    p.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=str(p.parent), delete=False) as f:
            pending = f.name
            json.dump(obj, f, indent=2, ensure_ascii=False)
        try:
            os.chmod(pending, 0o600)
        except OSError:
            pass
        os.replace(pending, str(p))
    finally:
        if pending and os.path.isfile(pending):
            os.remove(pending)


# --------------------------------------------------------------------------
# URL / field validation — shape only, no domain restriction
# --------------------------------------------------------------------------

def normalize_url(raw: str) -> str:
    """Validate the *format* of a web-app URL but never restrict the domain.

    A missing scheme defaults to http:// (handy for LAN addresses such as
    192.168.1.50:8080). Only http/https are accepted: javascript:, file:,
    data: and other active schemes are refused because the URL is opened by
    the TV's browser. Any hostname — public or private — is allowed.
    """
    url = (raw or "").strip()
    if not url:
        raise ValueError("Enter a URL.")
    if len(url) > MAX_URL:
        raise ValueError("That URL is too long.")
    if any(ord(c) < 32 for c in url):
        raise ValueError("The URL contains invalid characters.")
    if any(c.isspace() for c in url):
        raise ValueError("The URL must not contain spaces.")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
        url = ("http:" + url) if url.startswith("//") else ("http://" + url)
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Only http:// and https:// web addresses are supported.")
    if not parts.hostname:
        raise ValueError("Enter a valid web address, including its host name.")
    if parts.username or parts.password:
        raise ValueError("Remove the username and password embedded in the URL.")
    try:
        _ = parts.port  # rejects malformed / out-of-range ports
    except ValueError:
        raise ValueError("The port in that URL is invalid.") from None
    return url


def normalize_name(raw: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(raw or "")).strip()
    if not name:
        raise ValueError("Give this app a name.")
    if len(name) > MAX_NAME:
        name = name[:MAX_NAME]
    return name


def normalize_image(raw: str) -> str:
    """Accept https/http icons, self-contained data:image URIs, and locally
    served /icons/ or /assets/ paths. Reject everything else (active URLs)."""
    image = str(raw or "").strip()
    if not image:
        return ""
    if len(image) > MAX_IMAGE:
        raise ValueError("That icon is too large.")
    low = image.lower()
    if low.startswith(("https://", "http://")):
        return image
    if low.startswith("data:image/") and ";base64," in low:
        return image
    if image.startswith("/icons/") or image.startswith("/assets/"):
        tail = image.rsplit("/", 1)[-1]
        if not SAFE_NAME.fullmatch(tail):
            raise ValueError("Invalid icon file name.")
        return image
    raise ValueError("Use an https icon URL, an uploaded icon, or a built-in icon.")


def tile_app_id(app: dict) -> str:
    """Stable, VIDAA-safe launcher id ([a-z0-9_], <= 32 chars)."""
    supplied = re.sub(r"[^a-z0-9_]", "_", str(app.get("app_id", "")).lower())
    if supplied and re.fullmatch(r"[a-z0-9_]{1,32}", supplied):
        return supplied
    seed = str(app.get("id") or app.get("url") or app.get("name") or "app")
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return "app_" + digest


# --------------------------------------------------------------------------
# apps (tiles)
# --------------------------------------------------------------------------

def _empty_apps() -> dict:
    return {"format": FORMAT_APPS, "version": FORMAT_VERSION, "apps": []}


def _dedupe(apps: list[dict]) -> list[dict]:
    """Two tiles with the same VIDAA ``app_id`` would fight over one launcher
    slot. Collapse duplicates, preferring the entry that is already installed
    (so importing an older config never loses the TV tile state)."""
    by_key: dict[str, int] = {}
    result: list[dict] = []
    for app in apps:
        key = app.get("app_id") or ("id:" + app["id"])
        if key in by_key:
            index = by_key[key]
            if app.get("installed") and not result[index].get("installed"):
                result[index] = app
            continue
        by_key[key] = len(result)
        result.append(app)
    return result


def load_apps() -> list[dict]:
    data = _read_json(path(APPS_FILE), _empty_apps())
    raw = data.get("apps", []) if isinstance(data, dict) else []
    apps, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        try:
            app = normalize_app(item)
        except (ValueError, TypeError):
            continue
        if app["id"] in seen:
            continue
        seen.add(app["id"])
        apps.append(app)
    return _dedupe(apps)


def save_apps(apps: list[dict]) -> None:
    apps = [normalize_app(a) for a in apps][:MAX_APPS]
    _write_json(path(APPS_FILE),
                {"format": FORMAT_APPS, "version": FORMAT_VERSION, "apps": apps})


def normalize_app(raw: dict) -> dict:
    """Validate one tile and fill in defaults. Used on load, add, edit and
    import so a hand-written config can never crash the server or the TV."""
    if not isinstance(raw, dict):
        raise ValueError("An app must be an object.")
    rid = str(raw.get("id") or "").strip()
    if not SAFE_NAME.fullmatch(rid) or len(rid) > 40:
        rid = secrets.token_hex(5)
    url = normalize_url(str(raw.get("url", "")))
    # Optional TV-remote-friendly address (e.g. https://www.youtube.com/tv).
    # When set, TV tiles and the generated dashboard open this instead of the
    # desktop URL, because a TV remote is a D-pad, not a mouse.
    tv_url = str(raw.get("tv_url") or "").strip()
    if tv_url:
        try:
            tv_url = normalize_url(tv_url)
        except ValueError as error:
            raise ValueError("TV-friendly URL: " + str(error)) from None
    remote = str(raw.get("remote") or "pointer")
    if remote not in ("pad", "pointer"):
        remote = "pointer"
    name = normalize_name(raw.get("name") or urlsplit(url).hostname or "App")
    image = normalize_image(raw.get("image", ""))
    icon = str(raw.get("icon") or "globe")
    if not SAFE_NAME.fullmatch(icon):
        icon = "globe"
    color = str(raw.get("color") or "")
    if not COLOR.fullmatch(color):
        color = "#2c2f3a"
    category = str(raw.get("category") or "Custom")[:24]
    source = str(raw.get("source") or "custom")
    if source not in ("custom", "catalog"):
        source = "custom"
    app = {
        "id": rid,
        "name": name,
        "url": url,
        "tv_url": tv_url,
        "remote": remote,
        "image": image,
        "icon": icon,
        "color": color,
        "category": category,
        "app_id": tile_app_id(raw),
        "source": source,
        "catalog_id": str(raw.get("catalog_id") or "")[:40],
        "installed": bool(raw.get("installed", False)),
        "added_at": str(raw.get("added_at") or "")[:40],
    }
    return app


def add_app(raw: dict) -> dict:
    apps = load_apps()
    raw = dict(raw)
    raw.setdefault("id", secrets.token_hex(5))
    raw.setdefault("added_at", datetime.datetime.now().isoformat(timespec="seconds"))
    app = normalize_app(raw)
    # Adding the same catalog app (or the same VIDAA tile id) twice must UPDATE
    # the existing tile, not create a duplicate that fights for one launcher
    # slot. Keep the stable id and the known install state.
    for index, existing in enumerate(apps):
        same_id = existing["app_id"] == app["app_id"]
        same_catalog = bool(app["catalog_id"]) and \
            existing.get("catalog_id") == app["catalog_id"]
        if same_id or same_catalog:
            raw["id"] = existing["id"]
            raw["added_at"] = existing.get("added_at") or raw["added_at"]
            raw.setdefault("installed", existing.get("installed", False))
            app = normalize_app(raw)
            apps[index] = app
            save_apps(apps)
            return app
    if len(apps) >= MAX_APPS:
        raise ValueError(f"You can keep up to {MAX_APPS} apps.")
    apps.append(app)
    save_apps(apps)
    return app


def update_app(app_id: str, patch: dict) -> dict:
    apps = load_apps()
    for index, app in enumerate(apps):
        if app["id"] == app_id:
            merged = dict(app)
            merged.update({k: v for k, v in patch.items()
                           if k in ("name", "url", "tv_url", "remote", "image",
                                    "icon", "color", "category", "installed")})
            apps[index] = normalize_app(merged)
            save_apps(apps)
            return apps[index]
    raise ValueError("That app no longer exists.")


def delete_app(app_id: str) -> None:
    apps = [a for a in load_apps() if a["id"] != app_id]
    save_apps(apps)


def reorder_apps(ids: list[str]) -> list[dict]:
    apps = load_apps()
    lookup = {a["id"]: a for a in apps}
    ordered = [lookup[i] for i in ids if i in lookup]
    ordered += [a for a in apps if a["id"] not in set(ids)]
    save_apps(ordered)
    return ordered


def mark_installed(app_id: str, installed: bool = True) -> None:
    apps = load_apps()
    for app in apps:
        if app["id"] == app_id:
            app["installed"] = bool(installed)
    save_apps(apps)


def get_app(app_id: str) -> dict | None:
    return next((a for a in load_apps() if a["id"] == app_id), None)


# --------------------------------------------------------------------------
# dashboard config
# --------------------------------------------------------------------------

def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    data = _read_json(path(CONFIG_FILE), {})
    if isinstance(data, dict):
        cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    return sanitize_config(cfg)


def sanitize_config(cfg: dict) -> dict:
    out = copy.deepcopy(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key not in cfg:
            continue
        value = cfg[key]
        if key in CONFIG_BOOLS:
            out[key] = bool(value)
        elif key in ("accent", "accent2"):
            out[key] = value if isinstance(value, str) and COLOR.fullmatch(value) else DEFAULT_CONFIG[key]
        elif key == "columns":
            try:
                out[key] = max(2, min(8, int(value)))
            except (TypeError, ValueError):
                pass
        elif key == "port":
            try:
                port = int(value)
                out[key] = port if 0 <= port <= 65535 else DEFAULT_CONFIG[key]
            except (TypeError, ValueError):
                pass
        elif key == "theme":
            out[key] = value if value in ("dark", "light", "midnight") else "dark"
        elif key == "tile_style":
            out[key] = value if value in ("rounded", "square", "glass") else "rounded"
        elif isinstance(value, str):
            out[key] = value[:120]
    return out


def save_config(patch: dict) -> dict:
    cfg = load_config()
    cfg.update({k: v for k, v in patch.items() if k in DEFAULT_CONFIG})
    cfg = sanitize_config(cfg)
    _write_json(path(CONFIG_FILE),
                {"format": FORMAT_CONFIG, "version": FORMAT_VERSION, **cfg})
    return cfg


# --------------------------------------------------------------------------
# icons
# --------------------------------------------------------------------------

def save_icon(filename: str, data: bytes) -> str:
    """Store an uploaded icon and return its public /icons/<name> URL path."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("That icon file is empty.")
    if len(data) > MAX_ICON_BYTES:
        raise ValueError("Icons must be smaller than 400 KB.")
    name = os.path.basename(str(filename or "")).strip()
    stem, dot, ext = name.rpartition(".")
    ext = ext.lower() if dot else ""
    if ext not in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
        raise ValueError("Use a PNG, JPG, GIF, WebP or SVG image.")
    if not data.startswith((b"\x89PNG", b"\xff\xd8", b"GIF8", b"RIFF", b"<svg", b"<?xml")) \
            and ext != "svg":
        raise ValueError("That file does not look like an image.")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", stem)[:24] or "icon"
    final = f"{safe}-{secrets.token_hex(3)}.{ext}"
    target = icons_dir() / final
    with open(target, "wb") as f:
        f.write(bytes(data))
    return "/icons/" + final


def read_icon(name: str) -> tuple[Path, str] | None:
    """Resolve a safe icon file name inside the icons dir (no traversal)."""
    if not SAFE_NAME.fullmatch(name or ""):
        return None
    p = icons_dir() / name
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}.get(ext)
    if not ctype:
        return None
    return p, ctype


def _icon_payloads() -> dict:
    out = {}
    for p in sorted(icons_dir().glob("*")):
        if p.is_file() and SAFE_NAME.fullmatch(p.name) and p.stat().st_size <= MAX_ICON_BYTES:
            try:
                out[p.name] = base64.b64encode(p.read_bytes()).decode("ascii")
            except OSError:
                continue
    return out


# --------------------------------------------------------------------------
# import / export
# --------------------------------------------------------------------------

def export_config() -> dict:
    return {
        "format": FORMAT_EXPORT,
        "version": FORMAT_VERSION,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "custom_apps": {"format": FORMAT_APPS, "version": FORMAT_VERSION,
                        "apps": load_apps()},
        "dashboard_config": {"format": FORMAT_CONFIG, "version": FORMAT_VERSION,
                             **load_config()},
        "icons": _icon_payloads(),
    }


def _apps_from_import(obj) -> list[dict]:
    """Accept an export bundle, an apps file, an {apps:[...]} object, a bare
    list, or a single app. Be liberal, but validate every entry."""
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        raise ValueError("The config must be a JSON object.")
    if "custom_apps" in obj:
        inner = obj["custom_apps"]
        return inner.get("apps", []) if isinstance(inner, dict) else []
    if "apps" in obj:
        return obj["apps"] if isinstance(obj["apps"], list) else []
    if "url" in obj:
        return [obj]
    raise ValueError("No apps were found in that file.")


def import_config(obj, merge: bool = False) -> dict:
    """Import a config from another device. Returns counts for the UI."""
    if not isinstance(obj, dict) and not isinstance(obj, list):
        raise ValueError("That file is not a Sidee config.")
    raw_apps = _apps_from_import(obj)
    if not isinstance(raw_apps, list):
        raise ValueError("The app list is invalid.")
    incoming = []
    for item in raw_apps[:MAX_APPS]:
        try:
            incoming.append(normalize_app(item))
        except (ValueError, TypeError):
            continue
    if merge:
        apps = load_apps()
        known = {(a["name"].lower(), a["url"]) for a in apps}
        for app in incoming:
            if (app["name"].lower(), app["url"]) not in known:
                apps.append(app)
    else:
        apps = incoming
    apps = _dedupe(apps)
    save_apps(apps)

    icons_added = 0
    icons = obj.get("icons", {}) if isinstance(obj, dict) else {}
    if isinstance(icons, dict):
        for name, encoded in icons.items():
            if not isinstance(name, str) or not SAFE_NAME.fullmatch(name) \
                    or not isinstance(encoded, str):
                continue
            try:
                raw = base64.b64decode(encoded, validate=True)
                save_icon(name, raw)
                icons_added += 1
            except (ValueError, OSError):
                continue

    cfg_patch = {}
    if isinstance(obj, dict):
        source = obj.get("dashboard_config", obj)
        if isinstance(source, dict):
            cfg_patch = {k: v for k, v in source.items() if k in DEFAULT_CONFIG}
    save_config(cfg_patch)
    return {"apps": len(apps), "icons": icons_added, "ok": True}
