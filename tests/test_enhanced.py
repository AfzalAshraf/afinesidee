"""Sidee Enhanced: custom URLs, storage, catalog, media, dashboard generation
and — most importantly — installing ANY app as a permanent TV launcher tile
(the "install apps inside the TV, not only on the server" fix).

No network and no TV: MQTT calls are mocked, but the HTTP dashboard is a real
local server so the endpoints are exercised end to end.
"""
import base64
import http.client
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import autostart, catalog, media, storage, webui, client


class IsolatedState(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = folder.name
        env = patch.dict(os.environ, {"SIDEE_STATE_DIR": folder.name})
        env.start()
        self.addCleanup(env.stop)


class TestURLValidation(unittest.TestCase):
    def test_any_domain_is_allowed_shape_is_checked(self):
        self.assertEqual(storage.normalize_url("https://youtube.com"),
                         "https://youtube.com")
        self.assertEqual(storage.normalize_url("https://app.plex.tv"),
                         "https://app.plex.tv")
        self.assertEqual(storage.normalize_url("http://192.168.1.50:8080"),
                         "http://192.168.1.50:8080")
        self.assertEqual(storage.normalize_url("http://nas.home.local:5000/ui"),
                         "http://nas.home.local:5000/ui")
        # The domain is never restricted — only the shape is validated.
        self.assertEqual(storage.normalize_url("https://some.unknown.example.test/x"),
                         "https://some.unknown.example.test/x")

    def test_missing_scheme_defaults_to_http(self):
        self.assertEqual(storage.normalize_url("192.168.1.50:8080"),
                         "http://192.168.1.50:8080")
        self.assertEqual(storage.normalize_url("example.com/app"),
                         "http://example.com/app")

    def test_active_and_malformed_urls_are_rejected(self):
        for bad in ("", "javascript:alert(1)", "file:///etc/passwd",
                    "data:text/html,<h1>x", "ftp://example.com",
                    "https://", "http://host:99999/",
                    "http://user:pass@example.com", "https://a b.com",
                    "https://example.com\nX"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                storage.normalize_url(bad)

    def test_trust_warning_is_informational(self):
        self.assertIn("trust", storage.TRUST_WARNING.lower())
        self.assertIn("TV", storage.TRUST_WARNING)


class TestStorage(IsolatedState):
    def test_default_config_and_sanitizing(self):
        cfg = storage.load_config()
        self.assertEqual(cfg["port"], 8080)
        self.assertEqual(cfg["theme"], "dark")
        saved = storage.save_config({"accent": "#123456", "columns": 99,
                                     "theme": "nonsense", "show_clock": False,
                                     "unknown_key": "ignored"})
        self.assertEqual(saved["accent"], "#123456")
        self.assertEqual(saved["columns"], 8)          # clamped
        self.assertEqual(saved["theme"], "dark")       # invalid -> default
        self.assertFalse(saved["show_clock"])
        self.assertNotIn("unknown_key", saved)
        self.assertTrue((Path(self.state) / storage.CONFIG_FILE).is_file())

    def test_add_update_delete_reorder(self):
        a = storage.add_app({"name": "My Plex", "url": "https://app.plex.tv"})
        b = storage.add_app({"name": "LAN box", "url": "http://192.168.1.50:8080"})
        self.assertEqual(len(storage.load_apps()), 2)
        self.assertTrue((Path(self.state) / storage.APPS_FILE).is_file())
        self.assertRegex(a["app_id"], r"^[a-z0-9_]{1,32}$")
        storage.update_app(a["id"], {"name": "Plex!", "url": "https://plex.tv"})
        self.assertEqual(storage.get_app(a["id"])["url"], "https://plex.tv")
        ordered = storage.reorder_apps([b["id"], a["id"]])
        self.assertEqual([x["id"] for x in ordered], [b["id"], a["id"]])
        storage.delete_app(b["id"])
        self.assertEqual(len(storage.load_apps()), 1)

    def test_invalid_entries_never_crash(self):
        path = Path(self.state) / storage.APPS_FILE
        path.write_text(json.dumps({"apps": [
            {"name": "ok", "url": "https://ok.example"},
            {"name": "bad", "url": "javascript:alert(1)"},
            "not-an-object",
        ]}), encoding="utf-8")
        self.assertEqual(len(storage.load_apps()), 1)

    def test_export_import_roundtrip_and_liberal_import(self):
        storage.add_app({"name": "A", "url": "https://a.example"})
        storage.save_config({"accent": "#abcdef", "title": "Living Room"})
        exported = storage.export_config()
        self.assertEqual(exported["format"], storage.FORMAT_EXPORT)
        # Wipe and re-import.
        (Path(self.state) / storage.APPS_FILE).unlink()
        result = storage.import_config(exported)
        self.assertTrue(result["ok"] and result["apps"] == 1)
        self.assertEqual(storage.load_config()["title"], "Living Room")
        self.assertEqual(storage.load_config()["accent"], "#abcdef")
        # Liberal formats: a bare list, {apps:[...]}, and a single app.
        for obj in ([{"name": "B", "url": "https://b.example"}],
                    {"apps": [{"name": "C", "url": "https://c.example"}]},
                    {"name": "D", "url": "https://d.example"}):
            with self.subTest(kind=type(obj).__name__):
                storage.import_config(obj)
        self.assertTrue(any(x["name"] == "D" for x in storage.load_apps()))

    def test_merge_does_not_duplicate(self):
        storage.add_app({"name": "A", "url": "https://a.example"})
        storage.import_config({"apps": [
            {"name": "A", "url": "https://a.example"},
            {"name": "B", "url": "https://b.example"}]}, merge=True)
        names = [x["name"] for x in storage.load_apps()]
        self.assertEqual(names.count("A"), 1)
        self.assertIn("B", names)

    def test_icon_upload_and_traversal_blocked(self):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 40
        url = storage.save_icon("my icon.png", png)
        self.assertTrue(url.startswith("/icons/"))
        resolved = storage.read_icon(url.rsplit("/", 1)[-1])
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[1], "image/png")
        self.assertIsNone(storage.read_icon("../session.json"))
        self.assertIsNone(storage.read_icon("..%2f"))
        with self.assertRaises(ValueError):
            storage.save_icon("x.png", b"not-an-image")


class TestCatalog(unittest.TestCase):
    def test_all_requested_categories_present_and_entries_valid(self):
        grouped = catalog.by_category()
        for cat in ("Streaming", "Music", "Utilities", "Media", "Gaming",
                    "Productivity", "Featured"):
            self.assertIn(cat, grouped)
            self.assertTrue(grouped[cat])
        ids = set()
        for a in catalog.all_apps():
            self.assertTrue(a["id"] and a["name"] and a["category"])
            self.assertIn(a["icon"], catalog.BUILTIN_ICONS)
            self.assertNotIn(a["id"], ids)
            ids.add(a["id"])

    def test_search(self):
        self.assertTrue(any(a["id"] == "plex" for a in catalog.search("plex")))
        self.assertEqual(catalog.search(""), catalog.all_apps())

    def test_server_builders(self):
        jf = catalog.get("jellyfin")
        tile = catalog.catalog_tile(jf, "192.168.1.50")
        self.assertEqual(tile["url"], "http://192.168.1.50:8096/web/index.html")
        st = catalog.catalog_tile(catalog.get("stremio"), "")
        self.assertIn("stremio-vidaa-tv", st["url"])
        ha = catalog.catalog_tile(catalog.get("homeassistant"), "192.168.1.20")
        self.assertEqual(ha["url"], "http://192.168.1.20:8123")
        with self.assertRaises(ValueError):
            catalog.catalog_tile(catalog.get("jellyfin"), "")
        with self.assertRaises(ValueError):
            catalog.catalog_tile(catalog.get("homeassistant"), "localhost")

    def test_icon_library_is_self_contained(self):
        uri = catalog.icon_data_uri("play", "Plex")
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
        self.assertIn("<svg", base64.b64decode(uri.split(",", 1)[1]).decode())


class TestMedia(IsolatedState):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        (self.folder / "Movie.mp4").write_bytes(b"\x00" * 2048)
        (self.folder / "Movie.srt").write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n", encoding="utf-8")
        (self.folder / "Clip.webm").write_bytes(b"\x00" * 512)

    def test_scan_and_subtitles(self):
        media.set_root(str(self.folder))
        videos = media.scan()
        self.assertEqual(len(videos), 2)
        movie = next(v for v in videos if v["title"] == "Movie")
        self.assertTrue(movie["subtitle"])
        self.assertEqual(movie["subtitle_file"], "Movie.srt")

    def test_srt_to_vtt(self):
        vtt = media.srt_to_vtt("1\n00:00:01,000 --> 00:00:03,000\nHi\n")
        self.assertTrue(vtt.startswith("WEBVTT"))
        self.assertIn("00:00:01.000", vtt)

    def test_path_traversal_rejected(self):
        media.set_root(str(self.folder))
        self.assertIsNotNone(media.file_path("Movie.mp4"))
        for bad in ("../secret.mp4", "/etc/passwd", "..\\x", ""):
            self.assertIsNone(media.file_path(bad))

    def test_player_page_has_video_and_track(self):
        media.set_root(str(self.folder))
        page = media.player_page(media.scan(), "testkey")
        self.assertIn("<video", page)
        self.assertIn("<track", page)
        self.assertIn("/media/raw/Movie.mp4?key=testkey", page)
        self.assertIn("/media/sub/Movie.srt?key=testkey", page)


class TestInstallOnTV(IsolatedState):
    """The core fix: arbitrary URLs become permanent TV tiles via add_tile."""

    def test_custom_url_is_installed_as_a_tv_tile(self):
        app = storage.add_app({"name": "My LAN app",
                               "url": "http://192.168.1.50:8080",
                               "icon": "server"})
        tile = {"appId": app["app_id"], "name": "My LAN app",
                "url": "http://192.168.1.50:8080"}
        session = client.Session(host="192.168.1.10")
        with patch.object(client.Session, "load_or_none", return_value=session), \
             patch.object(client, "add_tile", return_value=[tile]) as add:
            result = webui.install_app(app, 8080)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "installed")
        args = add.call_args.args
        self.assertEqual(args[0].host, "192.168.1.10")
        self.assertEqual(args[2], "My LAN app")
        self.assertEqual(args[3], "http://192.168.1.50:8080")
        # No image was set: a self-contained SVG data URI is used, so the tile
        # needs no running server to show its icon.
        self.assertTrue(args[4].startswith("data:image/svg+xml;base64,"))
        self.assertTrue(storage.get_app(app["id"])["installed"])

    def test_public_https_url_is_also_installable(self):
        app = storage.add_app({"name": "Plex", "url": "https://app.plex.tv",
                               "image": "https://app.plex.tv/favicon.ico"})
        tile = {"appId": app["app_id"], "url": app["url"]}
        with patch.object(client.Session, "load_or_none",
                          return_value=client.Session(host="10.0.0.5")), \
             patch.object(client, "add_tile", return_value=[tile]) as add:
            result = webui.install_app(app, 8080)
        self.assertTrue(result["ok"])
        self.assertEqual(add.call_args.args[4], "https://app.plex.tv/favicon.ico")

    def test_unconfirmed_tile_is_reported_not_failed(self):
        app = storage.add_app({"name": "X", "url": "https://x.example"})
        with patch.object(client.Session, "load_or_none",
                          return_value=client.Session(host="10.0.0.5")), \
             patch.object(client, "add_tile", return_value=[]):
            result = webui.install_app(app, 8080)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("Check Home", result["message"])
        self.assertFalse(storage.get_app(app["id"])["installed"])

    def test_no_pairing_raises_autherror(self):
        app = storage.add_app({"name": "X", "url": "https://x.example"})
        with patch.object(client.Session, "load_or_none", return_value=None):
            with self.assertRaises(client.AuthError) as error:
                webui.install_app(app, 8080)
        self.assertEqual(error.exception.kind, "none")

    def test_install_all_loops_over_every_app(self):
        for i in range(3):
            storage.add_app({"name": f"App{i}", "url": f"https://app{i}.example"})
        with patch.object(client.Session, "load_or_none",
                          return_value=client.Session(host="10.0.0.5")), \
             patch.object(webui, "install_app",
                          return_value={"ok": True}) as install:
            result = webui.install_all_apps(8080)
        self.assertEqual(install.call_count, 3)
        self.assertEqual(result["installed"], 3)
        self.assertEqual(result["total"], 3)

    def test_dashboard_tile_and_tv_preview(self):
        with patch.object(client.Session, "load_or_none",
                          return_value=client.Session(host="10.0.0.5")), \
             patch.object(client, "add_tile", return_value=[]) as add, \
             patch.object(client, "launch_tile") as launch:
            tile_result = webui.install_dashboard_tile(8080)
            preview = webui.preview_on_tv(8080)
        self.assertIn("/dashboard?key=", add.call_args.args[3])
        self.assertEqual(tile_result["status"], "unconfirmed")
        self.assertTrue(preview["ok"])
        self.assertIn("/dashboard?key=", launch.call_args.args[3])


class TestAutostart(IsolatedState):
    def test_status_shape(self):
        status = autostart.status()
        self.assertIn("autostart", status)
        self.assertIn("keep_alive", status)
        self.assertIn("platform", status)

    def test_keep_alive_setting_persists(self):
        self.assertFalse(autostart.set_keep_alive(True)["keep_alive"] is False)
        self.assertTrue(storage.load_config()["keep_alive"])
        autostart.set_keep_alive(False)

    def test_windows_and_macos_helpers(self):
        with patch.object(autostart, "platform", return_value="windows"), \
             patch.object(autostart, "_startup_dir",
                          return_value=Path(self.state) / "Startup"), \
             patch.object(autostart.Path, "home", return_value=Path(self.state)):
            result = autostart.set_autostart(True)
            self.assertTrue(result["autostart"])
            self.assertIn("WScript.Shell",
                          (Path(self.state) / "Startup" / autostart.STARTUP_NAME).read_text())
            self.assertFalse(autostart.set_autostart(False)["autostart"])
        with patch.object(autostart, "platform", return_value="macos"), \
             patch.object(autostart, "_launchagent_path",
                          return_value=Path(self.state) / "agent.plist"):
            result = autostart.set_autostart(True, command=["/bin/true"])
            self.assertTrue(result["autostart"])
            import plistlib
            self.assertEqual(plistlib.loads(
                (Path(self.state) / "agent.plist").read_bytes())["ProgramArguments"],
                ["/bin/true"])


class TestHTTPEndpoints(IsolatedState):
    """Exercise the real local dashboard server over HTTP."""

    def setUp(self):
        super().setUp()
        self.dashboard = webui.Dashboard(port=0, headless=True)
        self.addCleanup(self.dashboard.close)
        self.dashboard.start()
        self.port = self.dashboard.port
        self.key = webui.ACCESS_KEY

    def request(self, path, method="GET", body=None, headers=None, with_key=True):
        sep = "&" if "?" in path else "?"
        target = path + (sep + "key=" + self.key if with_key else "")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, target, body=body,
                         headers={"Content-Type": "application/json", **(headers or {})})
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            conn.close()

    def post(self, path, data):
        return self.request(path, "POST", json.dumps(data))

    def test_root_is_the_redesigned_console_and_classic_still_exists(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Find TV", body)          # smoke-test contract
        self.assertIn(b"Use your phone", body)
        self.assertIn(b"My Apps", body)
        self.assertIn(b"Install on TV", body)
        status, _, body = self.request("/setup")
        self.assertEqual(status, 200)
        self.assertIn(b"Find TV", body)

    def test_access_key_is_required(self):
        status, _, _ = self.request("/api/state", with_key=False)
        self.assertEqual(status, 403)
        status, _, _ = self.request("/api/status", with_key=False)
        self.assertEqual(status, 403)

    def test_state_payload_is_complete(self):
        status, _, body = self.request("/api/state")
        state = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(state["ok"])
        self.assertIn("Streaming", state["catalog"])
        self.assertIn("play", state["icons"])
        self.assertIn("trust", state["trust_warning"].lower())
        self.assertIn("/dashboard?key=", state["dashboard_url"])

    def test_custom_url_add_edit_reorder_delete(self):
        r = json.loads(self.post("/api/apps/add", {
            "name": "My Server", "url": "http://192.168.1.50:8080",
            "icon": "server"})[2])
        self.assertTrue(r["ok"])
        self.assertIn("trust", r["warning"].lower())
        app_id = r["app"]["id"]
        r = json.loads(self.post("/api/apps/add", {"catalog_id": "youtube"})[2])
        self.assertTrue(r["ok"])
        self.assertEqual(r["app"]["url"], "https://www.youtube.com")
        r = json.loads(self.post("/api/apps/add", {"catalog_id": "jellyfin",
                                                   "server": "192.168.1.50"})[2])
        self.assertTrue(r["ok"])
        self.assertEqual(r["app"]["url"], "http://192.168.1.50:8096/web/index.html")
        ids = [a["id"] for a in r["apps"]]
        r = json.loads(self.post("/api/apps/reorder", {"ids": list(reversed(ids))})[2])
        self.assertEqual([a["id"] for a in r["apps"]], list(reversed(ids)))
        r = json.loads(self.post("/api/apps/update",
                                 {"id": app_id, "name": "Renamed"})[2])
        self.assertTrue(any(a["name"] == "Renamed" for a in r["apps"]))
        r = json.loads(self.post("/api/apps/delete", {"id": app_id})[2])
        self.assertFalse(any(a["id"] == app_id for a in r["apps"]))

    def test_bad_url_is_rejected_without_blocking_domains(self):
        r = json.loads(self.post("/api/apps/add", {
            "name": "Bad", "url": "javascript:alert(1)"})[2])
        self.assertFalse(r["ok"])
        r = json.loads(self.post("/api/apps/add", {
            "name": "Odd but fine", "url": "https://totally.unknown.example/x"})[2])
        self.assertTrue(r["ok"])

    def test_install_endpoint_uses_mqtt_add_tile(self):
        r = json.loads(self.post("/api/apps/add", {
            "name": "LAN", "url": "http://192.168.1.50:8080"})[2])
        app = r["app"]
        tile = {"appId": app["app_id"], "url": app["url"]}
        with patch.object(client.Session, "load_or_none",
                          return_value=client.Session(host="192.168.1.10")), \
             patch.object(client, "add_tile", return_value=[tile]) as add:
            status, _, body = self.post("/api/apps/install", {"id": app["id"]})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertTrue(result["ok"])
        self.assertEqual(add.call_args.args[3], "http://192.168.1.50:8080")

    def test_generated_tv_dashboard_contains_apps_and_config(self):
        self.post("/api/apps/add", {"name": "Plex", "url": "https://app.plex.tv"})
        self.post("/api/dashboard/config", {"accent": "#123456", "title": "Den",
                                            "show_weather": True})
        status, _, body = self.request("/dashboard")
        self.assertEqual(status, 200)
        self.assertIn(b"Plex", body)
        self.assertIn(b'"accent": "#123456"', body)
        self.assertIn(b"Den", body)
        self.assertIn(b"ArrowRight", body)       # remote navigation
        self.assertNotIn(b"__SIDEE_DATA__", body)  # placeholder was generated

    def test_import_export_and_icon_upload(self):
        self.post("/api/apps/add", {"name": "A", "url": "https://a.example"})
        status, _, body = self.request("/api/config/export")
        exported = json.loads(body)
        self.assertEqual(exported["format"], storage.FORMAT_EXPORT)
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 30
        r = json.loads(self.post("/api/icon/upload", {
            "name": "icon.png", "data": base64.b64encode(png).decode()})[2])
        self.assertTrue(r["ok"])
        status, _, icon = self.request(r["image"], with_key=False)  # public asset
        self.assertEqual(status, 200)
        self.assertEqual(icon, png)
        r = json.loads(self.post("/api/config/import", {"config": exported})[2])
        self.assertTrue(r["ok"] and r["apps"] == 1)

    def test_media_scan_player_and_range_request(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / "Vid.mp4").write_bytes(b"\x00" * 3000)
        (root / "Vid.srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nHi\n", encoding="utf-8")
        r = json.loads(self.post("/api/media/scan", {"path": str(root)})[2])
        self.assertTrue(r["ok"] and len(r["videos"]) == 1)
        status, _, body = self.request("/player")
        self.assertEqual(status, 200)
        self.assertIn(b"<video", body)
        status, headers, body = self.request(
            "/media/raw/Vid.mp4", headers={"Range": "bytes=100-199"})
        self.assertEqual(status, 206)
        self.assertEqual(len(body), 100)
        self.assertEqual(headers.get("Content-Range"), "bytes 100-199/3000")
        status, _, body = self.request("/media/sub/Vid.srt")
        self.assertEqual(status, 200)
        self.assertIn(b"WEBVTT", body)
        self.assertIn(b"00:00:01.000", body)
        status, _, _ = self.request("/media/raw/../secret.mp4")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
