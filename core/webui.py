"""Local Sidee Enhanced web interface.

Serves three things over one access-key-protected HTTP server:

  * ``/``          the redesigned browser console (core/enhanced.html)
  * ``/setup``     the original three-step page (core/dashboard.html)
  * ``/dashboard`` the generated full-screen TV launcher (core/tv_dashboard.html)

plus ``/player`` (local media), ``/icons/`` (uploads), ``/media/`` (video
files with Range support) and the JSON API used by both UIs.

Security (unchanged): the dashboard is reachable only with the unique key
printed at startup (in the URL and QR code); the PIN and tokens are never
logged; all TV communication stays on the local network over MQTT/TLS 36669.

The enhanced install path deliberately allows arbitrary web URLs (any
domain). It validates the URL *shape*, shows a trust warning in the UI, and
uses the SAME client.add_tile() MQTT action as the original curated presets —
so each app becomes a permanent launcher tile on the TV and keeps working
when Sidee/the computer is switched off.
"""
from __future__ import annotations

import base64
import http.server
import http.client
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import socketserver
import tempfile
import threading
import time
import urllib.parse
import webbrowser

from . import client, presets, platform_support
from . import storage, catalog, media, autostart
from .pairing import PairingFlow
from .phone import qr_image

_PORT = 8080   # configurable with --port / Settings; falls back to a free port
VERSION = "1.0.0-enhanced"
ROOT = str(platform_support.resource_root(__file__))
ACCESS_KEY = secrets.token_urlsafe(16)
PAIRING = PairingFlow()
# Enter your Ko-fi/Sponsors link here: it appears in the dashboard footer
KOFI_URL = "https://ko-fi.com/sidee"


def _read(name: str) -> str:
    with open(os.path.join(ROOT, "core", name), encoding="utf-8") as f:
        return f.read()


_PAGE = _read("dashboard.html")               # classic setup page
_ENHANCED_PAGE = _read("enhanced.html")       # redesigned console
_TV_TEMPLATE = _read("tv_dashboard.html")     # generated TV dashboard template

# Uploaded icons are public static assets (like /assets/) so a TV tile and the
# TV dashboard can display them without embedding the access key in an <img>.
_PUBLIC_PREFIXES = ("/assets/", "/icons/")


def _render(page: str) -> bytes:
    return page.replace("KOFI_URL_PLACEHOLDER", KOFI_URL).encode("utf-8")


def _server_port(server) -> int:
    address = getattr(server, "server_address", None)
    try:
        return int(address[1])
    except (TypeError, IndexError, ValueError):
        return _PORT


def _lan_base(port: int) -> str:
    """Absolute LAN URL of this Sidee server (never loopback for the TV)."""
    return f"http://{_local_ip()}:{port}"


def dashboard_url(port: int, tv_host: str | None = None) -> str:
    host = _local_ip(tv_host)
    return f"http://{host}:{port}/dashboard?key={urllib.parse.quote(ACCESS_KEY, safe='')}"


def player_url(port: int) -> str:
    return f"{_lan_base(port)}/player?key={urllib.parse.quote(ACCESS_KEY, safe='')}"


def render_tv_dashboard(port: int) -> bytes:
    """Generate the personalised full-screen TV dashboard HTML for this user."""
    data = {
        "config": storage.load_config(),
        "apps": storage.load_apps(),
        "icons": {i["id"]: {"glyph": i["glyph"], "label": i["label"]}
                  for i in catalog.icon_library()},
    }
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return _render(_TV_TEMPLATE.replace("__SIDEE_DATA__", blob))


def render_player() -> bytes:
    return media.player_page(media.scan(), ACCESS_KEY).encode("utf-8")


def state_payload(port: int) -> dict:
    """One bootstrap call for the redesigned console."""
    cfg = storage.load_config()
    cfg["port_effective"] = port
    return {
        "ok": True,
        "version": VERSION,
        "apps": storage.load_apps(),
        "catalog": catalog.by_category(),
        "icons": {i["id"]: {"label": i["label"], "glyph": i["glyph"],
                            "color": i["color"]} for i in catalog.icon_library()},
        "config": cfg,
        "status": _status(),
        "autostart": autostart.status(),
        "dashboard_url": dashboard_url(port),
        "player_url": player_url(port),
        "trust_warning": storage.TRUST_WARNING,
        "media": {"videos": media.scan(), "root": str(media.root() or "")},
    }


# --------------------------------------------------------------------------
# TV installation (the "install apps inside the TV, not only on the server"
# path). Uses the existing, PIN-paired MQTT action — no new network surface.
# --------------------------------------------------------------------------

def _paired_session() -> client.Session:
    session = client.Session().load_or_none()
    if not session:
        raise client.AuthError("none", "no TV paired: pair your TV first")
    return session


def install_app(app: dict, port: int) -> dict:
    """Register ONE app (custom URL or catalog) as a permanent TV tile."""
    session = _paired_session()
    url, name = app["url"], app["name"]
    app_id = storage.tile_app_id(app)
    image = app.get("image") or ""
    if image.startswith(("/icons/", "/assets/")):
        image = _lan_base(port) + image           # absolute LAN URL for the TV
    if not image:
        # Self-contained SVG: the tile never needs the Sidee server to show it.
        image = catalog.icon_data_uri(app.get("icon", "globe"), name)
    tiles = client.add_tile(session, app_id, name, url, image)
    confirmed = any(isinstance(t, dict) and
                    client.tile_matches_request(t, app_id, url) for t in tiles)
    storage.mark_installed(app["id"], confirmed)
    if confirmed:
        return {"ok": True, "status": "installed", "app_id": app_id,
                "message": name + " is installed on your TV. Press Home to open it.",
                "error": None}
    return {"ok": False, "status": "unconfirmed", "app_id": app_id,
            "error": None,
            "message": name + " was requested, but the TV has not confirmed its "
                       "address yet. Check Home on your TV before trying again."}


def install_all_apps(port: int) -> dict:
    _paired_session()  # fail fast with a pairing hint before the long loop
    apps = storage.load_apps()
    results, installed = [], 0
    for app in apps:
        try:
            r = install_app(app, port)
        except client.AuthError:
            raise
        except Exception as error:      # one bad app must not stop the rest
            r = {"ok": False, "error": str(error)}
        results.append({"id": app["id"], "ok": r.get("ok", False)})
        installed += 1 if r.get("ok") else 0
    return {"ok": True, "total": len(apps), "installed": installed,
            "results": results, "apps": storage.load_apps()}


def install_dashboard_tile(port: int) -> dict:
    """Install the hosted dashboard as ONE launcher tile (needs Sidee running)."""
    session = _paired_session()
    url = dashboard_url(port)
    app_id, name = "sideedashboard", "My Dashboard"
    image = catalog.icon_data_uri("grid", "Sidee")
    tiles = client.add_tile(session, app_id, name, url, image)
    confirmed = any(isinstance(t, dict) and
                    client.tile_matches_request(t, app_id, url) for t in tiles)
    return {"ok": confirmed, "status": "installed" if confirmed else "unconfirmed",
            "error": None,
            "message": "Dashboard tile installed. Press Home on your TV." if confirmed
                       else "Install requested, but the TV has not confirmed it yet. "
                            "Check Home before trying again."}


def preview_on_tv(port: int) -> dict:
    """Temporarily open the dashboard on the TV without installing a tile."""
    session = _paired_session()
    url = dashboard_url(port)
    client.launch_tile(session, "sideedashboard", "My Dashboard", url)
    return {"ok": True, "message": "Preview opened on your TV. Press Back to return."}


def _status() -> dict:
    s = client.Session().load_or_none()
    if not s:
        return {"paired": False, "state": "needs_pairing",
                "message": "Pair your TV: the PIN on the screen is required"}
    if s.expires_at and time.time() >= s.expires_at:
        return {"paired": True, "state": "expired", "host": s.host,
                "expires_at": s.expires_at,
                "message": "Token expired: pair your TV again to continue"}
    return {"paired": True, "state": "ok", "host": s.host,
            "expires_at": s.expires_at}


def _phone_access(port: int, tv_host: str | None = None) -> dict:
    host = _local_ip(tv_host)
    address = ipaddress.IPv4Address(host)
    if (address.is_loopback or address.is_unspecified or address.is_multicast
            or address.is_link_local):
        return {"ok": False, "error": "Connect this computer to your home network, "
                "then refresh this page to get the phone QR code."}
    url = f"http://{host}:{port}/?key={ACCESS_KEY}"
    return {"ok": True, "url": url, "qr": qr_image(url)}


def _probe_tv_ip(host: str) -> dict:
    """Verify a manually entered LAN IPv4 before allowing PIN pairing."""
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return {"ok": False, "error": "Enter a valid TV IPv4 address, e.g. 192.168.1.50."}
    # Do not probe Internet, loopback, link-local or multicast addresses.
    subnets = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(address in ipaddress.IPv4Network(net) for net in subnets):
        return {"ok": False, "error": "Use a private IPv4 address on your home network."}
    info = client.fetch_descriptor(str(address))
    try:
        with socket.create_connection((str(address), client.MQTT_PORT), timeout=2):
            mqtt_open = True
    except OSError:
        mqtt_open = False
    if not info or not info.is_vidaa:
        message = ("Port 36669 responds, but Sidee could not verify a VIDAA TV "
                   "using its device description." if mqtt_open else
                   "No VIDAA TV description or port 36669 response at that IP. "
                   "Check the TV address, its network and VPN settings.")
        return {"ok": False, "error": message}
    if not mqtt_open:
        return {"ok": False, "error": "VIDAA TV found, but TCP port 36669 is "
                "unreachable. Check local network permissions, VPN, firewall "
                "and Wi-Fi isolation."}
    return {"ok": True, "tv": {**info.__dict__, "raw_description": ""},
            "message": "VIDAA TV verified by IP. Automatic SSDP discovery may "
                       "be blocked; PIN pairing is still required."}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _authorized(self) -> bool:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return q.get("key", [""])[0] == ACCESS_KEY

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Sidee", "2")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send(self, body: bytes, ctype: str, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _html(self, body: bytes):
        self._send(body, "text/html; charset=utf-8")

    # -------------------------------------------------------------- GET ---
    def do_GET(self):
        parts = urllib.parse.urlparse(self.path)
        path = parts.path
        public = path.startswith(_PUBLIC_PREFIXES) or path == "/favicon.ico"
        if not public and not self._authorized():
            # static assets are public; everything else requires the key
            self._json({"error": "unauthorized"}, 403)
            return
        port = _server_port(self.server)
        if path == "/":
            self._html(_render(_ENHANCED_PAGE))
        elif path in ("/setup", "/classic"):
            self._html(_render(_PAGE))
        elif path == "/dashboard":
            self._html(render_tv_dashboard(port))
        elif path == "/player":
            self._html(render_player())
        elif path == "/favicon.ico":
            self._serve_asset("sidee-logo.png")
        elif path.startswith("/assets/"):
            self._serve_asset(os.path.basename(path))
        elif path.startswith("/icons/"):
            self._serve_icon(os.path.basename(path))
        elif path.startswith("/media/raw/") or path.startswith("/media/sub/"):
            self._serve_media(path)
        elif path == "/api/status":
            self._json(_status())
        elif path == "/api/state":
            self._json(state_payload(port))
        elif path == "/api/catalog":
            query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
            self._json({"ok": True, "apps": catalog.search(query.get("q", [""])[0])})
        elif path == "/api/dashboard/url":
            self._json({"ok": True, "url": dashboard_url(port),
                        "lan_ip": _local_ip(), "port": port})
        elif path == "/api/dashboard/preview":
            self._html(render_tv_dashboard(port))
        elif path == "/api/media/list":
            self._json({"ok": True, "videos": media.scan(),
                        "root": str(media.root() or "")})
        elif path == "/api/config/export":
            self._json(storage.export_config())
        elif path == "/api/phone":
            query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
            tv_host = query.get("tv_host", [None])[0]
            if tv_host is not None:
                try:
                    ipaddress.IPv4Address(tv_host)
                except ValueError:
                    self._json({"ok": False, "error": "The TV IP address is invalid. "
                                "Find your TV again to update the phone QR code."})
                    return
            self._json(_phone_access(port, tv_host))
        elif path == "/api/discover":
            try:
                tvs = [t.__dict__ | {"raw_description": ""}
                       for t in client.discover()]
                self._json({"ok": True, "tvs": tvs})
            except Exception as e:
                self._json({"ok": False, "error": repr(e)})
        else:
            self._json({"error": "not found"}, 404)

    def _serve_asset(self, name: str) -> None:
        # allowlist: only PNG files from the assets/ package
        p = os.path.join(ROOT, "assets", name)
        if not name.endswith(".png") or not os.path.isfile(p):
            self._json({"error": "not found"}, 404)
            return
        with open(p, "rb") as f:
            self._send(f.read(), "image/png")

    def _serve_icon(self, name: str) -> None:
        resolved = storage.read_icon(name)
        if not resolved:
            self._json({"error": "not found"}, 404)
            return
        p, ctype = resolved
        with open(p, "rb") as f:
            self._send(f.read(), ctype)

    def _serve_media(self, path: str) -> None:
        subtitle = path.startswith("/media/sub/")
        rel = urllib.parse.unquote(path[len("/media/sub/" if subtitle else "/media/raw/"):])
        target = media.file_path(rel)
        if not target:
            self._json({"error": "not found"}, 404)
            return
        if subtitle:
            if target.suffix.lower() not in media.SUBTITLE_EXTENSIONS:
                self._json({"error": "not found"}, 404)
                return
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._json({"error": "not found"}, 404)
                return
            if target.suffix.lower() == ".srt":
                text = media.srt_to_vtt(text)
            self._send(text.encode("utf-8"), "text/vtt; charset=utf-8")
            return
        if target.suffix.lower() not in media.VIDEO_EXTENSIONS:
            self._json({"error": "not found"}, 404)
            return
        ctype = media.CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        size = target.stat().st_size
        start, end = 0, size - 1
        range_header = self.headers.get("Range", "")
        partial = False
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if match and size:
            partial = True
            if match.group(1):
                start = int(match.group(1))
            else:
                suffix = int(match.group(2) or 0)
                start = max(0, size - suffix)
            if match.group(2):
                end = min(int(match.group(2)), size - 1)
            if start > end or start >= size:
                self._send(b"", ctype, 416,
                           {"Content-Range": f"bytes */{size}"})
                return
        length = max(0, end - start + 1)
        headers = {"Accept-Ranges": "bytes"}
        if partial:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            with open(target, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ------------------------------------------------------------- POST ---
    def do_POST(self):
        parts = urllib.parse.urlparse(self.path)
        path = parts.path
        if not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            # Import bundles and icon uploads can contain base64 images.
            big = path in ("/api/config/import", "/api/icon/upload")
            if length > (12_000_000 if big else 4096):
                self._json({"ok": False, "error": "payload too large"})
                return
            data = json.loads(self.rfile.read(length) or b"{}")
            if parts.path == "/api/pair/start":
                host = str(data.get("host", ""))
                try:
                    ipaddress.IPv4Address(host)
                except ValueError:
                    self._json({"ok": False, "error": "invalid IP address"})
                    return
                self._json(PAIRING.start(host))
            elif parts.path == "/api/pair":
                self._json(PAIRING.confirm(str(data.get("pairing_id", "")),
                                           str(data.get("pin", ""))))
            elif parts.path == "/api/pair/cancel":
                self._json(PAIRING.cancel(str(data.get("pairing_id", ""))))
            elif parts.path == "/api/tv/check":
                self._json(_probe_tv_ip(str(data.get("host", "")).strip()))
            elif (parts.path == "/api/shutdown" and
                  getattr(self.server, "headless", False) and
                  ipaddress.ip_address(self.client_address[0]).is_loopback):
                self._json({"ok": True})
                self.server.stop_event.set()
            elif parts.path == "/api/install":
                try:
                    result = self._install(data)
                except client.AuthError as e:
                    self._json({"ok": False, "error": str(e),
                                "needs_pairing": e.kind in
                                ("none", "rejected", "expired", "corrupt", "needs_pairing")})
                    return
                self._json(result)
            # ---- enhanced API ----
            elif path == "/api/apps/add":
                self._json(self._apps_add(data, _server_port(self.server)))
            elif path == "/api/apps/update":
                self._json({"ok": True, "apps": self._apps_update(data)})
            elif path == "/api/apps/delete":
                storage.delete_app(str(data.get("id", "")))
                self._json({"ok": True, "apps": storage.load_apps()})
            elif path == "/api/apps/reorder":
                ids = data.get("ids", [])
                if not isinstance(ids, list):
                    raise ValueError("The tile order is invalid.")
                self._json({"ok": True, "apps": storage.reorder_apps(
                    [str(i) for i in ids])})
            elif path == "/api/apps/install":
                self._json(self._apps_install(data, _server_port(self.server)))
            elif path == "/api/apps/install_all":
                self._json(install_all_apps(_server_port(self.server)))
            elif path == "/api/dashboard/config":
                patch = {k: v for k, v in data.items() if k in storage.DEFAULT_CONFIG}
                self._json({"ok": True, "config": storage.save_config(patch)})
            elif path == "/api/dashboard/install":
                self._json(install_dashboard_tile(_server_port(self.server)))
            elif path == "/api/preview":
                self._json(preview_on_tv(_server_port(self.server)))
            elif path == "/api/config/import":
                obj = data.get("config", data)
                result = storage.import_config(obj, merge=bool(data.get("merge")))
                self._json(result)
            elif path == "/api/icon/upload":
                raw = base64.b64decode(str(data.get("data", "")), validate=True)
                image = storage.save_icon(str(data.get("name", "icon.png")), raw)
                self._json({"ok": True, "image": image})
            elif path == "/api/media/scan":
                root = media.set_root(str(data.get("path", "")))
                self._json({"ok": True, "root": root, "videos": media.scan()})
            elif path == "/api/autostart":
                self._json(autostart.set_autostart(bool(data.get("enabled"))))
            elif path == "/api/keepalive":
                self._json(autostart.set_keep_alive(bool(data.get("enabled"))))
            elif path == "/api/onboarded":
                self._json({"ok": True, "config":
                            storage.save_config({"onboarded": True})})
            else:
                self._json({"error": "not found"}, 404)
        except client.AuthError as e:
            self._json({"ok": False, "error": str(e),
                        "needs_pairing": e.kind in
                        ("none", "rejected", "expired", "corrupt", "needs_pairing")})
        except (ValueError, TypeError, OSError) as e:
            self._json({"ok": False, "error": str(e)})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    # ---- enhanced helpers ----
    def _apps_add(self, data: dict, port: int) -> dict:
        catalog_id = str(data.get("catalog_id", "")).strip()
        if catalog_id:
            entry = catalog.get(catalog_id)
            if not entry:
                raise ValueError("Unknown catalog app.")
            tile = catalog.catalog_tile(entry, str(data.get("server", "")),
                                        _lan_base(port))
            app = storage.add_app(tile)
        else:
            app = storage.add_app({
                "name": str(data.get("name", "")),
                "url": str(data.get("url", "")),
                "image": str(data.get("image", "")),
                "icon": str(data.get("icon", "globe")),
                "color": str(data.get("color", "")),
                "category": str(data.get("category", "Custom")),
                "source": "custom",
            })
        return {"ok": True, "app": app, "apps": storage.load_apps(),
                "warning": storage.TRUST_WARNING}

    def _apps_update(self, data: dict) -> list[dict]:
        app_id = str(data.get("id", ""))
        patch = {k: v for k, v in data.items()
                 if k in ("name", "url", "image", "icon", "color", "category")}
        if not patch:
            raise ValueError("Nothing to update.")
        storage.update_app(app_id, patch)
        return storage.load_apps()

    def _apps_install(self, data: dict, port: int) -> dict:
        app = storage.get_app(str(data.get("id", "")))
        if not app:
            raise ValueError("That app no longer exists.")
        result = install_app(app, port)
        result["apps"] = storage.load_apps()
        return result

    # ---- legacy preset installer (unchanged) ----
    def _install(self, data: dict) -> dict:
        key = data.get("app", "")
        p = presets.get(key)
        if not p:
            return {"ok": False, "error": "unknown preset"}
        server = str(data.get("server", "")).strip()
        if p.get("needs_server"):
            if not server:
                return {"ok": False, "error": "enter your " + p["name"]
                                              + " server address"}
            p = dict(p)
            p["url"] = presets.build_server_url(server)
        elif p.get("server_builder") == "stremio":
            p = dict(p)
            p["url"] = presets.build_stremio_url(server)
        _validate_preset(p)
        s = client.Session.load()
        apps = client.add_tile(s, p["app_id"], p["name"], p["url"],
                               p["image"])
        found = [a for a in apps
                 if isinstance(a, dict) and
                 str(a.get("appId", "")).lower() == p["app_id"]]
        confirmed = any(client.tile_matches_request(a, p["app_id"], p["url"])
                        for a in found)
        dups = len(found)
        return {"ok": confirmed,
                "status": "installed" if confirmed else "unconfirmed",
                "error": None,
                "message": None if confirmed else
                p["name"] + " installation was requested, but the TV has not "
                "confirmed its current address yet. Check Home on your TV "
                "before trying again.",
                "duplicates": max(0, dups - 1) if found else 0}


def _validate_preset(p: dict) -> None:
    """Tile URLs must use https; http is allowed ONLY for hosts on
    the user's private network (e.g. their own Jellyfin server)."""
    if not re.fullmatch(r"[a-z0-9_]{1,32}", p["app_id"]):
        raise ValueError("invalid app_id")
    url = p["url"]
    if url.startswith("https://") and len(url) <= 300:
        pass
    elif url.startswith("http://") and presets.is_private_host(url) \
            and len(url) <= 300:
        pass
    else:
        raise ValueError("URL must use https (or http on your LAN)")
    if not re.fullmatch(r"[\w \-']{1,40}", p["name"]):
        raise ValueError("invalid name")
    if p["image"] and not p["image"].startswith("https://"):
        raise ValueError("icon URL must use https")


def _dashboard_state_path() -> str:
    return str(platform_support.dashboard_state_path(ROOT))


def _reopen_dashboard(open_browser: bool) -> bool:
    """A second double-click opens this folder's existing dashboard."""
    connection = None
    try:
        with open(_dashboard_state_path(), encoding="utf-8") as f:
            state = json.load(f)
        port, key = state["port"], state["key"]
        if (type(port) is not int or not 0 < port < 65536 or
                not isinstance(key, str) or not key):
            return False
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        connection.request("GET", "/api/status?key=" + urllib.parse.quote(key, safe=""))
        response = connection.getresponse()
        if response.status != 200 or response.getheader("X-Sidee") != "2":
            return False
        response.read()
        url = f"http://127.0.0.1:{port}/?key={urllib.parse.quote(key, safe='')}"
        if open_browser:
            webbrowser.open(url)
        print("Your dashboard is already running. Use its original window to close it.")
        return True
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
        return False
    finally:
        if connection:
            connection.close()


def _remember_dashboard(port: int) -> None:
    path = _dashboard_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=os.path.dirname(path), delete=False) as f:
            pending = f.name
            json.dump({"port": port, "key": ACCESS_KEY, "pid": os.getpid()}, f)
        os.chmod(pending, 0o600)
        os.replace(pending, path)
    finally:
        if pending and os.path.isfile(pending):
            os.remove(pending)


def _forget_dashboard() -> None:
    try:
        path = _dashboard_state_path()
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if state.get("pid") == os.getpid() and state.get("key") == ACCESS_KEY:
            os.remove(path)
    except (OSError, ValueError, AttributeError):
        pass


class DashboardServer(http.server.ThreadingHTTPServer):
    # Windows SO_REUSEADDR can silently share the port with another process.
    # Each dashboard must exclusively own its address and access key.
    allow_reuse_address = platform_support.allow_reuse_address()
    allow_reuse_port = False

    def server_bind(self):
        platform_support.configure_exclusive_tcp_socket(self.socket)
        # HTTPServer's default bind performs reverse DNS for 0.0.0.0. That
        # lookup can stall macOS startup on offline or filtered networks.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


def _bind_dashboard_server(port: int | None = None):
    port = _PORT if port is None else port
    try:
        return DashboardServer(("0.0.0.0", port), Handler)
    except OSError as e:
        if not platform_support.address_in_use(e):
            raise
        return DashboardServer(("0.0.0.0", 0), Handler)


class Dashboard:
    """Own the dashboard socket and lifecycle, shared by both launchers."""

    def __init__(self, port: int | None = None, headless: bool = False):
        self.server = _bind_dashboard_server(port)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/?key={ACCESS_KEY}"
        self.stop_event = threading.Event()
        self.server.stop_event = self.stop_event
        self.server.headless = headless
        self.server.timeout = 0.2
        self.thread = None
        self.error = None

    def start(self) -> None:
        try:
            _remember_dashboard(self.port)
            self.thread = threading.Thread(target=self._run, daemon=True,
                                           name="sidee-dashboard")
            self.thread.start()
        except BaseException:
            self.server.server_close()
            _forget_dashboard()
            raise

    def _run(self) -> None:
        try:
            while not self.stop_event.is_set():
                self.server.handle_request()
        except Exception as error:
            self.error = error
        finally:
            self.stop_event.set()

    def open(self) -> bool:
        return webbrowser.open(self.url)

    def close(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        self.server.server_close()
        PAIRING.close()
        _forget_dashboard()


def serve(open_browser: bool = True, port: int | None = None,
          headless: bool = False) -> None:
    if _reopen_dashboard(open_browser):
        return
    dashboard = Dashboard(port, headless)
    previous_signals = {}
    try:
        dashboard.start()
        # Signal handlers set an event; cleanup runs outside the handler.
        if threading.current_thread() is threading.main_thread():
            for number in (signal.SIGINT, signal.SIGTERM):
                previous_signals[number] = signal.signal(
                    number, lambda *_: dashboard.stop_event.set())
        print(f"Sidee Enhanced (this computer): {dashboard.url}", flush=True)
        print(f"Sidee Enhanced (from your phone, same network): "
              f"http://{_local_ip()}:{dashboard.port}/?key={ACCESS_KEY}", flush=True)
        print(f"TV dashboard (full screen): "
              f"{dashboard_url(dashboard.port)}", flush=True)
        print("Use your phone: scan the QR code shown in the dashboard.")
        print("Keep the URL key private. Ctrl+C to quit.")
        if open_browser:
            dashboard.open()
        dashboard.stop_event.wait()
        if dashboard.error:
            raise dashboard.error
    except KeyboardInterrupt:
        pass
    finally:
        for number, handler in previous_signals.items():
            signal.signal(number, handler)
        dashboard.close()


def _local_ip(tv_host: str | None = None) -> str:
    """Choose a local interface without sending traffic or needing Internet.

    The TV route takes precedence over a VPN's default route. Before a TV
    has been selected, the local broadcast route selects a LAN interface.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if tv_host:
            s.connect((tv_host, client.MQTT_PORT))
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.connect((client.SSDP_BROADCAST, client.SSDP_PORT))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
