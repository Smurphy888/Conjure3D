# 3D-Print Pipeline Spec

Canonical description of what each phase of the pipeline does. The VasePipe app is a UI wrapper around this. Edits to the pipeline are edits to this file first; code follows.

## Tools

- **Meshy** (`api.meshy.ai/openapi/v2/text-to-3d`) — text → 3D GLB
- **Blender** via the BlenderMCP addon TCP socket (`127.0.0.1:9876`) — geometry edits, sanity, STL export. Blender is **external**: user has it installed and running with the addon's "Connect to Claude" button clicked.
- **Bambu Studio** — slicing + printing (manual, outside the pipeline)

## Environment

- Meshy API key in Windows Credential Manager (service `vasepipe`, account `meshy_api_key`)
- Working dir: `%LOCALAPPDATA%\VasePipe\projects\<name>\`
- File stem per run: `<object_type>_{YYYYMMDD-HHMMSS}` — e.g. `vase_20260430-132930`, `guitar_20260503-050932`. All artifacts share it.
- Blender must be running with BlenderMCP socket on `:9876` listening. Pipeline aborts if it isn't.

## Phases

**Phase 1 — Pre-flight.** Verify Meshy key set, Bambu Studio path persisted, Blender process detected, BlenderMCP socket responds to a ping. Stop on any failure.

**Phase 2 — Generate.** POST to `/text-to-3d` with `mode: "preview"`, the prompt from MODEL SPEC, and `art_style`. Capture the task id. Poll `GET /text-to-3d/{id}` every 10 s up to 5 min. On `FAILED` or timeout: report and stop.

**Phase 3 — Refine + checkpoint.** Show preview thumbnail. User picks:
- (a) **refine** — POST `mode: "refine"` with `preview_task_id`, poll again;
- (b) **regenerate** — back to Phase 2 with edited prompt;
- (c) **accept** — proceed.

**Phase 4 — Download.** GET `model_urls.glb` to disk. Confirm size > 0 and magic bytes are `glTF`.

**Phase 5 — Import to Blender.** Send Python over the MCP socket: clear default cube, import GLB, frame viewport, render screenshot to file. Read screenshot, show user.

**Phase 6 — Edit loop.** Apply edits from MODEL SPEC, in **strict order**:

1. **Scale to longest dim.** Uniform scale so the longest world-space bbox dim equals `target_height_mm`. **Must run before voxel remesh** — Meshy outputs are at arbitrary scale (often 1–2 m); voxel remesh on an unscaled mesh produces millions of faces.
2. **Voxel remesh @ 0.8 mm.** Welds Meshy's mesh-soup into a single watertight surface.
3. **Keep largest connected component.** Drops floating blobs.
4. **Recenter X/Y, base at z=0.**
5. **Flat bottom.** Bisect at z = 0.5–1 mm, fill cut, repos to z=0. Removes any sub-mm tails on the base.
6. **Fix normals.** Compute signed volume; if negative, flip all normals. Outward-pointing normals = positive volume = correct printable mesh.
7. **Decimate** to a target face count (default 50,000). Voxel remesh always overproduces; decimate keeps STLs sane.
8. **Vase-only steps** (gated on `object_type == "vase"`):
   - **Open top.** Bisect at z = top - 2 mm, remove cap above.
   - **Bridge top loops.** If 2 boundary loops formed (outer rim + inner depression rim), bridge them into a single flat lip.
9. **Optional color split** (last step):
   - **zebra**: bisect into N horizontal bands, alternate colors, group into 2 objects.
   - **quarter**: 4 cutter cubes via Boolean Intersect (EXACT solver), produce 4 wedge sets per color.

After each edit, render a screenshot. Run sanity checks: manifold (0 boundary, 0 multi-face, 0 wire edges), single component (or expected count for color splits), normals consistent (signed volume > 0), longest dim ≤ 256 mm. Loop until user says "good."

**Phase 7 — Export STL.** Binary STL, mm units (`global_scale=1000`), one file per output object. Verify each file size > 0.

**Phase 8 — Hand off to Bambu Studio.** `Start-Process` with the STL path(s). Display printer profile (X1C), filament (PLA, 0.20 mm), and the **shape-aware slicer recipe** (see below). Do not click Print.

## Behavior rules

- **Pause at:** Phase 3 preview pick; Phase 6 "any further edits?"; Phase 8 hand-off. Never skip.
- **No silent retries on Meshy failure.** Surface error verbatim, ask before re-spending credits.
- **If BlenderMCP socket drops mid-run**, stop and ask user to reconnect (Blender N-panel → BlenderMCP → Connect to Claude). Do not fall back to subprocess Blender.
- **Surface intermediate file paths** in the UI.

## Failure recovery cheatsheet

- **Meshy generation fails** → quote error, ask before retry.
- **GLB imports as empty** → re-import with `import_pack='UNPACK'`; if still empty, regenerate.
- **Mesh non-manifold after Meshy** → already handled by auto-clean (voxel remesh + keep largest).
- **Voxel remesh produces millions of faces** → mesh wasn't scaled first. Ensure auto-clean order is correct.
- **File too large for build plate** → re-run scale step with smaller target, do not auto-shrink.
- **Bambu Studio binary missing** → search common paths, then ask user.
- **MCP socket timeout on heavy op** → likely scale step skipped. Auto-clean order solves this for the common case.

## MODEL SPEC (per-print parameters)

```yaml
prompt: "Stylized minimalist geometric vase, single watertight mesh,
         smooth surfaces, flat bottom, no support needed, ~80mm tall."
art_style: realistic        # realistic | sculpture | low-poly | cartoon
object_type: vase           # vase | solid_decorative | flat_part — gates auto-clean steps
target_height_mm: 80        # interpreted as longest dim (vase: height; guitar: length)
flat_bottom: true
decimate_target_faces: 50000
printer: X1C                # X1C | P2S
filament_note: "PLA, 0.20mm layer, default Bambu profile"
color_split:
  mode: none                # none | zebra | quarter
  zebra:
    count: 8                # number of horizontal bands
    axis: z                 # z | x | y
  colors: [red, yellow]     # used when mode != none
```

### object_type — what's gated

| Step | vase | solid_decorative | flat_part |
|---|---|---|---|
| scale, voxel remesh, keep largest, recenter, flat bottom, fix normals, decimate | ✓ | ✓ | ✓ |
| open_top | ✓ | ✗ | ✗ |
| bridge_top_loops | ✓ | ✗ | ✗ |
| color_split (parametric) | works well | works poorly — recommend slicer paint | works poorly — recommend slicer paint |

## Hollowing

The slicer hollows, not Blender. Two reliable approaches:

- **Vase / spiral mode** (vase only): single-walled spiral, lightest, fastest, no top cap. Bambu Studio: Process → Other → Spiral vase = ON.
- **Thin walls + 0% infill**: walls=5 (~2 mm at 0.4 mm line width), top shell layers=0, bottom shell layers=4, infill=0%.

## Why not Solidify in Blender?

Tried during prototyping. Two failure modes on dense voxel-remeshed topology:
1. `offset=+1, use_even_offset=True` blew the inner shell out to 1293 mm (Even Offset misbehaving on heavy concave/convex curvature).
2. `offset=-1, use_even_offset=False` produced an outward-growing shell because Solidify's offset sign depends on normal direction, and voxel-remeshed normals are unreliable here.

Slicer-side hollowing is precise (line width × wall count), reliable, and one click. Don't relitigate.

## Why Boolean Intersect, not bisect+fill, for color slicing?

`bpy.ops.mesh.bisect` with `use_fill=True` on a multi-component mesh creates T-junction artifacts where perpendicular cut planes meet existing component boundaries — the resulting edges have 3+ linked faces (multi-face edges). Boolean Intersect with EXACT solver against a quadrant cube produces clean topology because the operation re-tessellates the cut surface.

For zebra splits (single horizontal cuts per band) bisect+fill works fine because there's only one boundary per cut.

## Shape-aware slicer recipe (Phase 8 hand-off)

Display the matching block in the Export screen based on `object_type`.

### vase
- Process: 0.20mm Standard @BBL X1C
- **Spiral vase mode = ON** (if user wants thin-walled hollow), OR walls=5 + top=0 + infill=0
- Brim: not needed
- Predicted print: depends on size

### solid_decorative
- Process: 0.20mm Standard @BBL X1C
- Walls: 3
- Infill: 15% gyroid
- Top/bottom shells: 4
- **Brim: 5 mm** (critical if longest dim > 100 mm)
- Spiral vase mode = OFF
- Supports: OFF (flat-bottom orientation)

### flat_part
- Process: 0.20mm Standard @BBL X1C
- Walls: 4
- Infill: 20% gyroid
- Top/bottom shells: 4
- Brim: 3 mm
- Lay flat on bed (auto-orient should pick the largest face down)

## Open issues / known limitations

- **Parametric color split doesn't follow object anatomy** for shapes like guitars (body / neck / headstock) or chess pieces (base / column / top). v1 surfaces a warning and recommends Bambu Studio's brush paint. v2 stretch goal: in-app brush paint.
- **Sub-mm features get melted** by voxel remesh @ 0.8 mm — strings, fine frets, jewelry chains. Recommend regenerating with prompt language that suppresses thin geometry ("strings as embossed surface detail only"), or drop voxel size to 0.5 mm at higher face count.
- **No support generation** in Blender — orientation is the only support strategy. Auto-clean assumes flat-bottom orientation.

## Lessons from prototype runs

- **Vase run** (`vase_20260430-132930`): 80 mm tall, 8-band zebra, then quartered. Validated: voxel remesh, keep-largest, normal flip, top open + bridge, zebra, quartering via Boolean.
- **Guitar run** (`guitar_20260503-050932`): 200 mm long, solid decorative, no color split. Validated: object_type gating (skip open_top), scale-before-voxel-remesh ordering, decimate step. **First run skipped scale before voxel remesh** → 2.7M faces. Decimate to 50k after the fact recovered, but order was the lesson.
