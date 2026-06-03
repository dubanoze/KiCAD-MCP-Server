# Local patches & customisations — posture-football-pod project

> This file lives in the repo root so patches are easy to review after `git pull`.
> For every patch: WHY it was added, WHAT it does, STATUS (still needed / upstreamed / removed).

---

## 1. `python/commands/library_symbol.py` — cache-invalidation fix

**Added:** 2026-06-01  
**Status:** ✅ PR opened: https://github.com/mixelpixx/KiCAD-MCP-Server/pull/218  
**Branch:** `fix/symbol-library-empty-cache-rebuild` (f7a92c6) → fork `dubanoze/KiCAD-MCP-Server`  
**Tests:** `tests/test_symbol_library_empty_cache_rebuild.py` — 3 tests, all pass

### What
Early-return in `_rebuild_if_needed` now also checks that the cache is non-empty:

```python
# Before (original):
if self.library_manager.project_path == project_path:
    return

# After (patch, tagged "SER2RJ45"):
if (self.library_manager.project_path == project_path
        and len(self.library_manager.libraries) > 0):
    return
```

### Why
On the very first call after `create_project` (before `sym-lib-table` existed on disk) the
manager was freshly constructed with an empty library list.  The original early-return treated
"same project path" as "cache is valid" and skipped the rebuild → symbols were never found.

### How to maintain
When pulling upstream: `git stash push python/commands/library_symbol.py` → `git pull` →
`git stash pop`.  Confirm the hunk applies cleanly; if upstream touched the same lines, resolve
manually and re-test by adding a component to a fresh project.

---

## 2. New tools: `set_layer_visibility` + `center_board_on_sheet`

**Added:** 2026-06-01  
**Status:** Implemented locally, not yet submitted as PR

### Files
- `python/commands/board/visibility.py` — Python logic (BoardVisibilityCommands)
- `python/commands/board/__init__.py` — two new delegate methods
- `src/tools/board.ts` — two new TS tool registrations

### `set_layer_visibility`
Writes a named layer preset into `.kicad_pro` (`board.layer_presets`).  
Use to hide F.Courtyard / B.Courtyard (purple outlines) without touching KiCad GUI.  
Reload board in KiCad after calling.

### `center_board_on_sheet`
Moves all board content (footprints, tracks, zones, drawings) so the Edge.Cuts
bounding box is centred on the paper sheet. Fixes boards that appear off-sheet.

---

## 3. `python/commands/freerouting.py` — prefer Java 25/21 over PATH default

**Added:** 2026-06-01  
**Status:** Local patch (not submitted as PR yet)

### What
`_find_java()` originally called `shutil.which("java")` first, which on Windows returns
whichever JDK is first on PATH (often Java 11). Freerouting 2.x requires Java 21+.

Patch scans `C:\Program Files\Eclipse Adoptium\jdk-*` (and similar Temurin/Microsoft/BellSoft
paths), sorts by major version descending, and returns the highest ≥21 installation.
Falls back to `shutil.which` / Unix paths as before.

### Why
Java 25 was installed but `check_freerouting` still reported `java_21_ok: false` because
Java 11 was first on PATH. All three JDK versions (11, 21, 25) were installed simultaneously.

---

## 4. `add_board_cutout` — polygon cutout in Edge.Cuts + all-layer copper keepout

**Added:** 2026-06-01  
**Files:** `python/commands/board/outline.py` · `python/commands/board/__init__.py` · `python/kicad_interface.py` · `src/tools/board.ts`

Adds an arbitrary polygon to `Edge.Cuts` (physical cutout through the PCB) and optionally
creates a `RULE_AREA` keepout zone on all copper layers over the same polygon.

Use-case: triangular/trapezoidal slot antenna cutout at the board edge (e.g. for PCB-integrated
slot antenna designs). Neutral name — not tied to any vendor trademark.

---

## 5. `import_pcb` — import Altium/Eagle/PADS boards via kicad-cli

**Added:** 2026-06-01  
**Files:** `python/commands/export.py` · `python/kicad_interface.py` · `src/tools/export.ts`

Wraps `kicad-cli pcb import --format <fmt>` to convert non-KiCad PCBs (Altium `.PcbDoc`,
Eagle, PADS, CadStar, P-CAD, Fabmaster, SolidWorks) into `.kicad_pcb`. Used to study
reference antenna designs by importing then reading exact coordinates via MCP.

Also fixed `_find_kicad_cli()` to include KiCad **10.0** paths and per-user
`%LOCALAPPDATA%\Programs\KiCad` installs (was only 8.0/9.0 in Program Files).

---

## 6. `delete_pcb_shape` — delete board drawings / zones near a point

**Added:** 2026-06-01  
**Files:** `python/commands/board/outline.py` · `python/commands/board/__init__.py` · `python/kicad_interface.py` · `src/tools/board.ts`

Deletes the nearest PCB_SHAPE (line/arc/polygon/rect) OR ZONE/RULE_AREA to a given point,
with optional layer + shape-type filter. Fills the gap where upstream had `add_*` but no
way to remove cutouts or orphaned keepout zones headless.

---

## 7. `ipc_backend.py` — Windows IPC socket auto-discovery

**Added:** 2026-06-01  
**File:** `python/kicad_api/ipc_backend.py` (`IPCBackend._windows_socket_candidates` + `connect`)

### Problem
On Windows the IPC backend only tried kipy's default (`gettempdir()\kicad\api.sock`).
When KiCad is launched from a sandbox that sets `TMPDIR=...\Temp\claude` but the MCP
backend's own `gettempdir()` resolves to `...\Temp`, the socket paths differ and IPC
never connects → server silently stays on SWIG (`backend: swig, ipc_connected: false`).
The socket is a Windows **named pipe**, invisible to `os.path.exists`/`glob`, so the
filesystem cannot be probed.

### Fix
Enumerate likely temp roots (`TMPDIR`/`TEMP`/`TMP`/`gettempdir()`/`%LOCALAPPDATA%\Temp`)
plus a `\claude` sub-dir variant of each, and let the existing connect/ping loop pick the
first socket that actually answers. No hardcoded paths; works regardless of which temp
KiCad used. Verified: connects with a deliberately-wrong TEMP and no `KICAD_API_SOCKET`.

(Cleaner than hardcoding `KICAD_API_SOCKET` in the agent config — good PR candidate.)

---

## 8. Notes on the server instance we run

| Item | Value |
|------|-------|
| Repo | `C:\Users\Denis Fedorov\tools\KiCAD-MCP-Server` |
| Version after last update | v2.1.0-alpha (+36 commits from f03a74a → 3b4ffef) |
| KiCad install | `C:\Users\Denis Fedorov\AppData\Local\Programs\KiCad\10.0` |
| Python used by backend | `...\KiCad\10.0\bin\python.exe` |
| JLCPCB DB | `C:\Users\Denis Fedorov\.kicad-mcp\data\jlcpcb_parts.db` (~4.3 GB, 7.16M parts) |
| DB source | yaqwsx/jlcparts pre-built cache (needs 7-Zip for extraction) |

### Known issues in v2.1.0-alpha (our environment)
- `get_board_2d_view` (MCP tool) → **broken**: kicad-cli SVG export fails in headless mode.
  **Workaround:** `kicad-cli pcb export pdf --layers "F.Cu,F.Silkscreen,Edge.Cuts" -o out.pdf board.kicad_pcb`
  then read the PDF.

### Build after pulling
```powershell
cd "C:\Users\Denis Fedorov\tools\KiCAD-MCP-Server"
# stash local patch first if needed
npm install
npm run build
# then reconnect MCP: /mcp → kicad → Reconnect
```

### Extra Python deps installed into KiCad python (required by v2.1.0-alpha)
```
C:\Users\Denis Fedorov\AppData\Local\Programs\KiCad\10.0\bin\python.exe -m pip install sexpdata "kicad-python>=0.5.0"
```

---

## Adding a new MCP tool (quick reference)

```
1. python/commands/<domain>/<mycommand>.py   — Python logic via pcbnew.*
2. src/tools/<mydomain>.ts                  — TS wrapper: name/description/inputSchema + callKicadScript(...)
3. src/server.ts                            — import and call registerMyTools(server)
4. npm run build                            — recompile TypeScript → dist/
5. /mcp → kicad → Reconnect                — pick up new tools
```
Round-trip time: ~5 min.  No Python compilation needed (Python files are read at runtime).

## 9. `add_copper_pour` — IPC param-name fix (`outline`) + `priority`

**Added:** 2026-06-02 · `python/kicad_interface.py` (`_ipc_add_copper_pour`) · `src/tools/routing.ts`

### Bug
The SWIG handler reads `params.get("outline", params.get("points", []))` (accepts both,
falls back to board outline), but the IPC handler `_ipc_add_copper_pour` read **only**
`params.get("points", [])`. The TS tool schema exposes the boundary as **`outline`**, so in
IPC mode (KiCad GUI open) every `add_copper_pour` failed with *"At least 3 points are required"* —
copper pours could not be created live. The existing F.Cu/In1.Cu zones had been made earlier
in SWIG mode, masking the bug.

### Fix
- IPC handler now reads `params.get("outline") or params.get("points") or []` (same as SWIG).
- Added optional `priority` to the TS schema (the IPC handler already forwarded it to
  `add_zone`). Lets a GND plane override a lower-priority / netless zone on the same layer
  without deleting it (delete_pcb_shape has no IPC path).

Python is read at runtime → only `/mcp` reconnect needed; TS needed `npm run build`.

### Bug #2 (same feature): `Zone.fill_mode` has no setter
After the param fix, `add_zone` (IPC/kipy) still returned False. Log:
`property 'fill_mode' of 'Zone' object has no setter`. In this kipy build `Zone.fill_mode`
is read-only; assigning it raised `AttributeError` and aborted zone creation entirely
(`python/kicad_api/ipc_backend.py::add_zone`). Fixed: try the property, fall back to the
proto field, else keep KiCad's default solid fill — never abort the zone for fill mode.

---

## 10. `delete_zones` — remove stray/duplicate/netless copper zones

**Added:** 2026-06-02 · `python/kicad_api/ipc_backend.py` (`delete_zones`) ·
`python/kicad_interface.py` (`_ipc_delete_zones` + `_handle_delete_zones` swig fallback +
route + IPC_CAPABLE + `_BOARD_MUTATING_COMMANDS`) · `src/tools/routing.ts`

Filters by `layer` and/or `net` (`net=""` targets netless zones); `copperOnly` (default
true) protects rule-area / keepout zones so antenna keepouts are never deleted. IPC path
uses kipy `board.remove_items`; SWIG path uses `board.Remove`.

**Why:** the 4-layer GND fill left a leftover **netless In2.Cu zone** that filled as floating
copper overlapping the real GND plane. Zone fill *priority* does NOT exclude a no-net zone, and
`delete_pcb_shape` (point-nearest) can't disambiguate two full-board zones sharing a bbox
centre — so a net-filtered delete was needed. `delete_zones layer=In2.Cu net=""` removes
exactly the stray.

---

## 11. `set_layer_name` — fix a layer's display name

**Added:** 2026-06-02 · `python/kicad_interface.py` (`_handle_set_layer_name` + route +
`_BOARD_MUTATING_COMMANDS`) · `src/tools/routing.ts`

Renames a board layer via `board.SetLayerName`. Target by numeric `layerId` (unambiguous when
a custom name is duplicated) or canonical `layer` name; empty `name` reverts to default.

**Why:** the board (generated via kicad-skip/MCP) had **F.SilkS (id 5) mislabelled "In2.Cu"**,
so the front silkscreen showed up under the copper layer's name — `GetLayerName` returned
"In2.Cu" for both id 5 (silk) and id 6 (real copper), which masqueraded as a phantom copper
defect. kipy/IPC can read layer names but not set them (`get_layer_name` only), so this is a
SWIG-path tool: **KiCad GUI must be closed** (IPC active leaves `self.board` stale). Fix:
`set_layer_name layerId=5 name="F.Silkscreen"`.

---

## 12. `delete_trace` — real IPC implementation (kipy remove_items)

**Added:** 2026-06-02 · `python/kicad_api/ipc_backend.py` (`delete_traces`) ·
`python/kicad_interface.py` (`_ipc_delete_trace`)

`_ipc_delete_trace` previously just `return self.routing_commands.delete_trace(params)`
— i.e. it ran the SWIG path on `self.board`, a copy **separate from the live IPC GUI
board**. So deletions never reached the GUI/disk, and the SWIG proxy **dehydrated after
the first mutation** (`'SwigPyObject' object is not iterable`) — a parallel batch had
only its first call succeed.

Now net-based deletes use kipy `board.remove_items` on the live board in a single
transaction: `delete_traces(net, include_vias)` gathers `get_tracks()`/`get_vias()`
objects (net `"*"`/None = all) and removes them at once — no per-item dehydration, visible
live. `delete_trace net="*" includeVias=true` clears every track+via in one call. UUID/
position deletes still fall back to SWIG.

---

## 13. `update_footprints_from_library` — re-load placed footprints from library

**Added:** 2026-06-02 · `python/kicad_interface.py` (`_handle_update_footprints_from_library`
+ route) · `src/tools/routing.ts`

KiCad's Tools->Update Footprints from Library, headless. Re-loads each placed footprint from
its library (`FootprintLoad`, fresh from disk — no GUI cache), preserving
position/orientation/side/reference/value and re-mapping nets by pad number. `references`
limits scope (e.g. `['A1']`); omit = all.

**Why:** after re-importing the Altium niche antenna `.PcbLib` (which has 2 pads + 11 vias +
copper traces) into our project library, the board's `A1` instance was still the old stripped
2-pad version. `sync_schematic_to_board` only assigns nets (not footprint geometry);
`place_component`/`replace_component` couldn't resolve a project fp-lib footprint; and the GUI
"Update from Library" served a **stale cached** 2-pad footprint (the window was opened before
the library was rewritten). This tool reads the library file directly, so it always gets the
current geometry. SWIG path — run with the GUI closed.

**Added:** 2026-06-02 · component.py / kicad_interface.py / src/tools/component.ts

Assign/replace a placed footprint's 3D model (FP_3DMODEL). Use when a footprint's bundled
model .step is missing in the install (e.g. USB_C_Receptacle_HRO right-angle) — point it at an
available model such as GCT_USB4105 ...Horizontal.step. Board-mutating (auto-save).

---

## 14. Dual-backend bridge — SWIG board writes while the GUI is open over IPC

**Added:** 2026-06-02 · `python/kicad_interface.py`
(`_live_gui_bridge_active`, `_bridge_gui_to_disk`, `_bridge_disk_to_gui`, `handle_command`
hook, `_SWIG_SELF_SAVING_COMMANDS`, `_auto_save_board` pcbnew import) ·
`python/kicad_api/ipc_backend.py` (`save_live_board`, `revert_live_board`, `get_board_filename`)

### Problem
SWIG handlers mutate `self.board`, a file-backed copy. When KiCad is open over IPC that copy is
**not** the document the user sees, so SWIG-only tools (`set_layer_name`,
`update_footprints_from_library`, `delete_zones`, `delete_pcb_shape`, …) edited a stale board and
the GUI silently diverged from disk — forcing a close / `/mcp reconnect` / reopen dance for every
such command.

### Fix
For a board-modifying SWIG command issued while IPC is live, `handle_command` brackets the handler:
1. `_bridge_gui_to_disk` — `board.save()` (kipy) flushes the live document to disk, then
   `self.board` is reloaded from it, so the SWIG edit is applied on top of the current GUI state.
2. the SWIG handler runs and persists (generic auto-save or self-save).
3. `_bridge_disk_to_gui` — `board.revert()` (kipy) reloads the open document from disk so the GUI
   reflects the edit; the IPC board handle is re-fetched (revert invalidates it).

Gated by `_live_gui_bridge_active` (IPC up + command SWIG-only + board-modifying) and degrades
safely — any failed step logs and falls back to the previous behaviour. Also fixes
`_auto_save_board`, which used `pcbnew` without importing it (the module-level import is skipped
when the IPC backend is selected), so SWIG auto-save failed with *"name 'pcbnew' is not defined"*
whenever the GUI was open.

Result: SWIG and IPC tools operate on the same open board with no manual mode switching — the
"run with the GUI closed" caveat on patches 10-13 no longer applies.

---

## 16. `assign_footprint_graphic_net` — net a footprint's copper artwork

**Added:** 2026-06-02 · `python/kicad_interface.py`
(`_handle_assign_footprint_graphic_net` + route + `_SWIG_SELF_SAVING_COMMANDS`) ·
`src/tools/routing.ts`

Assigns a net to a footprint's copper graphic shapes via `PCB_SHAPE.SetNet` (KiCad 7+ copper
shapes are net-aware). `reference` + `net`, optional `layer` to restrict to one copper layer.

**Why:** the Altium niche antenna imports its copper ground ring as **net-less footprint
graphics** (Altium copper primitives → KiCad `fp_line` on F.Cu, with no net). That copper
physically touches the GND via-fence and the GND pour, so DRC reports *shorting_items "GND and
‹none›"*, zone-clearance 0 mm and solder-mask bridges. Grounding the shapes (same net as the
pour/vias) clears the conflict without deleting the antenna artwork. SWIG path that self-saves;
listed in `_SWIG_SELF_SAVING_COMMANDS` so the dual-mode bridge applies it to the live board.

---

## 15. `set_grid` — change the live editor grid

**Added:** 2026-06-02 · `python/kicad_api/ipc_backend.py` (`IPCBoardAPI.set_grid`) ·
`python/kicad_interface.py` (`_ipc_set_grid`, `_handle_set_grid_no_gui`, route + IPC_CAPABLE) ·
`src/tools/routing.ts`

Steps the active PCB-editor grid via KiCad `run_action`: `finer`/`coarser`
(`gridNext`/`gridPrev`, with a `steps` repeat), the two user fast grids (`fast1`/`fast2`), or
`cycle` (`gridFastCycle`). The IPC API exposes no read or absolute-set for the grid size (kipy
`KiCad.grid`/`Board.grid` are empty and there are no grid commands), and the active grid lives in
the editor frame, not the board/project file — so stepping through the configured grid list is
the only available control. IPC-only: the SWIG route returns a "needs KiCad open over IPC"
message. Not board-mutating, so the dual-mode bridge does not engage.

---

## 17. `convert_footprint_graphics_to_tracks` — promote footprint copper graphics to board tracks

**Added:** 2026-06-02 · `python/kicad_interface.py`
(`_handle_convert_footprint_graphics_to_tracks` + route + `_SWIG_SELF_SAVING_COMMANDS`) ·
`src/tools/routing.ts`

Converts a footprint's copper graphic shapes (`PCB_SHAPE` segments/arcs) into genuine
board-level tracks (`PCB_TRACK`/`PCB_ARC`) carrying a given net. `reference` + `net`, optional
`layer` to restrict to one copper layer, `remove_source` (default true) to delete the originals.

**Why:** a KiCad `FOOTPRINT` cannot hold real tracks/vias — `FOOTPRINT::Add()` rejects
`PCB_TRACE_T` outright (`BOARD_ITEM type (13) not handled`), so Altium track primitives import as
net-less `fp_line` graphics. A copper pour never integrates with graphics (a zone keeps clearance
from a shape even on the same net), so the niche antenna's GND ring shows up as `zone clearance
0 mm` / `shorting_items` DRC errors that grounding alone (patch #16) cannot clear. Promoting the
geometry to real tracks lets the pour connect to it and removes the violations. A footprint
shape's `GetStart`/`GetEnd` are already in board coordinates (placement transform baked in), so
the geometry copies straight onto a track; stroke width carries over (0.2 mm fallback). SWIG path
that self-saves; listed in `_SWIG_SELF_SAVING_COMMANDS` so the dual-mode bridge applies it live.

---

## 18. Demote a stale IPC session to SWIG when KiCad has closed

**Added:** 2026-06-02 · `python/kicad_interface.py` (`_try_enable_ipc_backend`)

When `use_ipc` is set but the KiCad process is no longer running, `_try_enable_ipc_backend` now
clears `use_ipc`/`ipc_board_api` and returns `False`, so the next command falls back to the SWIG
file backend instead of routing to a dead socket.

**Why:** after the user closed pcbnew, board-mutating commands kept being routed to the stale IPC
session and failed (`KiCad is busy` / no board), forcing a manual `/mcp` reconnect. Checking
`KiCadProcessManager.is_running()` and demoting on the spot makes the backend self-heal — the
session transparently continues on SWIG once the GUI is gone.

---

## 19. `add_zone` — copper pour with pad-connection control

**Added:** 2026-06-02 · `python/kicad_api/ipc_backend.py` (`IPCBoardAPI.add_zone` `pad_connection`) ·
`python/kicad_interface.py` (`_ipc_add_zone`, `_handle_add_zone`, route + IPC_CAPABLE +
`_SWIG_SELF_SAVING_COMMANDS`) · `src/tools/routing.ts` (TS tool already existed; backend was missing)

The TS `add_zone` tool existed but the Python backend returned *"Unknown command"*. Implemented it
on both backends. Unlike `add_copper_pour` it exposes **`padConnection`** (solid / thermal / none).
On IPC the pad-connection style is written via the proto
(`zone._proto.copper_settings.connection.zone_connection = ZCS_FULL`, the kipy wrapper has no
setter); on SWIG via `ZONE.SetPadConnection`.

**Why:** `solid` floods copper right up to a net's pads — required to fully bury stitching
vias/pads, which the default thermal relief leaves spoke-gapped. `add_copper_pour` could not do
this. (Superseded for the antenna by patch #20, which fixes the fill at the pad/footprint level
instead of with an extra zone, but `add_zone` remains the general way to drop a pour with a
specific pad-connection.)

---

## 20. `set_pad_zone_connection` — set a placed footprint's pad-to-zone connection

**Added:** 2026-06-02 · `python/kicad_interface.py`
(`_handle_set_pad_zone_connection` + route + `_SWIG_SELF_SAVING_COMMANDS`) · `src/tools/routing.ts`

Sets the zone-connection mode (`solid`/`thermal`/`none`/`inherit`) on a placed footprint's pads
via `PAD.SetLocalZoneConnection`. `reference` + `connection`; optional `pads` (limit to pad
numbers) and `net` (limit to a net, e.g. `GND`).

**Why:** the niche antenna's GND via-fence looked unfilled because the default thermal relief
leaves gaps around each pad. Setting the GND pads to `solid` makes the existing GND pour flood
solidly around them (the slot side stays open by design) — the clean, portable fix, done at the
footprint/pad level rather than with board-level patch zones or a zone-wide clearance change. The
matching library footprint pads are set the same way so the property travels with the component.
SWIG self-saving; applies live via the dual-mode bridge.

---

## 21. `delete_zones` — `maxAreaMm2` filter (target small local/patch zones)

**Added:** 2026-06-02 · `python/kicad_interface.py` (`_handle_delete_zones`) ·
`src/tools/routing.ts`

Adds an optional `maxAreaMm2` filter to `delete_zones`: only zones whose outline area is at most
the given value are removed (`abs(zone.Outline().Area()) / 1e12`). Combined with `net`/`layer` it
targets small local "patch" pours — e.g. the antenna-corner GND zones added as a fill crutch —
without touching the full-board GND/PWR planes that share the same net and layer.

**Why:** `delete_zones` filtered only by net+layer, so it could not remove a small local GND zone
without also deleting the main GND plane on that layer. Area-bounding makes the cleanup surgical.
SWIG path (the IPC handler ignores `maxAreaMm2` for now — kipy exposes no zone-area accessor).

---

## 22. `add_component` — sync per-project reference inside `(instances ...)` after clone

**Added:** 2026-06-03 · `python/commands/component_schematic.py`
(`ComponentManager._sync_instance_references`, called from `add_component`)

`add_component` builds a new part by `clone()`-ing a `_TEMPLATE_*` symbol, then sets the new
`uuid` and the `Reference` *property*. But `clone()` copies the template's `(instances ...)` block
verbatim, so every `(project ... (path ... (reference "_TEMPLATE_...")))` entry still named the
template. KiCad annotates from that **per-project reference**, not the property — so the cloned
part read as unannotated/duplicate and the sheet was silently dropped from the netlist
(comp count collapses, e.g. 47 → 21). Native eeschema schematics carry **two** project blocks
(`"<project>"` + `"project"`); the new walker re-points the reference in **all** of them.

**Why:** adding any dynamically-loaded symbol (3-pin BPF FL1, multi-unit parts) via the MCP tool
hit this — it cost a long manual debug cycle (hand-fixing both project blocks). Now the tool does
it. Verified on `mcu.kicad_sch`: cloning `XM4` yields instance refs `['XM4','XM4']`, sync to a new
ref updates both → `['XM99','XM99']`. Raw-sexpr walk, best-effort (never raises). Pure-Python,
no TS change; takes effect on backend restart.

> NB: the **cache** half of this class of bug (lib_symbols parent must carry the `lib:` prefix,
> sub-symbols `Name_0_1` must NOT) is already handled correctly by `dynamic_symbol_loader.py`
> (`_extract_symbol_block` skips `_\d+_\d+` names; only the first/top-level name is prefixed).

---

## 23. `add_net_class` — persist net classes to `.kicad_pro` directly

**Added:** 2026-06-03 · `python/kicad_interface.py` (`_handle_add_net_class`, registered as
the `add_net_class` command)

The `add_net_class` / `assign_net_to_class` tools had no Python handler ("Unknown command"),
and `create_netclass` mutated the SWIG board's `GetNetClasses()` — but net classes and
net->class assignments live in the **project** file (`net_settings` in `.kicad_pro`), not the
board, so a board save never persisted them (the class looked created in memory, then vanished).
On top of that the board-save path itself was flaky here (IPC project-manager hijack → save fails).

`_handle_add_net_class` writes the `.kicad_pro` JSON directly, independent of the board/IPC save
path: it upserts the class into `net_settings.classes` (copying the `Default` class as a template
so every field KiCad expects is present, then overriding clearance/track_width/via_*/diff_pair_*),
gives custom classes precedence over `Default` (priority 0+ vs Default's max-int), and assigns nets
via `net_settings.netclass_patterns` (`{netclass, pattern}` exact-name entries, de-duplicated).
Project path comes from `_current_project_file_path()` (or an explicit `projectPath`/`boardPath`).

**Why:** routing the RF feed needed an `RF` net class (0.34 mm = 50 Ω microstrip on the JLC7628
0.8 mm stack) assigned to ANT_RF/ANT_FEED/FL_IN/FL_OUT, and no working tool could create+assign
one. Reuses the existing `add_net_class` TS schema (no TS change); Python-only, effective on
backend reconnect. Verified: writes `RF` (track 0.34, priority 0) + 4 patterns, valid `.kicad_pro`.

---

## 24. `set_design_rules` — persist min-* constraints to `.kicad_pro`

**Added:** 2026-06-03 · `python/kicad_interface.py` (`_handle_set_design_rules` wraps
`design_rule_commands.set_design_rules`; dispatch entry repointed)

Same persistence gap as #23: the design-rule constraints (`min_clearance`, `min_track_width`,
`min_via_diameter`, `min_through_hole_diameter`, `min_microvia_*`) live in the project's
`board.design_settings.rules` (`.kicad_pro`), so the SWIG board mutation in `set_design_rules`
updated the in-memory board but never reached disk — re-reading `.kicad_pro` still showed
`min_clearance: 0.0`. The wrapper runs the original SWIG handler (for the live board), then writes
the constraints straight into `.kicad_pro` via `_current_project_file_path()`, mapping the tool's
camelCase params to KiCad's snake_case rule keys.

**Why:** the board shipped with `min_clearance = 0` (DRC could not catch shorts). Setting JLCPCB
values (clearance/track 0.127, via 0.45/0.2, hole 0.2) via the existing tool now actually persists.
Python-only, effective on reconnect.

---

## 25. `set_stackup` — author the physical stackup in `.kicad_pcb`

**Added:** 2026-06-03 · `python/kicad_interface.py` (`_handle_set_stackup`) ·
`src/tools/design-rules.ts` (new `set_stackup` tool) · `src/tools/registry.ts` (drc category)

New tool to define the board physical stackup. The stackup lives in the board's `(setup ...)`
block and SWIG `pcbnew` has no API to author it, so the handler edits the s-expression directly:
it reads the board's own copper-layer names, interleaves them with the supplied dielectrics
(N copper layers -> N-1 dielectrics), emits the standard KiCad stackup (silk/paste/mask + copper +
dielectric layers + `copper_finish`), then replaces an existing `(stackup ...)` or inserts one as
the first child of `(setup ...)`. Params: `copper[]` (per-layer Cu thickness, defaults outer 0.035
/ inner 0.018), `dielectrics[]` (`thickness`, `epsilon_r`, `type` prepreg|core, `loss_tangent`),
`maskThickness`, `copperFinish`, `material`.

Safety: the board carries the hand-routed RF corner, so the handler **backs up to
`<board>.stackup.bak` before writing and refuses on parenthesis imbalance**. Verified end-to-end
on a board copy — kicad-cli loads the result. First MCP tool requiring a TS rebuild (`npm run
build`) since the dual-backend bridge; effective on reconnect.

**Why:** the board defaulted to ~1 mm with no controlled stackup; the design targets JLCPCB
4-layer 0.8 mm JLC7628 (PP 0.2/Er4.6 · core 0.265/Er4.5 · PP 0.2/Er4.6, Cu 35/18/18/35 µm) so the
0.34 mm RF feed is a real 50 Ω microstrip. Wanted settable from MCP, not only the Board Setup GUI.

---

## 26. `set_zone_clearance` — edit existing fill-zone clearance + refill

**Added:** 2026-06-03 · `python/kicad_interface.py` (`_handle_set_zone_clearance`) ·
`src/tools/routing.ts` (new tool) · `src/tools/registry.ts` (routing category)

The existing zone tools only set clearance when *creating* a pour (`add_copper_pour` / `add_zone`);
there was no way to change the local clearance of an already-placed zone. New `set_zone_clearance`
matches existing fill zones by `net` and/or `layer` (rule areas / keepouts are skipped via
`GetIsRuleArea()`), applies `SetLocalClearance`, refills (`ZONE_FILLER`) and self-saves. Backs up
the board to `<board>.zoneclr.bak` first since it carries hand-routed copper.

**Why:** the GND pours on F.Cu/B.Cu/In2 carried a 0.5 mm local clearance (vs 0.2 on the In1 plane),
which fragmented the top fill around the dense RF cluster. Normalising them to 0.2 mm needed an
MCP-settable edit of existing zones. SWIG path (KiCad GUI must be closed); the SWIG `ZONE_FILLER`
refill is the same one `add_zone` uses successfully here. Python+TS, rebuild + reconnect.

---

## 27. `sync_schematic_to_board` — reuse the loaded board instead of reloading

**Added:** 2026-06-03 · `python/kicad_interface.py` (`_handle_sync_schematic_to_board`)

When called with `boardPath`, the sync did a fresh `pcbnew.LoadBoard(boardPath)` via
`_safe_load_board`, which in this long-lived SWIG process **reliably returned a dehydrated proxy**
("Could not load board ... dehydrated SWIG proxy") — so the sync was unusable, even though
`open_project` had already loaded a healthy board into `self.board` and kicad-cli loads the file
fine. (A fresh process like kicad-cli works; the server's accumulated SWIG state does not.)

Fix: prefer the already-loaded `self.board` when it is healthy and its filename matches the
requested `boardPath` (resolved), and only fall back to `_safe_load_board` when nothing usable is
loaded. So the working flow is `open_project` (loads a healthy board) → `sync_schematic_to_board`
(reuses it, no dehydrating reload). Python-only, effective on reconnect.

---

## 28. `save_schematic` — pretty-print kicad-skip output (token-preserving)

**Added:** 2026-06-03
**Status:** ✅ local; Python-only, effective on reconnect
**Files:** `python/commands/sexpr_pretty.py` (new), `python/commands/schematic.py`

### What
`SchematicManager.save_schematic` now calls `sexpr_pretty.format_kicad_sch_file(path)`
right after `schematic.write(path)`. The new module re-indents the `.kicad_sch` into
KiCad-canonical multi-line form.

### Why
kicad-skip's `Schematic.write()` serialises the entire schematic on a **single line**
(0 newlines). KiCad reads it fine (whitespace-insensitive) but git diffs become useless
("5380 deletions / 8 insertions") and it does not match what eeschema produces. This hit
us swapping U4 TP4054→CN3163 via MCP: every `add_schematic_component` / net-label write
collapsed `power.kicad_sch` to one line.

The KiCad **IPC API (kipy)** can't help here — it is board-only on write; there is no
schematic-edit API (hence "IPC mode = pcbnew only"). Schematic edits must go through
kicad-skip, so the fix is to clean up its serialiser output.

### How (safety)
`format_kicad_sexpr` tokenises, re-emits pretty, then **re-tokenises and refuses to write
unless the token tree is byte-for-byte identical** to the input. So it can only change
whitespace, never a token — worst case it's a no-op. `format_kicad_sch_file` swallows all
errors so formatting can never break an otherwise-successful save.

### Maintain
Pure add-on; no upstream conflict expected. If kicad-skip ever gains pretty output,
this becomes a redundant no-op and can be removed.

---

## 29. Dev hot-reload of command handlers (no reconnect on python edits)

**Added:** 2026-06-03
**Status:** ✅ local dev affordance; opt-in (off by default)
**Files:** `python/kicad_interface.py`

### What
The top-level handler-import block is now wrapped in `_load_command_handlers()`
(declares all 21 names `global`, then imports). `handle_command` calls
`_maybe_hot_reload()` first: when enabled it drops every cached `commands.*`
module from `sys.modules` and re-runs `_load_command_handlers()`, so edits to
python command files take effect on the **next tool call** — no MCP
reconnect/restart needed.

### Why
The MCP server runs a persistent python process; python edits are otherwise
only picked up on `/mcp` reconnect. With 28+ local patches that iteration loop
is painful. (kipy can't help — it's board-only; schematic work stays in python.)

### Enable
Either set env var `KICAD_MCP_HOTRELOAD=1`, **or** create an empty file
`.kicad_mcp_hotreload` in the server root (easier — no MCP-config edit). Default
(neither present) = no-op, identical to upstream behaviour.

### Caveats
Re-imports ~24 small modules per call (negligible at human pace). A syntax error
in a file being edited makes that call fail until the file is fixed (self-heals
on the next good edit). Keep OFF for non-dev use.

---

## 30. get_schematic_view_region — PNG converter dependency (pymupdf)

**Added:** 2026-06-03
**Status:** ✅ local (pymupdf installed into KiCad's python); requirements.txt updated for PR

### What / Why
`get_schematic_view_region` (region-crop PNG of a schematic — the "close-up vision"
tool) fails with *"No PNG converter available. Install pymupdf, inkscape, or
imagemagick"* on a stock install: it does NOT use `cairosvg` (which IS in
requirements and is used by `get_schematic_view`). KiCad's bundled python had no
pymupdf → tool unusable.

### Fix
`pip install pymupdf` into the server's python (KiCad-bundled
`AppData/Local/Programs/KiCad/10.0/bin/python.exe`); add `pymupdf` to
requirements.txt.

### PR opportunity
Make `get_schematic_view_region` fall back to **cairosvg** (already a dependency)
for SVG→PNG, so it works out-of-the-box without an extra binary. Then this becomes
a 1-line requirements note instead of a runtime dependency surprise.

---

## 31. New schematic tools: delete_no_connect, delete/edit_schematic_text

**Added:** 2026-06-03
**Status:** ✅ local; TS+Python, needs `npm run build` + reconnect to expose
**Files:** `python/commands/wire_manager.py`, `python/kicad_interface.py`, `src/tools/schematic.ts`

### What
Three new MCP tools to close gaps that previously forced direct-file scripting:
- **delete_no_connect** — remove a no-connect (X) flag by position or componentRef+pinNumber
  (mirror of add_no_connect; there was add but no delete).
- **delete_schematic_text** — remove a free-form text annotation by exact text or position.
- **edit_schematic_text** — change a text annotation's content in place (position preserved);
  previously only add_schematic_text / list_schematic_texts existed.

### Why
Cleaning up the CH585M migration needed: dropping stray NC flags (no delete tool) and
fixing the sheet title text (no edit/delete tool). Per project rule "no scripts on KiCad
files — only MCP tools; add the tool if missing".

### Impl
`WireManager.delete_no_connect / delete_text / edit_text` (sexpdata load → match by
position/text → mutate → dump). Output is re-prettified by the central save-format hook
(patch #28). Handlers in kicad_interface.py + dispatch entries; zod schemas in schematic.ts.

---

## 32. New schematic tool: set_schematic_pin_type

**Added:** 2026-06-04
**Status:** ✅ local; TS+Python, needs `npm run build` + reconnect to expose
**Files:** `python/commands/wire_manager.py`, `python/kicad_interface.py`, `src/tools/schematic.ts`

### What
**set_schematic_pin_type** — set one pin's electrical type in a placed symbol's cached
definition (`lib_symbols`), located by `componentRef` (resolved to lib_id) or `libId`,
matched by pin number. Valid types: input/output/bidirectional/tri_state/passive/free/
unspecified/power_in/power_out/open_collector/open_emitter/no_connect.

### Why
ERC reads pin electrical types from the schematic's `lib_symbols` cache. Two recurring
needs had no tool and were previously fixed by editing the file directly:
- EasyEDA/LCSC-imported symbols arrive with all pins `unspecified` → pin_to_pin ERC noise
  (the CH585M import: 30 warnings, fixed across 49 pins).
- A DC-DC switch node (CH585M VSW) mistyped `power_in` → power_pin_not_driven; correct
  type is `passive`.
Per project rule "no scripts on KiCad files — only MCP tools; add the tool if missing".

### Impl
`WireManager.set_pin_type` (sexpdata load → resolve lib_id from Reference if needed →
find `(symbol "<lib_id>" ...)` in `(lib_symbols ...)` → recurse sub-units → match
`(pin <type> <shape> ... (number "N"))` → rewrite leading type token → dump).
Re-prettified by the central save hook (patch #28). Handler + dispatch in
kicad_interface.py; zod enum schema in schematic.ts.

---

## 33. New schematic tool: update_schematic_symbols_from_library

**Added:** 2026-06-04
**Status:** ✅ local; TS+Python, needs `npm run build` + reconnect to expose
**Files:** `python/commands/symbol_updater.py` (new), `python/kicad_interface.py`,
`src/tools/schematic.ts`

### What
**update_schematic_symbols_from_library** — eeschema's "Update Symbols from Library",
done file-side. Re-reads each used symbol from its source library and overwrites the
schematic's `(lib_symbols ...)` cache, clearing `lib_symbol_mismatch` ERC. Options:
`libIds` / `componentRefs` (narrow scope), `pruneUnused` (drop cache entries no instance
references), `extraLibTables`.

### Why
kicad-skip / EasyEDA-imported schematics cache symbol definitions that drop properties
KiCad 10 expects (e.g. Device:R cached with 5 properties vs 7 in the library) → 33
lib_symbol_mismatch warnings. No tool existed; only eeschema's GUI action or hand-editing
the cache could fix it. Per project rule "no scripts on KiCad files — only MCP tools".

### Impl
`SymbolUpdater.update_from_library`: resolve each lib_id nickname via the **project**
sym-lib-table (`${KIPRJMOD}` expanded) merged over the **global** sym-lib-table
(discovered from `%APPDATA%/kicad/<ver>/` or `KICAD_CONFIG_HOME`; `${ENV}` expanded);
load the library, deep-copy the `(symbol "Name" ...)`, rename its top id to the full
`Nickname:Name`, and replace the cache entry in place (append if absent). `pruneUnused`
removes `(symbol "Nick:Name" ...)` cache entries whose id isn't used by any instance.
Re-prettified by the central save hook (#28).

**Geometry-safe by default (important).** A blanket refresh is *not* safe: if a library
symbol's pins sit at different positions/lengths than the placed/cached copy, refreshing
moves the pins and every wire/label drawn to the old endpoints dangles. (Seen on this
project: refreshing all 33 mismatches cleared them but spawned 16 unconnected wires + 9
isolated labels — from 4 divergent symbols: AP2112K-3.3, USBLC6-2SC6, Antenna_Shield,
pfp:LSM6DSV32X.) So the tool compares `_pin_signature` (numbers + positions + lengths)
of cache vs library and **skips** any symbol whose pins would move, reporting it under
`skipped_pins_differ`. The bulk (R/C/L/LED/connectors/...) is geometry-identical and
refreshes cleanly. `allowPinChanges=true` forces the eeschema-style full refresh (and you
then own re-wiring the moved pins).

---

## 34. Auto-restart the Python backend after a crash

**Added:** 2026-06-04
**Status:** ✅ local; TS only, needs `npm run build` + reconnect to take effect
**Files:** `src/server.ts`

### What
The KiCAD MCP server spawns KiCad's bundled Python as a long-lived child (it owns the
pcbnew/swig state). If that child died, the server just set `pythonProcess = null` and
every subsequent tool call failed with *"Python process for KiCAD scripting is not
running"* until a manual `/mcp` reconnect. The swig backend crashed repeatedly over a
long session, so each crash meant a manual reconnect + a fresh 1-2 min warm-up.

Now the server **auto-recovers**:
- The spawn + stdio wiring is factored into `spawnPython()` (reused by `start()` and the
  restart path); `resetReadyState()` re-arms the READY handshake promise.
- On child `exit`, `handlePythonExit()` rejects the in-flight request and any queued ones
  with a clear error (callers fail fast instead of hanging until timeout), then — unless
  `stop()` set `intentionalStop` — kicks off `ensureRestart()`.
- `ensureRestart()` respawns, waits for the READY marker, and re-runs the warm-up. It is
  idempotent (concurrent callers share one `restartPromise`) and has a **crash-loop guard**:
  >5 restarts within 2 min aborts with a clear message instead of thrashing.
- `callKicadScript()` now awaits `ensureRestart()` when the backend is down rather than
  rejecting, so the next tool call transparently waits out the respawn.

The MCP STDIO transport is never touched on restart — only the Python child is replaced,
so the client stays connected.

### Crash diagnostics
On every unintended exit, `recordCrash()` appends a JSONL record to
`<server-root>/logs/python-crashes.jsonl` (gitignored): ISO time, exit code, signal, the
command in flight when it died (`lastCommand`, the prime suspect), queue depth, restarts in
the current window, and the last ~40 lines of the child's stderr (where a Python traceback
or C-level pcbnew message surfaces). This is what was missing when the swig backend crashed
mid-session — the Claude Code mcp-logs didn't retain the exit signal. Wrapped best-effort so
logging itself never takes the server down.

### Caveat
A respawn pays the full pcbnew/wxApp warm-up (~1-2 min). A single tool call may exceed the
MCP client's own timeout while recovery runs; the restart still completes and the next call
succeeds.
