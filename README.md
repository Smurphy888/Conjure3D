# VasePipe

Turn a text description into a sliceable, multi-color 3D print. Single-click launch on Windows. No Blender install needed — Blender ships inside the app.

```
Prompt → Meshy preview → (your pick) → auto-clean → editor → STL → Bambu Studio
                              ↑                        ↑                  ↑
                       checkpoint #1           checkpoint #2       checkpoint #3
                       (refine/regen/         (any further       (slice & print
                        accept)                edits?)            yourself)
```

## Requirements

- Windows 10/11, x64
- 2 GB free disk (the bundled Blender is heavy)
- A Meshy account and API key — https://www.meshy.ai/api
- Bambu Studio installed — https://bambulab.com/en/download/studio
- Internet connection (only when generating; editing is offline)

## Install

1. Download `VasePipe-Setup.exe` from the latest release.
2. Run it. SmartScreen may warn ("publisher unknown") — click **More info → Run anyway**. (The app is unsigned in v1; this is a one-time prompt.)
3. App installs to `C:\Program Files\VasePipe\`. A Start menu entry + desktop shortcut are created.

## First run

1. Launch VasePipe.
2. **Settings** dialog appears asking for your Meshy API key. Paste it; the key is stored in Windows Credential Manager (service: `vasepipe`).
3. If Bambu Studio isn't at the default path (`C:\Program Files\Bambu Studio\bambu-studio.exe`), Settings will ask you to point at it. Path is saved to `%LOCALAPPDATA%\VasePipe\settings.json`.
4. **New Project** screen opens. Type a prompt, set parameters, click **Generate**. ~3-5 min later you'll see a preview thumbnail.

## File locations

| What | Where |
|---|---|
| Settings | `%LOCALAPPDATA%\VasePipe\settings.json` |
| Meshy API key | Windows Credential Manager → `vasepipe` |
| Default project folder | `%LOCALAPPDATA%\VasePipe\projects\` |
| Crash logs | `%LOCALAPPDATA%\VasePipe\logs\<timestamp>.log` |

## How a print actually happens

VasePipe gets you to a sliceable file. It does not slice or print. After Export, Bambu Studio opens with your STL(s). You then:

1. Set printer profile (X1C) and filament(s) (PLA).
2. Assign filaments to objects if multi-color (panel on the right).
3. Click **Slice plate** → review → **Print**.

The handoff text shown in the Export screen has the exact slicer settings.

## Multi-color tips

- **Single color, hollow vase:** turn on **Spiral vase mode** in Bambu Studio's process settings.
- **Multi-color (zebra / quarter):** VasePipe outputs one STL per color. Don't enable vase mode — assign a filament to each object instead, set walls=5 and infill=0% if you want a thin shell.

## Troubleshooting

**"Generate" hangs at 0% for > 30s**
The Meshy API didn't accept the request. Check Settings → Meshy key. The error appears in the bottom-left status bar; if not, check `%LOCALAPPDATA%\VasePipe\logs\`.

**Editor "Apply" returns "Edit failed"**
A Blender op crashed. Click the **Copy diagnostic** button in the toast, paste into a bug report. Mesh-soup inputs (very low-poly Meshy outputs) sometimes break voxel remesh; try Refine in step 3 first.

**"Bambu Studio not found"**
Settings → Bambu Studio path → browse to `bambu-studio.exe`.

**Sanity panel shows red lights**
- Manifold red → mesh has holes; the auto-clean usually fixes this. If not, regenerate with a more printable prompt ("single watertight mesh, flat bottom" helps).
- Longest dim red → your `target_height_mm` × scale puts a dimension over 256 mm. Lower target height.

**SmartScreen blocks the installer**
Click "More info → Run anyway". The app is unsigned in v1.

## Uninstalling

Settings → Apps → VasePipe → Uninstall. To also clear the API key:
```powershell
cmdkey /delete:vasepipe
```
And to wipe project data:
```powershell
Remove-Item -Recurse "$env:LOCALAPPDATA\VasePipe"
```

## Privacy

- Your prompts and parameters are sent to Meshy.ai (their API).
- No telemetry, no analytics, no auto-update.
- Crash logs stay on your machine.

## Development

If you're picking up the code, start with [HANDOFF.md](HANDOFF.md) and [docs/pipeline.md](docs/pipeline.md). [PROMPT.md](PROMPT.md) is the brief that kicks off the build from a fresh Claude Code session.
