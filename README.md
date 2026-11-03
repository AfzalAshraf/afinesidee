<p align="center"><img src="assets/sidee-logo.png" width="180" alt="Sidee"></p>

# Sidee Enhanced

**Your TV, your apps — installed on the TV itself.**

Sidee Enhanced is a free, open-source (MIT) rework of [Sidee](https://github.com/Empi9245/Sidee).
It turns the original "tile adder" into a full custom dashboard and open app launcher that anyone
can use without coding. You can paste **any web URL**, give it a name and icon, arrange your apps
by dragging, generate a TV-friendly full-screen launcher, and — most importantly — **install each
app as a real, permanent tile on your VIDAA TV**.

A tile installed on the TV lives in the TV launcher: it keeps working even when Sidee and this
computer are switched off. The hosted `/dashboard` page is an optional alternative that shows all
your apps in one place (it needs Sidee running). You choose per app.

> **Important:** this is an independent project, not affiliated with TV manufacturers. Use it only
> with devices you own or are authorised to manage.

---

## What's new

| Phase | Feature |
| --- | --- |
| 1 | **Custom URL input** — paste any `http://` or `https://` address; only the URL *format* is validated, never the domain. Custom name, uploaded icon, or a built-in icon library. Saved to `~/.sidee/custom_apps.json`. A short trust warning is shown ("Make sure you trust this URL. It will be accessible from your TV.") but nothing is blocked. |
| 1 | **Expanded catalog** — 35+ one-click apps in categories: Streaming, Music, Utilities, Media/NAS, Gaming, Productivity, plus the original Featured presets. Searchable. |
| 2 | **Drag-and-drop tiles** — reorder, edit (name/URL/icon), delete. Order is persisted and synced. |
| 2 | **Import / Export** — your whole setup (tiles, URLs, icons, dashboard layout, colours, widgets) in one JSON file. Merge or replace. |
| 3 | **Custom dashboard generator** — a full-screen, dark, 1080p/4K-ready HTML page at `http://<computer-ip>:<port>/dashboard`. Large tiles, TV-remote navigation (arrows + Enter), clock/date/weather widgets, customisable accent colours. Installable as a single launcher tile. |
| 4 | **Redesigned console** — sidebar (My Apps, App Catalog, Dashboard Builder, Local Media, Settings, Connect TV), card layout, search, tooltips, help text, working on desktop and mobile. The QR-code phone feature is kept. |
| 4 | **Onboarding wizard** — first launch shows 3 steps: Find your TV → Pair with PIN → Add your first apps. |
| 5 | **Local media** — scan a folder for MP4/MKV/WebM, stream it over the built-in server with an HTML5 player and automatic `.srt` subtitles (converted to WebVTT). |
| 6 | **Auto-start / Keep Alive** — launch at login (Windows Startup folder / macOS LaunchAgent) and `--keep-alive` supervision that restarts the server after a crash. |
| 6 | **Preview on TV** — temporarily open the dashboard on the TV without installing anything. |

Everything runs locally. There is **no telemetry, account, or cloud service**. TV discovery and
control stay on your LAN over **MQTT/TLS port 36669** with **mandatory PIN pairing**, and dashboard
access is protected by the existing **private access key** printed at startup.

### The "install apps inside the TV, not only on the server" fix

The original Sidee only offered a fixed list of curated presets. Sidee Enhanced adds two distinct
ways to use an app:

1. **Install on TV** (per app, primary): Sidee sends the same `app_install` MQTT action used by the
   original presets via `client.add_tile()`. The TV registers a launcher tile pointing straight at
   the app's own URL. Nothing depends on Sidee's web server afterwards — the tile persists on the
   TV across restarts. Icons default to a **self-contained SVG data URI**, so even the icon needs no
   running server. **This works for custom URLs as well as catalog apps.**
2. **Hosted dashboard** (optional): one tile that opens the locally served `/dashboard` page. This
   requires Sidee to be running, because the page is served from this computer.

The redesigned console makes the distinction explicit and offers "Install on TV", "Install all on
TV", and "Install dashboard as one tile" as separate actions.

---

## Requirements

- Windows 10/11, or macOS 15+ (Apple Silicon or Intel)
- A compatible VIDAA TV and a computer on the same home Wi-Fi/Ethernet network
- Internet access for the initial Windows setup and any online apps you open on the TV

Compatibility varies by TV model/firmware; see [compatibility notes](docs/toshiba-compatibility.md).
Custom URLs are opened by the TV's own browser — playback/compatibility depends on that browser.

---

## Get started

### Windows

1. [Download Sidee for Windows](https://github.com/Empi9245/Sidee/releases/download/v0.1.4.2/sidee-windows.zip)
   (or build `dist/sidee-windows.zip` with `python tools/build_windows_release.py`) and extract it.
2. Double-click **`start-windows.bat`** (not `start-windows.ps1`). The redesigned console opens in
   your browser. The `.ps1` is an unsigned setup script — running it directly makes Windows report
   *"is not digitally signed"*. The `.bat` applies `-ExecutionPolicy Bypass` for that one launch;
   see [Troubleshooting](#troubleshooting) if you hit that error.
3. Follow the onboarding wizard: **Find TV** → **Request code / enter the 4-digit PIN** → **Add your
   first apps**.

On first launch, Sidee downloads a private, version-pinned Python runtime and its connection
dependency from official sources, verifying SHA-256 checksums. You do **not** need to install
Python, use a terminal, or grant admin rights. Later launches reuse the downloaded runtime. Keep the
launcher window open while using the console. If the browser doesn't open automatically, use the full
link printed in the launcher (it includes the private access key). Allow local-network access if
Windows asks.

### macOS

The macOS download bundles Sidee.app and its runtime — no Python install or Terminal commands.

1. Get the DMG for your Mac from [Releases](https://github.com/Empi9245/Sidee/releases) or a
   successful [build workflow](https://github.com/Empi9245/Sidee/actions/workflows/build.yml)
   (`arm64` for Apple Silicon, `x64` for Intel).
2. Open the DMG, drag Sidee.app to Applications, launch it, then choose **Open dashboard**.

The current macOS builds are not signed/notarized; macOS may block them. If you trust the download,
follow [Apple's instructions](https://support.apple.com/en-us/102445) for opening an unverified
app, and grant Local Network access. Sidee's control window must stay open while you use the console.

> Both launchers now bundle the redesigned console (`core/enhanced.html`), the TV dashboard template
> (`core/tv_dashboard.html`) and the new storage/catalog/media modules, so no extra files are needed.

---

## Using the redesigned console

See [docs/ui-guide.md](docs/ui-guide.md) for a screen-by-screen description (and ASCII mockups) of
the new UI. In short:

- **My Apps** — card grid of your tiles. Drag to reorder; each card has **Install on TV**, Open,
  Edit and Delete. The drag order is saved to `custom_apps.json`.
- **App Catalog** — categorised, searchable one-click apps. **+ Add** puts one in My Apps;
  **Add & Install** installs it on the TV immediately. Apps that need your own server (Jellyfin,
  Home Assistant, NAS, …) show a field for its LAN address.
- **Dashboard Builder** — set the title, accent colours, theme, columns and clock/date/weather
  widgets; **Open dashboard**, **Preview on TV**, or **Install dashboard as one tile**. The full URL
  is displayed so you can copy it or open it directly on the TV browser.
- **Local Media** — point at a folder, **Scan folder**, then **Open player**. Matching `.srt` files
  become subtitles automatically.
- **Settings** — export/import the whole setup, enable launch-at-login and Keep Alive, set the
  preferred port, and read the privacy notes.
- **Connect TV / Setup** — the 3-step onboarding wizard, manual TV IP check, and the **phone QR
  code**. The original three-step page is still reachable at `/setup`.

**Custom URL**: click **+ Add app** (or **+ Custom URL**), paste e.g.
`http://192.168.1.50:8080` or `https://app.plex.tv`, choose a name, category and icon (built-in
library, uploaded image, or an https icon URL), then Save. The trust warning is shown but the URL is
never blocked. Click **Install on TV** on the new tile to make it a permanent launcher tile.

---

## Persistent configuration

All user data lives in `~/.sidee/` (mode 600 on Unix):

| File | Contents |
| --- | --- |
| `session.json` | existing pairing tokens (unchanged) |
| `custom_apps.json` | your tiles / custom URLs and their order — [sample](examples/custom_apps.json) |
| `dashboard_config.json` | layout, colours, widgets and options — [sample](examples/dashboard_config.json) |
| `icons/` | user-uploaded icon images |
| `media/` | optional symlink to your local media folder |

`SIDEE_STATE_DIR` overrides the profile directory (used by the test suite). The generated HTML
dashboard template is [`core/tv_dashboard.html`](core/tv_dashboard.html).

### Configuration file format

```json
{
  "format": "sidee-enhanced/custom-apps",
  "version": 1,
  "apps": [
    {
      "id": "a1b2c3d4e5",
      "name": "My Home Server",
      "url": "http://192.168.1.50:8080",
      "image": "",
      "icon": "server",
      "color": "#3d7bfd",
      "category": "Custom",
      "app_id": "app_f6g7h8i9j0",
      "source": "custom",
      "installed": false
    }
  ]
}
```

Exports use `format: "sidee-enhanced/config"` and additionally contain `dashboard_config` and
base64 `icons`. See the [examples](examples/) folder.

---

## How it works

Sidee uses the TV's local control interface for SSDP discovery, PIN-authorised pairing, and
launcher management (MQTT/TLS on port 36669). It does not install native system software or modify
the TV OS. The built-in web server (default port **8080**, configurable with `--port` or Settings)
serves the console, the generated TV dashboard, uploaded icons and local media (with HTTP Range
support for video seeking).

The redesigned console is a single self-contained HTML file with no external scripts, fonts, CDNs or
analytics; the TV dashboard is likewise generated locally from a checked-in template.

## Privacy and security

- No telemetry: discovery, pairing and TV control are local; no account is required.
- Consent-based pairing: you must confirm the 4-digit PIN shown on the TV.
- Local credentials: saved tokens stay in `~/.sidee/session.json`.
- Protected dashboard: every API/page requires the private key in the URL/QR link. Keep links private.
- Arbitrary URLs are allowed but only `http`/`https` shapes are accepted (active schemes such as
  `javascript:`/`file:`/`data:` are refused). A trust warning is shown — only add addresses you trust.
- The TV dashboard's "weather" widget is a text field you set yourself; it makes **no** cloud calls.

---

## Development

With Python 3.9+ installed:

```bash
python -m pip install -r requirements.txt
python sidee.py                 # opens the redesigned console on port 8080
python sidee.py --port 9000    # choose a port
python sidee.py --headless     # no browser
python sidee.py --keep-alive   # supervise + restart the server on a crash
python sidee.py --self-test    # verify bundled resources/runtime without a GUI
```

Command-line interface (all TV actions still require a paired TV):

```bash
python sidee.py discover
python sidee.py pair TV_IP
python sidee.py install PRESET_ID              # original curated presets
python sidee.py list                           # tiles currently on the TV
python sidee.py apps                           # your saved custom apps
python sidee.py add https://app.plex.tv --name Plex
python sidee.py install-url http://192.168.1.50:8080 --name "My Server"
python sidee.py install-app APP_ID             # install a saved app as a TV tile
python sidee.py export setup.json
python sidee.py import setup.json --merge
```

`install-url` is the CLI proof of the new behaviour: it adds an arbitrary URL and immediately
registers it as a permanent TV tile.

Tests:

```bash
python -m unittest discover -s tests
node --test tests/test_dashboard_selection.js
python tools/smoke_test.py --source
python tools/public_release_guard.py --source-root .
```

Packaging: see [macOS build notes](docs/macos-build.md) and the
[GitHub Actions workflow](.github/workflows/build.yml).

---

## Troubleshooting

### "start-windows.ps1 is not digitally signed" / `UnauthorizedAccess`

This happens when you run **`start-windows.ps1` directly** in PowerShell. That file is an
unsigned local setup script, and many Windows machines use an `AllSigned` / `RemoteSigned`
execution policy, so PowerShell refuses to load it:

```
& : File C:\My Apps\Afinesidee\start-windows.ps1 cannot be loaded.
The file ... is not digitally signed. ... FullyQualifiedErrorId : UnauthorizedAccess
```

**Use the batch launcher instead** — it already applies the bypass for that one process:

- Double-click **`start-windows.bat`** in File Explorer, **or**
- From your existing PowerShell prompt: `& "C:\My Apps\Afinesidee\start-windows.bat"`, **or**
- Explicitly:
  ```powershell
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\My Apps\Afinesidee\start-windows.ps1"
  ```

Paths containing spaces (like `C:\My Apps\Afinesidee`) are fine — the launcher quotes them.
Do **not** run the `.ps1` on its own. Other options:

- If you downloaded a ZIP, Windows may have marked the files as coming from the Internet.
  `Unblock-File` removes that mark (it is a command, so it is not blocked by the script policy):
  ```powershell
  Get-ChildItem "C:\My Apps\Afinesidee" -Recurse -File | Unblock-File
  ```
- To allow your own local scripts permanently (no admin rights needed):
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```
  Only do this if you understand the change; `-ExecutionPolicy Bypass` via the `.bat` is safer
  because it affects just that one launch.
- If your organisation enforces the policy through Group Policy, ask your administrator, or
  install Python 3.9+ and run `python sidee.py` (see [Development](#development)).

See [docs/windows-launch.md](docs/windows-launch.md) for a full walkthrough.

### Find TV / network

If **Find TV** cannot locate your TV, check that both devices share the same network and that a VPN,
guest Wi-Fi, or firewall is not blocking local discovery. The manual IP option checks that the
destination responds as a compatible TV and that port 36669 is reachable; it never bypasses PIN
authorization. Some TVs advertise themselves rather than replying directly to discovery — keep the
TV on and retry. For firmware-specific pairing limitations see the
[compatibility notes](docs/toshiba-compatibility.md).

On macOS, check **System Settings → Privacy & Security → Local Network** and, if needed, the
firewall permissions for Sidee. Diagnostic logs are at `~/Library/Logs/Sidee/sidee.log`.

## Why Sidee exists

Sidee began with a simple idea: people should have more freedom to use technology they already own.
Sidee Enhanced keeps that idea — open URLs, open launcher, your data on your machine. If it helps
you, please consider supporting continued development.

☕ [Support Sidee on Ko-fi](https://ko-fi.com/sidee)

## License

MIT — see [LICENSE](LICENSE). Sidee Enhanced is a derivative work of Sidee (MIT), and remains MIT.
Independent project; not affiliated with TV manufacturers.
