# 3D-Print Pipeline Spec

This is the canonical description of what each phase of the pipeline does. The VasePipe app is a UI wrapper around this. Edits to the pipeline are edits to this file first; code follows.

## Tools

- **Meshy** (`api.meshy.ai/openapi/v2/text-to-3d`) — text → 3D GLB
- **Blender** via `bpy` — geometry edits, sanity, STL export
- **Bambu Studio** — slicing + printing (manual, outside the pipeline)

## Environment

- Meshy API key in env or keyring (per app config)
- Working dir: `%LOCALAPPDATA%\VasePipe\projects\<name>\`
- File stem per run: `vase_{YYYYMMDD-HHMMSS}` — all artifacts share it

## Phases

**Phase 1 — Pre-flight.** Verify Meshy key set, slicer binary exists, Blender (bpy) loads. Stop on any failure.

**Phase 2 — Generate.** POST to `/text-to-3d` with `mode: "preview"`, the prompt from MODEL SPEC, and `art_style`. Capture the task id. Poll `GET /text-to-3d/{id}` every 10 s up to 5 min. On `FAILED` or timeout: report and stop.

**Phase 3 — Refine + checkpoint.** Show preview thumbnail. User picks:
- (a) **refine** — POST `mode: "refine"` with `preview_task_id`, poll again;
- (b) **regenerate** — back to Phase 2 with edited prompt;
- (c) **accept** — proceed.

**Phase 4 — Download.** GET `model_urls.glb` to disk. Confirm size > 0 and magic bytes are `glTF`.

**Phase 5 — Import to Blender.** Clear default cube, import GLB, frame viewport, screenshot. Show user.

**Phase 6 — Edit loop.** Apply edits from MODEL SPEC:
1. Voxel remesh at 0.8 mm if non-manifold
2. Keep largest connected component
3. Scale to `target_height_mm`, recenter X/Y, base at z=0
4. Flat bottom: bisect at z=1mm, fill the cut
5. Fix normals: signed volume must be positive (flip if negative)
6. Open top: bisect at z=top-2mm, remove top cap
7. Bridge boundary loops if more than one
8. Optional color split (zebra or quarter)

After each edit, screenshot. Run sanity checks: manifold (0 boundary, 0 multi, 0 wire edges), single component, normals consistent (signed volume > 0), longest dim ≤ 256 mm. Loop until user says "good."

**Phase 7 — Export STL.** Binary STL, mm units (`global_scale=1000`), selected mesh only. Verify file size > 0.

**Phase 8 — Hand off to Bambu Studio.** `Start-Process` with the STL path(s). Tell user printer profile (X1C), filament (PLA, 0.20 mm), recommended hollow approach. Do not click Print.

## Behavior rules

- **Pause at:** Phase 3 preview pick; Phase 6 "any further edits?"; Phase 8 hand-off. Never skip.
- **No silent retries on Meshy failure.** Surface error verbatim, ask before re-spending credits.
- **If Blender connection drops mid-run**, stop and ask user to verify.
- **Surface intermediate file paths** in the UI.

## Failure recovery cheatsheet

- **Meshy generation fails** → quote error, ask before retry.
- **GLB imports as empty** → re-import with `import_pack='UNPACK'`; if still empty, regenerate.
- **Mesh non-manifold after Meshy** → voxel remesh at 0.5–1 mm, re-check.
- **File too large for build plate** → re-run scale step, do not auto-shrink.
- **Bambu Studio binary missing** → search common paths, then ask user.

## MODEL SPEC (per-print parameters)

```yaml
prompt: "Stylized minimalist geometric vase, single watertight mesh,
         smooth surfaces, flat bottom, no support needed, ~80mm tall."
art_style: realistic        # realistic | sculpture | low-poly | cartoon
target_height_mm: 80
flat_bottom: true
decimate_ratio: null        # 0.5 to halve poly count, null to skip
printer: X1C                # X1C | P2S
filament_note: "PLA, 0.20mm layer, default Bambu profile"
color_split:
  mode: none                # none | zebra | quarter
  zebra:
    count: 8                # number of horizontal bands
    axis: z                 # z | x | y
  colors: [red, yellow]     # used when mode != none
```

## Hollowing

The slicer hollows, not Blender. Two reliable approaches:

- **Vase / spiral mode**: single-walled spiral, lightest, fastest, no top cap. Use when the model has no internal cavity. Bambu Studio: Process → Other → Spiral vase = ON.
- **Thin walls + 0% infill**: walls=5 (~2 mm at 0.4 mm line width), top shell layers=0, bottom shell layers=4, infill=0%.

## Why not Solidify in Blender?

Tried during prototyping. Two failure modes on dense voxel-remeshed topology:
1. `offset=+1, use_even_offset=True` blew the inner shell out to 1293 mm (Even Offset misbehaving on heavy concave/convex curvature).
2. `offset=-1, use_even_offset=False` produced an outward-growing shell because Solidify's offset sign depends on normal direction, and voxel-remeshed normals are unreliable here.

Slicer-side hollowing is precise (line width × wall count), reliable, and one click. Don't relitigate.

## Why Boolean Intersect, not bisect+fill, for color slicing?

`bpy.ops.mesh.bisect` with `use_fill=True` on a multi-component mesh creates T-junction artifacts where perpendicular cut planes meet existing component boundaries — the resulting edges have 3+ linked faces (multi-face edges). Boolean Intersect with EXACT solver against a quadrant cube produces clean topology because the operation re-tessellates the cut surface.

For zebra splits (single horizontal cuts per band) bisect+fill works fine because there's only one boundary per cut.
