# Sidee Enhanced — UI guide

This document describes the redesigned dashboard. The console is a single self-contained HTML file
(`core/enhanced.html`) with no external assets, so it works offline on desktop and mobile. Below are
text "screenshots" (layout mockups) for each view.

- **Admin console** → `http://<computer-ip>:8080/?key=<private-key>` (path `/`)
- **TV dashboard** → `http://<computer-ip>:8080/dashboard?key=<private-key>`
- **Classic page** → `http://<computer-ip>:8080/setup?key=<private-key>`

---

## 1. Overall shell (desktop)

Dark theme (`#0b0d12`) with a yellow `--accent` and a violet secondary glow. A fixed left sidebar
holds navigation; a sticky top bar holds the pairing status, a catalog search field, and the three
primary actions.

```
┌──────────────────────┬────────────────────────────────────────────────────────────────┐
│ ▢ Sidee Enhanced     │ ● TV paired · 192.168.1.42        🔍 Search apps…             │
│   YOUR TV, YOUR APPS │                    📱 Use your phone  ▶ Preview on TV  + Add app│
│                      ├────────────────────────────────────────────────────────────────┤
│ 🏠 My Apps  ◀ active │                                                                │
│ 🧩 App Catalog       │   YOUR LAUNCHER                                                │
│ 🖥 Dashboard Builder │   My Apps                        [Install all on TV] [+ Custom URL]│
│ 🎬 Local Media       │   Everything here can be added to your hosted dashboard or …    │
│ ⚙ Settings           │                                                                │
│ ───────────────────  │   ┌──────────────────────────────────────────────────────┐   │
│ 📺 Connect TV/Setup  │   │ 📌 Install on TV = works without this computer.      │   │
│                      │   │    "Install on TV" registers a launcher tile …      │   │
│ Local only · MQTT/TLS│   └──────────────────────────────────────────────────────┘   │
│ PIN pairing · v1.0…  │   0 apps   0 installed on TV   ↕ Drag tiles to reorder         │
│ classic · support ☕ │   ┌───────────┐ ┌───────────┐ ┌───────────┐                   │
│                      │   │ ▶ Plex    │ │ 🌐 LAN box│ │ 🎵 Spotify│                   │
│                      │   │ app.plex… │ │ 192.168…  │ │ open.spot…│                   │
│                      │   │ ✓ on TV ⠿ │ │ not inst ⠿│ │ not inst ⠿│                   │
│                      │   │ [📲Install]│ │ [📲Install]│ │ [📲Install]│                  │
│                      │   │ [Open][Edit][🗑]                                      │   │
│                      │   └───────────┘ └───────────┘ └───────────┘                   │
└──────────────────────┴────────────────────────────────────────────────────────────────┘
```

On phones (≤860px) the sidebar collapses into a horizontal, wrapping row of buttons above the
content; the tile grid becomes a single column and the top bar stacks.

## 2. My Apps

Card-based tiles. Each card shows the icon (built-in emoji/SVG, uploaded image, or an https icon),
name, truncated URL, category chip, an "on TV / not installed" pill and a drag grip. Actions:
**📲 Install on TV** (primary), **Open ↗**, **Edit**, **🗑 Delete**. Dragging a card onto another
reorders them via `POST /api/apps/reorder`; the order is written to `custom_apps.json` immediately.
Tooltips (`data-tip`) explain the bulk actions; help text below the grid explains where data is saved.

## 3. Add / Edit modal (Custom URL)

```
┌───────────────────────────────────────────────────────┐
│ Add a custom app                                   ✕  │
│ Paste any web address — any domain is allowed.         │
│ ┌───────────────────────────────────────────────────┐ │
│ │ ⚠️ Make sure you trust this URL. It will be        │ │
│ │    accessible from your TV.                       │ │
│ └───────────────────────────────────────────────────┘ │
│ Name [ My Plex          ]  Category [ Streaming ▾ ]   │
│ URL  [ https://app.plex.tv                          ]  │
│ Icon — pick from the built-in library                  │
│  [▶][🎬][🎵][📺][☁️][🗄️][🏠][📊][🛡️][⚡][⛅][🎮] …       │
│ Or upload an image [ Choose file ]  Or https icon URL  │
│ [ Use built-in icon ]                    🌐 Globe      │
│                              [ Cancel ] [ Save app ]  │
└───────────────────────────────────────────────────────┘
```

Only the URL *shape* is validated (http/https, valid host, no embedded credentials, no active
schemes). Domains are never restricted. The trust warning is informational, never a block.

## 4. App Catalog

Grouped by category (Featured, Streaming, Music, Utilities, Media, Gaming, Productivity). The top-bar
search filters names, descriptions and categories live. Cards show a coloured icon, name,
description, an optional **server address** field for self-hosted apps (Jellyfin, Emby, Home
Assistant, Grafana, Pi-hole, Synology DSM, TrueNAS, local media server), and **+ Add** /
**Add & Install** buttons.

```
  ⭐ FEATURED ────────────────────────────────────────────────
  ┌────────────┐ ┌────────────┐ ┌──────────────────────────┐
  │ ▶ Nuvio    │ │ ▶ Stremio  │ │ 🎬 Jellyfin              │
  │ Browse…    │ │ Full Stre… │ │ Your media from …        │
  │            │ │ [server…]  │ │ [ Your server's IP ]     │
  │ [+Add][A&I]│ │ [+Add][A&I]│ │ [+Add] [Add & Install]   │
  └────────────┘ └────────────┘ └──────────────────────────┘
  🎬 STREAMING ───────────────────────────────────────────────
   Plex · Emby · YouTube · Netflix · Disney+ · Twitch · Prime Video
```

## 5. Dashboard Builder

Shows the copyable full URL of the generated TV page, plus **Open dashboard ↗**, **Install dashboard
as one tile** and **▶ Preview on TV**. Appearance controls: title, theme (Dark / Midnight / Light),
columns (2–8), tile style, two accent-colour swatch rows. Widget toggles: Clock, Date, Weather
widget (with a free-text field), Tile labels. All settings persist to `dashboard_config.json` and are
applied to the generated HTML instantly.

## 6. Generated TV dashboard (`/dashboard`)

Full-screen, dark, 1080p/4K-ready. A header shows the title, live clock, date and optional weather
widget. Below it a responsive CSS grid of large 16:10 tiles, each with an icon and label. The
currently focused tile is highlighted with an accent glow; **arrow keys** move focus spatially and
**Enter/OK** opens the app. No external scripts or network calls.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Sidee Living Room TV                        24°C · Clear   Mon 3 Nov  │
│                                                          14:32        │
├──────────────────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │ STREAMING  │  │ MUSIC      │  │ UTILITIES  │  │ CUSTOM     │    │
│  │     ▶      │  │     🎵     │  │     🏠     │  │     🌐     │    │
│  │   Plex     │  │  Spotify   │  │ Home Asst. │  │ My Server  │    │
│  │◀ accent halo — focused tile ▶                              │    │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘    │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │     🎬     │  │     🎮     │  │     📝     │  │     ⛅     │    │
│  │  YouTube   │  │ GeForceNOW │  │  Notion    │  │  Weather   │    │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘    │
│                                         ← ↑ ↓ → navigate · Enter open│
└──────────────────────────────────────────────────────────────────────┘
```

## 7. Local Media

A folder path field + **Scan folder**, a count pill, **▶ Open player**, and a list of videos with
size, format badge and a `CC` badge when a matching `.srt`/`.vtt` is found. The player page is a
dark two-column layout: a large HTML5 `<video>` on the left and a scrollable playlist on the right,
with subtitles loaded through `<track>`.

```
  ┌───────────────────────────────────────┬───────────────────┐
  │                                       │ MP4  Movie  820 MB│
  │            < video player >           │      CC  [▶ Play] │
  │                                       │ MKV  Clip   1.2GB│
  │                                       │      [▶ Play]     │
  └───────────────────────────────────────┴───────────────────┘
```

## 8. Settings

- **Import / Export**: `⬇ Export setup` downloads one JSON; `⬆ Import file` or paste a config into
  the textarea; `Import as merge` toggles merge-vs-replace.
- **Startup**: two switches — *Launch Sidee at login* and *Keep Alive (restart on crash)* — plus a
  preferred port field.
- **Privacy & security**: local-only, PIN pairing, access-key protection, trust note.

## 9. Connect TV / onboarding wizard

Three numbered steps shown as cards (the active one is accent-outlined):
**1 Find your TV** (auto-discovery + manual IP check + device list), **2 Pair with PIN** (Request code
→ 4-digit PIN → Confirm code), **3 Add your first apps** (popular-choice cards + "Paste my own URL").
Below, the **Use your phone** QR card shows the locally generated QR and the private link. The wizard
opens automatically on first launch until you click **Done** / **Skip** (stored as
`dashboard_config.json → onboarded`).

## 10. Classic page (`/setup`)

The original light, three-column Sidee page (Find TV → Request code → Choose an app) is kept
unchanged and fully functional. It is linked from the sidebar footer for users who prefer it, and it
keeps the original QR-code and preset installer behaviour.
