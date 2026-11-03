"""Sidee Enhanced built-in app catalog and icon library.

The catalog is data only: it never contacts the network. Each entry becomes a
tile that can be added to the local dashboard and/or installed as a permanent
launcher tile on the TV (``client.add_tile``). Icons are rendered locally as
coloured SVGs, so the dashboard always looks right even fully offline.
"""
from __future__ import annotations

import base64
import html
import re
from urllib.parse import urlsplit

from . import presets, storage

# An ordered, searchable set of categories shown in the UI.
CATEGORIES = ("Featured", "Streaming", "Music", "Utilities", "Media",
              "Gaming", "Productivity")

# Built-in icon library: id -> (label, glyph, accent colour). Users can pick
# one of these, upload their own image, or paste an icon URL.
BUILTIN_ICONS: dict[str, tuple[str, str, str]] = {
    "globe":     ("Globe", "🌐", "#3d7bfd"),
    "play":      ("Play", "▶️", "#e53b3b"),
    "film":      ("Film", "🎬", "#b23bd6"),
    "tv":        ("TV", "📺", "#2bb1a8"),
    "music":     ("Music", "🎵", "#1db954"),
    "radio":     ("Radio", "📻", "#e0672b"),
    "cloud":     ("Cloud", "☁️", "#4a86e8"),
    "server":    ("Server", "🗄️", "#6b7280"),
    "home":      ("Home", "🏠", "#f0a020"),
    "chart":     ("Chart", "📊", "#e5812a"),
    "shield":    ("Shield", "🛡️", "#c0392b"),
    "speed":     ("Speed", "⚡", "#f4c20d"),
    "weather":   ("Weather", "⛅", "#37a9e0"),
    "game":      ("Game", "🎮", "#7c5cff"),
    "folder":    ("Folder", "📁", "#d9a441"),
    "drive":     ("Drive", "📦", "#2a9d4b"),
    "note":      ("Notes", "📝", "#8a8f98"),
    "calendar":  ("Calendar", "📅", "#4285f4"),
    "grid":      ("Grid", "🔲", "#5b6472"),
    "heart":     ("Heart", "❤️", "#e0457b"),
    "star":      ("Star", "⭐", "#f2b705"),
    "rocket":    ("Rocket", "🚀", "#7c5cff"),
    "camera":    ("Camera", "📷", "#8e44ad"),
}


def _fav(domain: str) -> str:
    """A public https icon URL used only for the TV launcher tile."""
    return f"https://{domain}/favicon.ico"


def _app(id, name, url, category, icon, color, description, image="",
         **extra):
    d = dict(id=id, name=name, url=url, category=category, icon=icon,
             color=color, description=description, image=image)
    d.update(extra)
    return d


# Each entry: id, name, url, category, builtin icon, colour, description,
# TV icon (https), plus optional server-building hints.
APPS: list[dict] = [
    # --- Featured: the original curated presets, kept for compatibility ---
    _app("nuvio", "Nuvio", "https://nuviotvsmart.vercel.app/vidaa.html",
         "Featured", "play", "#ffe600", "Browse and stream your library",
         "https://nuviotvsmart.vercel.app/assets/images/tizenIcon.png"),
    _app("stremio", "Stremio",
         "https://noobygains.github.io/stremio-vidaa-tv/?install_source=sidee",
         "Featured", "play", "#7c5cff", "Full Stremio TV for VIDAA",
         "https://noobygains.github.io/stremio-vidaa-tv/icon.png",
         server_builder="stremio", server_optional=True,
         server_placeholder="Streaming server URL (optional)"),
    _app("jellyfin", "Jellyfin", "", "Featured", "film", "#aa5cc3",
         "Your media from your Jellyfin server", _fav("jellyfin.org"),
         needs_server=True, server_builder="jellyfin",
         server_placeholder="Your server's IP or URL (e.g. 192.168.1.50)"),

    # --- Streaming ---
    _app("plex", "Plex", "https://app.plex.tv", "Streaming", "play", "#e5a00d",
         "Plex web player", _fav("plex.tv")),
    _app("emby", "Emby", "", "Streaming", "film", "#52b54b",
         "Your Emby media server", _fav("emby.media"),
         needs_server=True, server_builder="jellyfin",
         server_placeholder="Your Emby server's IP or URL"),
    _app("youtube", "YouTube", "https://www.youtube.com", "Streaming", "play",
         "#ff0033", "YouTube on the big screen", _fav("youtube.com")),
    _app("netflix", "Netflix", "https://www.netflix.com", "Streaming", "film",
         "#e50914", "Netflix web", _fav("netflix.com")),
    _app("disney", "Disney+", "https://www.disneyplus.com", "Streaming", "star",
         "#113ccf", "Disney+ web", _fav("disneyplus.com")),
    _app("twitch", "Twitch", "https://www.twitch.tv", "Streaming", "tv",
         "#9146ff", "Live streams and esports", _fav("twitch.tv")),
    _app("primevideo", "Prime Video", "https://www.primevideo.com", "Streaming",
         "play", "#00a8e1", "Amazon Prime Video web", _fav("primevideo.com")),

    # --- Music ---
    _app("spotify", "Spotify", "https://open.spotify.com", "Music", "music",
         "#1db954", "Spotify web player", _fav("spotify.com")),
    _app("applemusic", "Apple Music", "https://music.apple.com", "Music",
         "music", "#fa243c", "Apple Music web", _fav("music.apple.com")),
    _app("tidal", "Tidal", "https://listen.tidal.com", "Music", "music",
         "#111111", "Tidal web player", _fav("tidal.com")),
    _app("ytmusic", "YouTube Music", "https://music.youtube.com", "Music",
         "music", "#ff0033", "YouTube Music", _fav("music.youtube.com")),
    _app("radio", "Internet Radio", "https://www.radio-browser.info", "Music",
         "radio", "#e0672b", "Browse thousands of radio stations",
         _fav("radio-browser.info")),

    # --- Utilities ---
    _app("homeassistant", "Home Assistant", "", "Utilities", "home", "#41bdf5",
         "Your smart-home dashboard", _fav("home-assistant.io"),
         needs_server=True, server_builder="lan", default_port=8123,
         server_placeholder="Home Assistant IP (e.g. 192.168.1.20:8123)"),
    _app("grafana", "Grafana", "", "Utilities", "chart", "#f46800",
         "Metrics and dashboards", _fav("grafana.com"),
         needs_server=True, server_builder="lan", default_port=3000,
         server_placeholder="Grafana IP (e.g. 192.168.1.20:3000)"),
    _app("pihole", "Pi-hole", "", "Utilities", "shield", "#c0392b",
         "Network-wide ad blocking admin", _fav("pi-hole.net"),
         needs_server=True, server_builder="lan", default_port=80,
         server_placeholder="Pi-hole IP (e.g. 192.168.1.2)"),
    _app("speedtest", "Speedtest", "https://www.speedtest.net", "Utilities",
         "speed", "#14c3a2", "Test your connection speed", _fav("speedtest.net")),
    _app("weather", "Weather", "https://weather.com", "Utilities", "weather",
         "#37a9e0", "Weather forecast", _fav("weather.com")),

    # --- Media / NAS ---
    _app("localmedia", "Local Media Server", "", "Media", "server", "#6b7280",
         "Any media server on your LAN", "",
         needs_server=True, server_builder="lan",
         server_placeholder="Server URL (e.g. http://192.168.1.50:8080)"),
    _app("sideemedia", "Sidee Media Player", "", "Media", "folder", "#2bb1a8",
         "Play videos from this computer (served by Sidee)",
         "", self_hosted="player"),
    _app("synology", "Synology DSM", "", "Media", "server", "#4a86e8",
         "Synology NAS file browser", _fav("synology.com"),
         needs_server=True, server_builder="lan", default_port=5000,
         server_placeholder="NAS IP (e.g. 192.168.1.10:5000)"),
    _app("truenas", "TrueNAS", "", "Media", "server", "#3aa0d8",
         "TrueNAS web interface", _fav("truenas.com"),
         needs_server=True, server_builder="lan",
         server_placeholder="TrueNAS IP or URL"),

    # --- Gaming ---
    _app("geforce", "GeForce NOW", "https://play.geforcenow.com", "Gaming",
         "game", "#76b900", "Cloud gaming by NVIDIA", _fav("nvidia.com")),
    _app("xboxcloud", "Xbox Cloud", "https://www.xbox.com/play", "Gaming",
         "game", "#107c10", "Xbox cloud gaming", _fav("xbox.com")),
    _app("retroarch", "RetroArch Web", "https://web.libretro.com", "Gaming",
         "game", "#7c5cff", "RetroArch web player", _fav("libretro.com")),
    _app("browsergames", "Browser Games", "https://www.crazygames.com",
         "Gaming", "rocket", "#f46800", "Play browser games", _fav("crazygames.com")),

    # --- Productivity ---
    _app("gdrive", "Google Drive", "https://drive.google.com", "Productivity",
         "drive", "#2a9d4b", "Your files in the cloud", _fav("drive.google.com")),
    _app("notion", "Notion", "https://www.notion.so", "Productivity", "note",
         "#8a8f98", "Notes and workspaces", _fav("notion.so")),
    _app("gcal", "Calendar", "https://calendar.google.com", "Productivity",
         "calendar", "#4285f4", "Google Calendar", _fav("calendar.google.com")),
    _app("office", "Microsoft 365", "https://www.office.com", "Productivity",
         "note", "#d83b01", "Office on the web", _fav("office.com")),
]

_BY_ID = {a["id"]: a for a in APPS}


def get(app_id: str) -> dict | None:
    return _BY_ID.get(str(app_id).lower())


def all_apps() -> list[dict]:
    return [dict(a) for a in APPS]


def by_category() -> dict[str, list[dict]]:
    out = {c: [] for c in CATEGORIES}
    for a in APPS:
        out.setdefault(a["category"], []).append(dict(a))
    return out


def search(query: str) -> list[dict]:
    q = (query or "").strip().lower()
    return [dict(a) for a in APPS
            if not q or q in a["name"].lower() or q in a["description"].lower()
            or q in a["category"].lower()]


def icon_library() -> list[dict]:
    return [{"id": k, "label": v[0], "glyph": v[1], "color": v[2]}
            for k, v in BUILTIN_ICONS.items()]


def icon_svg(icon_id: str, label: str = "") -> str:
    """Inline SVG for a built-in icon (used by the UI and as a self-contained
    data: URI on TV tiles, so an installed tile needs no running server)."""
    label_s, glyph, color = BUILTIN_ICONS.get(icon_id, BUILTIN_ICONS["globe"])
    letter = html.escape((label or label_s)[:1].upper())
    text = html.escape(glyph)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
        'viewBox="0 0 256 256">'
        f'<rect width="256" height="256" rx="52" fill="{color}"/>'
        f'<text x="128" y="150" font-size="118" text-anchor="middle" '
        f'font-family="sans-serif" fill="#ffffff">{text}</text>'
        f'<text x="128" y="232" font-size="34" text-anchor="middle" '
        f'font-family="sans-serif" fill="#ffffff" opacity="0.9">{letter}</text>'
        '</svg>'
    )


def icon_data_uri(icon_id: str, label: str = "") -> str:
    raw = icon_svg(icon_id, label).encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


def build_lan_url(server: str, default_port: int | None = None) -> str:
    """Normalise a user-entered LAN address into a full http(s) URL without
    forcing a vendor-specific path (unlike presets.build_server_url)."""
    server = (server or "").strip().rstrip("/")
    if not server:
        raise ValueError("Enter your server's LAN address.")
    if "://" not in server:
        server = "http://" + server
    url = storage.normalize_url(server)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".localhost"):
        raise ValueError("Use your server's LAN IP or URL; localhost points to the TV itself.")
    if default_port and parts.port is None and ":" not in parts.netloc:
        url = url.replace(parts.netloc, f"{parts.netloc}:{default_port}", 1)
    return url


def catalog_tile(entry: dict, server: str = "", lan_base: str = "") -> dict:
    """Build the tile dict stored in custom_apps.json for a catalog app."""
    e = dict(entry)
    url = e.get("url", "")
    builder = e.get("server_builder")
    if e.get("self_hosted") == "player":
        url = lan_base.rstrip("/") + "/player" if lan_base else "http://127.0.0.1:8080/player"
    elif builder == "jellyfin":
        if not server:
            raise ValueError("Enter your " + e["name"] + " server address.")
        url = presets.build_server_url(server)
    elif builder == "stremio":
        url = presets.build_stremio_url(server)
    elif builder == "lan":
        if not server:
            raise ValueError("Enter your " + e["name"] + " server address.")
        url = build_lan_url(server, e.get("default_port"))
    elif e.get("needs_server"):
        if not server:
            raise ValueError("Enter your " + e["name"] + " server address.")
        url = build_lan_url(server, e.get("default_port"))
    image = e.get("image") or ""
    return {
        "name": e["name"],
        "url": url,
        "image": image,
        "icon": e["icon"],
        "color": e["color"],
        "category": e["category"],
        "source": "catalog",
        "catalog_id": e["id"],
        "app_id": "cat_" + re.sub(r"[^a-z0-9_]", "_", e["id"].lower())[:28],
    }
