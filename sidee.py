#!/usr/bin/env python3
"""Sidee Enhanced: add ANY web app as a permanent tile to the VIDAA launcher.

With no arguments, start the local web console (click and you're done).
The redesigned console is at "/", the generated TV dashboard at "/dashboard",
and the original three-step page is still available at "/setup".

CLI commands: discover | pair <host> | refresh | install <preset> |
list | launch <preset> | apps | add <url> | install-url <url> |
install-app <id> | export [file] | import <file>
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from core import client, presets, webui, native_session
from core import storage, catalog, autostart


def cmd_cli(a) -> int:
    if a.cmd == "native":
        try:
            return 0 if native_session.install(a.target, api_base=a.api, gate_key=a.key) else 1
        except (ValueError, OSError, client.AuthError, native_session.native_api.ApiError) as error:
            print(str(error))
            return 1
    if a.cmd == "discover":
        for t in client.discover():
            print(f"  {t.host}  {t.friendly_name}  vidaa={t.is_vidaa}")
        return 0
    if a.cmd == "pair":
        s = client.pair(a.host, lambda: input("PIN shown on the TV: "))
        print(f"paired with {s.host}")
        return 0
    if a.cmd == "refresh":
        client.refresh(client.Session.load())
        print("tokens refreshed")
        return 0
    if a.cmd == "list":
        apps = client.list_tiles(client.Session.load())
        for x in apps:
            print(f"  {x.get('appId')}  {x.get('name')}  "
                  f"{str(x.get('url'))[:60]}")
        return 0
    if a.cmd == "apps":
        apps = storage.load_apps()
        if not apps:
            print("No apps configured. Use the dashboard or 'add <url>'.")
        for x in apps:
            print(f"  {x['id']}  {'TV' if x['installed'] else '--'}  "
                  f"{x['name']:<24} {x['url']}")
        return 0
    if a.cmd == "add":
        try:
            app = storage.add_app({"name": a.name or a.url, "url": a.url,
                                   "icon": "globe", "source": "custom"})
        except (ValueError, OSError) as error:
            print(str(error))
            return 2
        print(f"added {app['name']} ({app['id']}) -> {app['url']}")
        print(storage.TRUST_WARNING)
        return 0
    if a.cmd == "install-url":
        try:
            app = storage.add_app({"name": a.name or a.url, "url": a.url,
                                   "icon": a.icon, "source": "custom"})
            result = webui.install_app(app, webui._PORT)
        except (ValueError, OSError, client.AuthError) as error:
            print(str(error))
            return 2
        print(result.get("message") or result.get("error") or "done")
        return 0 if result.get("ok") else 1
    if a.cmd == "install-app":
        app = storage.get_app(a.app_id)
        if not app:
            print("unknown app id (try 'apps')")
            return 2
        try:
            result = webui.install_app(app, webui._PORT)
        except client.AuthError as error:
            print(str(error))
            return 2
        print(result.get("message") or "done")
        return 0 if result.get("ok") else 1
    if a.cmd == "export":
        data = json.dumps(storage.export_config(), indent=2, ensure_ascii=False)
        if a.file:
            with open(a.file, "w", encoding="utf-8") as f:
                f.write(data)
            print(f"exported to {a.file}")
        else:
            print(data)
        return 0
    if a.cmd == "import":
        try:
            with open(a.file, encoding="utf-8") as f:
                result = storage.import_config(json.load(f), merge=a.merge)
        except (OSError, ValueError) as error:
            print(str(error))
            return 2
        print(f"imported {result['apps']} apps and {result['icons']} icons")
        return 0
    if a.cmd == "install":
        p = presets.get(a.preset)
        if not p:
            print(f"unknown preset: {a.preset} "
                  f"(available: {', '.join(sorted(presets.PRESETS))})")
            return 2
        if p.get("needs_server"):
            if not getattr(a, "server", None):
                print(f"{p['name']} requires your server address: "
                      f"--server YOUR_SERVER_IP:8096")
                return 2
            p = dict(p)
            try:
                p["url"] = presets.build_server_url(a.server)
            except ValueError as error:
                print(str(error))
                return 2
        elif p.get("server_builder") == "stremio":
            p = dict(p)
            try:
                p["url"] = presets.build_stremio_url(
                    getattr(a, "server", "") or "")
            except ValueError as error:
                print(str(error))
                return 2
        s = client.Session.load()
        apps = client.add_tile(s, p["app_id"], p["name"], p["url"], p["image"])
        ok = any(client.tile_matches_request(x, p["app_id"], p["url"]) for x in apps)
        print(f"{'REGISTERED' if ok else 'NOT confirmed by the TV'}: "
              f"{p['name']} ({p['app_id']}) -> {p['url']}")
        return 0 if ok else 1
    if a.cmd == "launch":
        p = presets.get(a.preset)
        if not p:
            print("unknown preset")
            return 2
        client.launch_tile(client.Session.load(), p["app_id"], p["name"],
                           p["url"])
        print("launched")
        return 0
    return 2


def main() -> int:
    p = argparse.ArgumentParser(prog="sidee", description=__doc__)
    p.add_argument("--headless", action="store_true",
                   help="run the dashboard without opening a browser")
    p.add_argument("--port", type=int, default=None,
                   help="dashboard port (0 selects a free port; default 8080)")
    p.add_argument("--keep-alive", action="store_true",
                   help="supervise the server and restart it if it crashes")
    p.add_argument("--self-test", action="store_true",
                   help="check bundled imports, resources, TLS and Tcl without a GUI")
    sub = p.add_subparsers(dest="cmd")
    native = sub.add_parser("native", help="install through the native service (preview)")
    native.add_argument("target", help="catalog id or self-contained HTML file")
    native.add_argument("--api", help="HTTPS service URL; HTTP only on loopback for tests")
    native.add_argument("--key", help="activation key (not saved)")
    sub.add_parser("discover")
    pr = sub.add_parser("pair"); pr.add_argument("host")
    sub.add_parser("refresh")
    ins = sub.add_parser("install"); ins.add_argument("preset")
    ins.add_argument("--server", help="server address (for Jellyfin or Stremio)")
    sub.add_parser("list")
    la = sub.add_parser("launch"); la.add_argument("preset")
    sub.add_parser("apps", help="list configured custom apps")
    add = sub.add_parser("add", help="add a custom URL (any domain)")
    add.add_argument("url"); add.add_argument("--name", default="")
    iu = sub.add_parser("install-url", help="add a URL and install it as a TV tile")
    iu.add_argument("url"); iu.add_argument("--name", default="")
    iu.add_argument("--icon", default="globe")
    ia = sub.add_parser("install-app", help="install a saved app as a TV tile")
    ia.add_argument("app_id")
    ex = sub.add_parser("export", help="export the full setup as JSON")
    ex.add_argument("file", nargs="?")
    im = sub.add_parser("import", help="import a setup JSON file")
    im.add_argument("file"); im.add_argument("--merge", action="store_true")
    a = p.parse_args()

    if a.port is not None and not 0 <= a.port <= 65535:
        p.error("--port must be between 0 and 65535")
    if a.self_test:
        return self_test()

    if a.cmd is None:
        headless = a.headless or os.environ.get("SIDEE_CI") == "1"
        if a.keep_alive:
            command = [sys.executable, os.path.abspath(__file__)]
            if a.port is not None:
                command += ["--port", str(a.port)]
            command.append("--headless")
            return autostart.supervise(command)
        if not headless and a.port is None:
            webui.serve()
        else:
            webui.serve(open_browser=not headless, port=a.port, headless=headless)
        return 0
    return cmd_cli(a)


def self_test() -> int:
    """Validate the shipped runtime without connecting to a TV or opening a UI."""
    from core import platform_support
    from core.phone import qr_image
    import ssl

    root = platform_support.resource_root()
    for name in ("core/dashboard.html", "core/enhanced.html",
                 "core/tv_dashboard.html", "core/tv-client.bundle",
                 "assets/sidee-logo.png", "assets/nuvio-wordmark.png",
                 "assets/jellyfin.png"):
        if not (root / name).is_file():
            raise FileNotFoundError(f"A required Sidee resource is missing: {name}")
    # Constructor loads the shipped certificate into OpenSSL and immediately
    # deletes its temporary PEM files. It does not open a network connection.
    connection = client.MqttSession("127.0.0.1", "sidee-self-test", 1)
    connection.stop()
    assert ssl.OPENSSL_VERSION
    assert qr_image("http://127.0.0.1/").startswith("data:image/svg+xml;base64,")
    # New modules import cleanly (also verifies no missing stdlib dependency).
    assert catalog.APPS and storage.TRUST_WARNING
    if sys.platform == "darwin":
        import tkinter
        assert tkinter.Tcl().eval("info patchlevel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
