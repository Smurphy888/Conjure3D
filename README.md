# Conjure3D

Turn a text description into a sliceable 3D print. Type a prompt, get a printable file. Single-click launch on Windows.

```
Prompt → Meshy preview → (your pick) → auto-clean → editor → STL → Bambu Studio
                              ↑                        ↑                  ↑
                       checkpoint #1           checkpoint #2       checkpoint #3
                       (refine/regen/         (any further       (slice & print
                        accept)                edits?)            yourself)
```

Conjure3D drives a running Blender instance via the BlenderMCP addon. Blender stays visible while you work, so you can watch the mesh evolve in Blender's viewport at the same time as the in-app preview. The first-run wizard installs the BlenderMCP addon and walks you through connecting it.

## What can it print?

Anything you can describe that fits within a 256mm cube on the X1C. Examples that have been tested end-to-end:

| Prompt | object_type | Outcome |
|---|---|---|
| "Stylized minimalist geometric vase, ~80mm tall" | vase | Hollow-ready vase with open top |
| "Stratocaster-style electric guitar, ~200mm long" | solid_decorative | Solid figurine with surface detail |
| "Hexagonal coaster with embossed star pattern, 95mm wide" | flat_part | Lay-flat printable plaque |
| "Small chess pawn, classic style, 60mm tall" | solid_decorative | Sealed, supportless figurine |

The auto-clean chain handles the messy parts (mesh-soup outputs, sub-millimeter features, non-manifold geometry). It works best on objects with a flat bottom and no overhanging thin features — the slicer doesn't add support automatically, and the auto-clean voxel-remeshes anything thinner than ~1 mm into smooth surface.

## Requirements

- Windows 10/11, x64
- ~200 MB free disk for the app + projects
- A Meshy account and API key — https://www.meshy.ai/api
- **Blender 4.2 LTS or newer** — https://www.blender.org/download/lts/ (the wizard prompts you to install if missing)
- Bambu Studio installed — https://bambulab.com/en/download/studio
- Internet connection (only when generating; editing is offline)

## Install

1. Download `Conjure3D-Setup.exe` from the latest release (~50 MB).
2. Run it. SmartScreen may warn ("publisher unknown") — click **More info → Run anyway**. (App is unsigned in v1.)
3. App installs to `C:\Program Files\Conjure3D\`. Start menu + desktop shortcut are created.

## First run (wizard walks you through this)

1. **Launch Conjure3D.** A 5-step wizard appears.
2. **Step 1 — Blender:** wizard checks for an installed Blender. If missing, you get a "Download Blender LTS" button. Install Blender, then click **Re-check** in the wizard.
3. **Step 2 — BlenderMCP addon:** wizard copies the BlenderMCP addon into `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\` and enables it. Click **Done**.
4. **Step 3 — Connect Blender:** wizard launches Blender. In Blender, press `N` in the 3D viewport, click the **BlenderMCP** tab, click **Connect to Claude**. Back in the wizard, click **Test connection** — green check means socket `:9876` is live.
5. **Step 4 — Bambu Studio:** wizard finds Bambu Studio at the default path. If missing, browse to `bambu-studio.exe`.
6. **Step 5 — Meshy API key:** paste your key. Stored in Windows Credential Manager (service: `conjure3d`).
7. Wizard finishes. **New Project** screen opens.

## Daily use

Every session needs Blender open with BlenderMCP "Connect to Claude" clicked. Conjure3D checks this on launch and shows a Reconnect dialog if the socket is dead. You can minimize Blender — the app drives it via the socket.

## File locations

| What | Where |
|---|---|
| App settings | `%LOCALAPPDATA%\Conjure3D\settings.json` |
| Meshy API key | Windows Credential Manager → `conjure3d` |
| Default project folder | `%LOCALAPPDATA%\Conjure3D\projects\` |
| Crash logs | `%LOCALAPPDATA%\Conjure3D\logs\<timestamp>.log` |
| BlenderMCP addon | `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\blender_mcp\` |

Project artifact files (`.glb`, `.stl`) are named with a slug derived from your project name plus a timestamp — e.g. `lampshade-idea_20260503-070000.stl`. The app's UI shows the original project name; only the on-disk filename uses the slug.

## How a print actually happens

Conjure3D gets you to a sliceable file. It does not slice or print. After Export, Bambu Studio opens with your STL(s). You then:

1. Set printer profile (X1C) and filament(s) (PLA).
2. Assign filaments to objects if multi-color (panel on the right).
3. Click **Slice plate** → review → **Print**.

The handoff text shown in the Export screen has the exact slicer settings for the shape you generated.

## Slicer setup tips

The Export screen shows the recipe matched to your `object_type`. Quick reference:

- **Hollow rotational shapes** (vase, lampshade, cup): turn on **Spiral vase mode** in Bambu Studio's process settings for a single-walled hollow print.
- **Solid decorative objects** (figurines, busts, instruments): 15% gyroid infill, 3 walls, brim 5 mm if longer than 100 mm, supports off (auto-clean orients flat-bottom).
- **Flat parts** (coasters, plaques, panels): lay flat, 4 walls, 20% infill.
- **Multi-color (zebra / quarter splits):** Conjure3D outputs one STL per color. Don't enable vase mode — assign a filament to each object instead, set walls=5 and infill=0% if you want a thin shell.

## Troubleshooting

**"Blender not detected"**
Blender isn't installed, or installed somewhere unusual. Settings → Blender path → browse to `blender.exe`. Must be 4.2 or newer.

**"BlenderMCP socket not responding (port 9876)"**
Open Blender, press `N` in the 3D viewport, BlenderMCP tab, click **Connect to Claude**. The button must be clicked each time you start Blender. If the BlenderMCP tab isn't visible, the addon isn't enabled — Edit → Preferences → Add-ons → search "BlenderMCP" → enable.

**"Generate" hangs at 0% for > 30s**
Meshy didn't accept the request. Check Settings → Meshy key. Errors appear in the status bar; if not, see `%LOCALAPPDATA%\Conjure3D\logs\`.

**Editor "Apply" returns "Edit failed"**
A Blender op crashed. Click **Copy diagnostic** in the toast and paste into a bug report. Mesh-soup inputs (very low-poly Meshy outputs) sometimes break voxel remesh — try Refine in the Preview Pick step first.

**"Bambu Studio not found"**
Settings → Bambu Studio path → browse to `bambu-studio.exe`.

**Sanity panel shows red lights**
- Manifold red → mesh has holes; auto-clean usually fixes this. Otherwise regenerate with a more printable prompt ("single watertight mesh, flat bottom" helps).
- Longest dim red → your `target_height_mm × scale` puts a dimension over 256 mm. Lower target.

**SmartScreen blocks the installer**
Click "More info → Run anyway". App is unsigned in v1.

## Uninstalling

Settings → Apps → Conjure3D → Uninstall. To also clear the API key:
```powershell
cmdkey /delete:conjure3d
```
Wipe project data:
```powershell
Remove-Item -Recurse "$env:LOCALAPPDATA\Conjure3D"
```
Optionally remove the BlenderMCP addon from Blender's Edit → Preferences → Add-ons.

## Privacy

- Your prompts and parameters are sent to Meshy.ai (their API).
- No telemetry, no analytics.
- Conjure3D checks for app updates on startup (see [docs/release-signing.md](docs/release-signing.md)) — this is the only outbound network call not tied to a prompt/generation. Update artifacts are signature-verified before install.
- Crash logs stay on your machine.

## Development

If you're picking up the code, start with [HANDOFF.md](HANDOFF.md) and [docs/pipeline.md](docs/pipeline.md). [PROMPT.md](PROMPT.md) is the brief that kicks off the build from a fresh Claude Code session.
