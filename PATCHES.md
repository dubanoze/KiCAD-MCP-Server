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

---

## 35. New schematic tool: set_schematic_label_orientation

**Added:** 2026-06-04
**Status:** ✅ local; TS+Python, needs `npm run build` + reconnect to expose
**Files:** `python/commands/wire_manager.py`, `python/kicad_interface.py`, `src/tools/schematic.ts`

### What
**set_schematic_label_orientation** — set a net label's rotation (the angle in `(at x y angle)`)
and/or text `justify` (left/right/top/bottom) **without moving it**. Position is preserved, so
wire connectivity is unchanged — only which way the text / global-label flag points changes.

### Why
A connector (Debug_Header_2x4_1.27, J2) rendered 'crooked': left-side local labels (rotation 0,
justify left) ran their text back through the wire stub ("strikethrough"), and right-side GND
global labels (rotation 180, justify right) pointed their flag into the symbol body, overlapping
the pin-name text. The fix is orientation, not position (move would risk connectivity and the
labels were already on their pins). No tool could set label rotation/justify; per the project
rule "no scripts on KiCad files — only MCP tools; add the tool if missing".
Convention: pin-on-left → text left (rotation 180 + justify right); pin-on-right → text right
(rotation 0 + justify left).

### Impl
`WireManager.set_label_orientation`: match the label by name (+ optional position/type),
rewrite `at[3]` (angle) and/or the `(effects (justify ...))` token, leaving coordinates intact.
Re-prettified by the central save hook (#28).

---

## 36. New schematic tool: add_schematic_rectangle

**Added:** 2026-06-04
**Status:** ✅ local; TS+Python, needs `npm run build` + reconnect to expose
**Files:** `python/commands/wire_manager.py`, `python/kicad_interface.py`, `src/tools/schematic.ts`

### What
**add_schematic_rectangle** — add a graphic `(rectangle ...)` to a schematic (start/end in mm,
stroke width, fill). `fill='background'` gives an opaque sheet-background fill that hides
anything drawn behind the box.

### Why
The root sheet carries a hand-drawn block diagram (12 graphic rectangles + 13 polylines +
text). Adding a missing block (an LDO between VBAT and the MCU) needed a new box; only
add_schematic_text existed for the diagram, no tool for graphic rectangles. `background` fill
let the box drop onto the existing VBAT polyline without splitting/deleting it. Per the project
rule "no scripts on KiCad files — only MCP tools; add the tool if missing".

### Impl
`WireManager.add_rectangle` appends `(rectangle (start)(end)(stroke)(fill)(uuid))` before
`(sheet_instances)`. Re-prettified by the central save hook (#28).

---

## 37. New schematic tools: add_schematic_polyline, delete_schematic_shape

**Added:** 2026-06-04
**Status:** ✅ local; TS+Python, needs `npm run build` + reconnect to expose
**Files:** `python/commands/wire_manager.py`, `python/kicad_interface.py`, `src/tools/schematic.ts`

### What
- **add_schematic_polyline** — add a graphic `(polyline (pts ...))` (block-diagram connection
  line; not electrical — use add_schematic_wire for nets).
- **delete_schematic_shape** — delete a graphic shape (rectangle/polyline/circle/arc) matched
  by a reference point (any defining coord — start/end/center or a pts vertex — within tolerance).

### Why
Finishing the block-diagram LDO box (#36): to match the other outline-only blocks instead of
a background-filled box, the VBAT polyline had to be split so it doesn't run under the box —
which needs deleting the old line and routing two new segments. No tools existed for graphic
polylines or for deleting graphic shapes. Per the project rule "no scripts on KiCad files —
only MCP tools; add the tool if missing".

### Impl
`WireManager.add_polyline` appends a `(polyline)` before `(sheet_instances)`;
`WireManager.delete_shape` finds the first matching shape by type + reference coordinate and
removes it. Re-prettified by the central save hook (#28).

---

## 38. Label justify: default to vertically-centered + normalize tool

**Added:** 2026-06-04
**Status:** ✅ local; add_label fix hot-reloads; new tool needs build + reconnect
**Files:** `python/commands/wire_manager.py`, `python/kicad_interface.py`, `src/tools/schematic.ts`

### What
- `WireManager.add_label` no longer appends a `bottom` vertical-justify token — labels are now
  vertically centered on their wire (KiCad centers when top/bottom is absent).
- **normalize_schematic_label_justify** — strip top/bottom from every existing label's justify
  on a sheet (one-shot sweep to center labels added before the fix).

### Why
add_label hard-coded `(justify <h> bottom)`, which floats label text above the wire; it reads
as misaligned (visible at the CN3163 charger node and the BT1 battery labels). User feedback:
labels should be vertically centered. 35 labels across the sheets carried the stray `bottom`.

### Impl
Drop `Symbol("bottom")` from the add_label effects. `normalize_label_justify` rewrites each
label's `(justify ...)` keeping only non-vertical tokens. Re-prettified by the save hook (#28).

---

## 39. New schematic tools: add_hierarchical_sheet + repair_subsheet_instances

**Added:** 2026-06-04
**Status:** ✅ local; TS+Python, needs `npm run build` + reconnect to expose
**Files:** `python/commands/wire_manager.py`, `python/kicad_interface.py`, `src/tools/schematic.ts`

### What
- **add_hierarchical_sheet** — author an (empty) sub-sheet .kicad_sch and add its `(sheet ...)`
  symbol on the parent/root. The sheet symbol is **cloned from an existing one** on the root
  (guaranteed-correct property format); only name/file/uuid/position/size are rewritten.
  Returns sheet_uuid / subsheet_uuid / root_uuid.
- **repair_subsheet_instances** — add the hierarchical instance path
  `(project "<root>" (path "/<root-uuid>/<sheet-uuid>" (reference)(unit)))` to every symbol on
  a sub-sheet (deriving the uuids by matching the subsheet filename to a `(sheet)` on the root).

### Why
Adding a new domain sheet (Storage, for the data-log flash) needs a hierarchical sheet, and
`add_schematic_component` writes only the **standalone** instance path on a sub-sheet — so
kicad-cli netlist emits no pins for those components in the full hierarchy (known footgun, see
project memory). These two tools make creating a sheet + getting connectivity right a pure-MCP
operation. Per the rule "no scripts on KiCad files — only MCP tools; add the tool if missing".

### Impl
`WireManager.add_hierarchical_sheet` deep-copies a template `(sheet)`, rewrites the fields, and
authors a minimal subsheet (`(kicad_sch ... (lib_symbols) (sheet_instances (path "/" (page "1"))))`).
`WireManager.repair_subsheet_instances` appends the hierarchical project block to each symbol's
`(instances)`. Re-prettified by the central save hook (#28). Verify with a netlist component/pin
count after use.

## 40. New schematic tool: set_component_dnp

### What
`set_component_dnp(schematicPath, reference, dnp=true, inBom?)` — sets the
`(dnp yes|no)` attribute on a placed symbol (optionally `(in_bom ...)` too).

### Why
striq audit decision: keep crystal load-cap footprints as a tuning option but
exclude them from assembly (C7/C9/C12/C13), plus XM7 antenna shunt → DNP.
No existing tool could touch symbol attributes (edit_schematic_component only
handles text properties).

### Impl
- `python/commands/wire_manager.py`: static `set_component_dnp` — sexpdata pass
  over top-level placed `(symbol ...)` blocks, match by `(property "Reference")`,
  rewrite/insert the `(dnp ...)` token after `(on_board ...)`.
- `python/kicad_interface.py`: dispatch `set_component_dnp` → `_handle_set_component_dnp`.
- `src/tools/schematic.ts`: zod schema + registration.

## 41. add_board_cutout / delete_pcb_shape: live-GUI bridge + KiCad 10 LSET fix

### What
1. `kicad_interface.py`: added `add_board_cutout` and `delete_pcb_shape` to
   `_BOARD_MUTATING_COMMANDS` so the dual-backend live-GUI bridge engages
   (GUI flush -> SWIG edit on fresh board -> auto-save -> GUI reload).
2. `commands/board/outline.py` (`delete_pcb_shape`): zone layer filter used
   `LSET.test()`, removed in KiCad 10 — now resolves `Contains()` with a
   `test()` fallback for older APIs.

### Why
With pcbnew open over IPC, both tools silently edited the stale file-backed
SWIG board: "success" was reported, but nothing reached disk or the GUI
(striq motor-slot cutout vanished twice). The bridge predicate only engages
for commands listed in `_BOARD_MUTATING_COMMANDS` / `_SWIG_SELF_SAVING_COMMANDS`,
and these two were in neither. The LSET crash surfaced right after: nearest-shape
search also walks zones (rule areas), and `GetLayerSet().test()` raises
AttributeError on KiCad 10, failing the whole command.

### Impl notes
- Bridge membership is enough — no per-tool code changes needed for (1).
- Found via `~/.kicad-mcp/logs/kicad_interface.log` traceback.
- Caveat observed while testing: KICAD_MCP_HOTRELOAD reloading command handlers
  after an on-disk edit dehydrated the SWIG session ("name 'pcbnew' is not
  defined" from LoadBoard); requires a backend restart. Known issue, see #TODO.

## 42. add_board_cutout: edge-slot merge into the outline

### What
`add_board_cutout` now detects when the cutout polygon crosses the existing
board outline and, instead of overlaying a closed `gr_poly` (which makes the
outline self-intersecting -> DRC "malformed outline"), embeds the slot into
the outline: the crossed straight Edge.Cuts segment is split at the two
crossing points and the interior chain of polygon vertices is stitched in as
`gr_line` segments. Falls back to the old closed-poly behaviour for true
window cutouts (no crossing), or for ambiguous geometry (crosses arcs, more
than one segment, !=2 intersections). Result reports `mode: edge_slot|window`.

### Why
striq motor slot: an edge slot for a cylindrical ERM motor on the board edge.
The old overlay produced DRC errors: "Board has malformed outline
(self-intersecting)" x2 + copper_edge_clearance noise.

### Impl
`outline.py`: `_try_merge_edge_slot(pts_nm)` — pure-python segment
intersection (param form), interior-side test via board bbox centre sign,
chain selection with complementary fallback, zero-length stub suppression
(1 µm eps). Original segment width preserved.

## 43. Hot-reload: mtime gate + dehydration note

### What
`_maybe_hot_reload` reloads command modules only when some `commands/*.py`
mtime actually advanced (baseline recorded on first call), instead of
purging+reimporting on EVERY command.

### Why
Unconditional reload wasted time and was observed to dehydrate live SWIG
proxies mid-session (`GetDrawings -> 'SwigPyObject' object is not iterable`,
`LoadBoard -> name 'pcbnew' is not defined`), forcing MCP reconnects. Note:
reload after a real edit can still dehydrate the loaded board — re-run
open_project (handler instances are only re-created there) or restart the
backend after editing python command files.

## 44. New board tool: add_edge_cut_line

### What
`add_edge_cut_line(x1,y1,x2,y2, layer?="Edge.Cuts", width?=0, unit?="mm")` —
adds a single straight graphic segment on a layer (default Edge.Cuts).

### Why
striq: converting the motor edge-slot into a fully-enclosed internal window
required restoring a straight left board edge after delete_pcb_shape removed
the slot detour. No existing tool could add a single open Edge.Cuts segment:
add_board_outline only draws closed shapes (>=3 pts), add_board_cutout draws
closed polygons. Redrawing the whole outline would mean deleting ~30 segments
one-by-one. A one-segment primitive is the right tool and broadly reusable for
outline patching.

### Impl
- outline.py: `add_edge_cut_line` — PCB_SHAPE SHAPE_T_SEGMENT, layer by name
  (GetLayerID), width 0 = hairline (canonical Edge.Cuts).
- board/__init__.py: delegate. kicad_interface.py: dispatch + added to
  _BOARD_MUTATING_COMMANDS (auto-save + live-GUI bridge).
- board.ts: zod schema + registration. Requires `npm run build` + /mcp
  reconnect (NEW tool → node must re-register; python-only restart is not
  enough).

## 45. add_board_cutout keepout clearance + retry double-apply fix

### What
1. add_board_cutout: the keepout rule area now carries an OUTWARD clearance —
   when keepout_clearance>0 the keepout is the cutout bbox inflated by that
   amount (a rectangle; a keepout need not match the chamfered cutout). A rule
   area has no implicit gap, so without this copper fills right to the cutout
   edge (0 mm) and trips the board copper-to-edge rule (e.g. 0.5 mm).
2. Dispatcher SWIG-dehydration handler no longer auto-re-runs the handler:
   it rehydrates the board from disk and returns a "re-issue" failure. Auto
   re-running double-applied mutating commands that had already persisted
   before a late refresh/save raised (observed: 2 identical Edge.Cuts cutouts
   + duplicate outline segments).

### Why
striq vibro-motor internal window: copper_edge_clearance DRC at the window
edge; and earlier duplicate geometry from the retry path.

### Impl
- outline.py add_board_cutout: keepout outline = inflated bbox rect.
- kicad_interface.py _dispatch_command: rehydrate-only on SwigPyObject error.

### KNOWN ENV HAZARD (not a code bug)
Multiple MCP node servers (multiple Claude sessions / repeated /mcp reconnects
without old node exit) share one .kicad_pcb. Their python backends' auto-saves
clobber each other — a stale-state writer overwrites a correct result. Symptom:
"Auto-save refused: disk changed externally", and on-disk geometry reverting to
an older shape. Fix is operational: keep the board open in exactly ONE session.

## 46. New tool: set_impedance_control (stackup dielectric_constraints flag)

### What
`set_impedance_control(enabled=true, boardPath?)` — toggles the board stackup's
`(dielectric_constraints yes|no)` flag (the "Impedance controlled" checkbox) in
the .kicad_pcb. Surgical one-token regex edit that PRESERVES the existing stackup
dielectrics (unlike set_stackup, which regenerates the whole block and hard-codes
`no`). Backup (.impedance.bak) + paren-balance guard.

### Why
striq RF: the 2.4GHz ANT_RF feed needs the board marked impedance-controlled so
JLCPCB compensates the geometry to 50 ohm and it is exported in fab data. The
existing set_stackup could only write `dielectric_constraints no` and would have
clobbered the carefully-set 0.20mm prepreg / Er4.6 dielectrics if used to flip it.

### Impl
- python/kicad_interface.py: `_handle_set_impedance_control` + dispatch.
  File-based text edit (no SWIG stackup API exists), mirrors set_stackup's
  read/backup/paren-check/write pattern; records board signature after.
- src/tools/design-rules.ts: zod schema + registration. registry.ts: listed under 'drc'.
- Requires `npm run build` + /mcp reconnect (NEW tool -> node must re-register).

### Note
Custom DRC width rule for the RF net is authored as a project `<name>.kicad_dru`
file (not in the .kicad_pcb/.kicad_pro protected set) — a plain text rules file
KiCad reads at DRC time; written directly.

## 47. modify_trace: traceUuid param + auto-save

### What
1. `commands/routing.py modify_trace`: read the trace id from `traceUuid`
   (the name the TS tool actually sends) as well as legacy `uuid`. It was only
   reading `uuid`, so every call failed "Missing trace identifier".
2. Added `modify_trace` to `_BOARD_MUTATING_COMMANDS` so width/layer/net edits
   auto-save (SWIG board mutation was otherwise lost on the next reload).

### Why
striq: bulk-fix the RF_ANT_IN antenna-feed segments from a stale 0.20mm to the
RF net-class 0.34mm (50 ohm). modify_trace by UUID was unusable due to the param
name mismatch.

## 48. New tool: fillet_trace (round a track corner with a tangent arc)

### What
`commands/routing.py fillet_trace` + dispatch + `_BOARD_MUTATING_COMMANDS` +
`src/tools/routing.ts` schema. Rounds the corner between two connected straight
track segments:
- finds the true corner **vertex by intersecting the two segment lines**, so it
  works even when the segments meet *through a pad* or with a sub-0.05mm
  mis-alignment — exactly the cases where KiCad's native "Fillet Tracks" aborts
  with the opaque "Unable to fillet the selected track segments";
- trims each segment's near endpoint back to the tangent point and inserts a
  `PCB_ARC` (start/mid/end) tangent to both legs, preserving width/net/layer;
- handles arbitrary corner angles (not just 90°): tangent distance
  `t = R / tan(theta/2)`, arc-centre on the bisector at `R / sin(theta/2)`;
- when the requested radius does not fit the shorter leg it returns
  `success:false` **with `maxRadius`** (the largest feasible radius) and
  `cornerAngleDeg`, instead of a silent failure.

Identify the corner by `segment1Uuid` + `segment2Uuid`, or by a `corner`
{x,y,unit} point (optionally `net`-filtered) that auto-selects the two nearest
segments. Guards: same layer, same net, non-collinear, non-zero legs.

Note `modify_trace` still only edits width/layer/net (no endpoint move) — corner
trimming is done inside `fillet_trace` via `SetStart`/`SetEnd` on the matched
`PCB_TRACK`, which is why a separate tool was added rather than extending
`modify_trace`.

### Why
striq: smooth the RF feed corners (e.g. FL_OUT 90° bend right after the filter
FL1). The vertical leg is only ~1.31mm, so KiCad refused a 2mm (79mil) fillet
with no explanation; fillet_trace reports the real ceiling (~1.0mm here) and
lays a clean controlled-width arc — important for 2.4GHz microstrip where sharp
90° corners cause impedance discontinuity / reflection.

## 49. route_trace: robust net resolution (GetNetItem, not NetsByName)

### What
`commands/routing.py route_trace` resolved the net via
`board.GetNetInfo().NetsByName()` + `nets_map.has_key(net)`. On some KiCad 10
SWIG builds `NetsByName()` returns a proxy whose `.has_key()` either raises
`'SwigPyObject' object has no attribute 'NetsByName'` (dehydrated board) or
hard-crashes the Python backend (segfault on a freshly-rehydrated board).
Switched to `GetNetInfo().GetNetItem(net)` — the same direct lookup that
`modify_trace` and `fillet_trace` already use successfully — and return a clean
"Invalid net" error instead of crashing when the net is missing.

### Why
striq: rerouting the HSE crystal net X32MO (delete_trace + 5x route_trace) hard-
crashed the backend on every route_trace until the net lookup was changed. With
GetNetItem the same 5 segments routed first-try in SWIG mode.

## 50. New tool: add_keepout_zone (rule-area / placement keepout)

### What
`add_keepout_zone` — `_handle_add_keepout_zone` + command_routes + _SWIG_SELF_SAVING
+ `src/tools/board.ts` schema + registry. Creates a named **rule-area** ZONE
(`SetIsRuleArea(True)`) with configurable doNotAllow flags
(footprints/tracks/vias/pads/copperpour), multi-layer (default all 4 Cu), NOT
filled (no ZONE_FILLER — avoids the swig fill segfault), self-saves.

`add_zone` only makes filled copper pours (`SetIsRuleArea(False)` hard-coded), so
there was no way to place a keepout via MCP. Default flags = component-placement
keepout: footprints FORBIDDEN, everything else allowed. doNotAllow setters are
called through a guard that errors loudly if a method name is missing (rather
than silently no-opping the flag). LSET built via AddLayer with fallbacks.

### Why
striq: antenna clearance boundary — "no components may intrude around the niche
antenna, but GND stitching vias are still allowed there." Was an open TODO in
hardware/antenna/ANE-niche-antenna-notes.md ("Добавить add_keepout_zone").

## 51. CRITICAL data-loss fix: empty symbol instance path (path "/") segfaults KiCad 10

### What
`create_component_instance` (commands/dynamic_symbol_loader.py) wrote every added
symbol's instance block as `(project "project" (path "<instance_path>" ...))` where:
  - the project name was the hard-coded placeholder `"project"`, and
  - `instance_path` was correct only for ROOT-sheet symbols (`/<root-uuid>`); for a
    SUB-SHEET it grabbed that sub-sheet file's OWN top-level uuid, and it fell back
    to a bare `"/"` whenever the uuid regex missed.

A bare `(path "/")` inside a symbol's `(instances ...)` is a malformed KIID_PATH:
KiCad 10's schematic serializer dereferences null in `KIID::operator<` and
**segfaults**, truncating the `.kicad_sch` to **0 bytes** on save / `kicad-cli sch
upgrade`. Reproduced here: a symbol with `path "/"` → `kicad-cli sch upgrade
--force` exits `0xC0000005` (3221225477) and zeroes the file.

Added a resolver `_resolve_instance_context(schematic_path) -> (project_name,
instance_path)` plus helpers `_read_top_uuid` / `_find_sheet_uuid`:
  - project_name = the sibling `.kicad_pro` stem (what real eeschema writes), via
    `self.project_path`; falls back to the schematic stem.
  - instance_path:
      * root sheet → `/<root-sheet-uuid>`
      * sub-sheet  → `/<root-uuid>/<sheet-object-uuid>` (sheet uuid resolved by
        matching the sub-sheet filename against each root `(sheet)`'s `Sheetfile`
        property — read-only sexpdata parse of the ROOT only, so the module's
        "no sexpdata writes" formatting rule is preserved)
      * never returns a bare `/` — last-resort fallback synthesizes a uuid so a
        save can never zero the file.
Also fixed `WireManager.repair_subsheet_instances` (commands/wire_manager.py):
`proj_name` was hard-coded `"striq"` (the "overridden below" comment was a lie —
it never was), which would corrupt hierarchy resolution on any OTHER project.
Now derived from the root's sibling `.kicad_pro` stem.

Note: `(path "/" (page "1"))` inside `(sheet_instances ...)` is the LEGITIMATE
root-sheet form and is untouched — only SYMBOL instance paths were the bug.

### Why
striq: schematics generated by the server segfaulted eeschema (and `kicad-cli sch
upgrade`) and got zeroed on save — 3x data loss before the manual
`repair_subsheet_instances` workaround. This fixes the root cause at creation
time so generated schematics are hierarchy-correct out of the box. Surfaced while
prepping a SECOND project on the shared server, where the `"striq"` / `"project"`
hard-codes would have produced wrong-project instance paths.

### Verify
- Negative control: a `path "/"` symbol → `kicad-cli sch upgrade --force` =
  exit 0xC0000005, file → 0 bytes (bug reproduced).
- Fixed code on a root + one sub-sheet: root symbol path `/<root>`, sub-sheet
  symbol path `/<root>/<sheet>`, project name = `.kicad_pro` stem, no bare `/`;
  `kicad-cli sch upgrade --force` exits 0 on both, files intact.
- Python-only change → no `npm run build`; `/mcp` reconnect to load it.

---

## 52. `add_hierarchical_sheet`: subfolder Sheetfile + duplicate page number

**Added:** 2026-06-17
**Status:** ✅ local patch (tag `SER2RJ45`); candidate for upstream PR
**File:** `python/commands/wire_manager.py`
**Tests:** `tests/test_add_hierarchical_sheet.py` — 4 tests, all pass; existing
`test_hierarchy_tools.py` / `test_add_wire_sub_sheet.py` (33) still pass.

### What
Two fixes in `WireManager.add_hierarchical_sheet` (+ one in
`repair_subsheet_instances`):

1. **Sheetfile is now relative to the root's directory, not the bare basename.**
   `sheet_file_rel = os.path.relpath(subsheet_path, root.parent)` (POSIX slashes).
   Previously `Path(subsheet_path).name` → a subsheet in `Sheets/` was written as
   `(property "Sheetfile" "Foo.kicad_sch")`, so KiCad could not find it and the
   sheet rendered **empty** in the hierarchy. `repair_subsheet_instances` now
   matches Sheetfile by **basename** so it still resolves the sheet.

2. **The new sheet gets a unique page number.** The `(sheet)` symbol is
   `deepcopy`'d from an existing one, so it inherited that sheet's
   `(instances … (page "N"))` verbatim → two sheets claimed the same page.
   Now: `page = max(existing sheet pages) + 1`.

### Why
On SER2RJ45 (hierarchical project, subsheets in `Sheets/`): adding an `Overview`
sheet produced `Sheetfile "Overview.kicad_sch"` (no `Sheets/` prefix) → the page
rendered blank until the root was hand-fixed; and the new sheet was assigned the
same page number as `Power` (both "2"). Both are creation-time defects that every
hierarchical project hits.

### Verify
- `tests/test_add_hierarchical_sheet.py`:
  `python -m pytest tests/test_add_hierarchical_sheet.py -o addopts=""` → 4 passed.
- Manual: add a sheet whose file is in a subfolder → root gets
  `"Sheetfile" "Sheets/<name>.kicad_sch"` and a page number not used by any
  sibling sheet.
- Python-only change → no `npm run build`; `/mcp` reconnect to load it.

---

## 53. `find_overlapping_elements`: detect overlapping field/label TEXT

**Added:** 2026-06-17
**Status:** ✅ local patch (tag `SER2RJ45`); candidate for upstream PR
**File:** `python/commands/schematic_analysis.py`
**Tests:** `tests/test_text_overlap_detection.py` — 4 tests, all pass; full
schematic-analysis/hierarchy suite (121) still passes.

### What
`find_overlapping_elements` previously only checked symbol bounding boxes,
label ANCHOR proximity, and wire collinearity — it never looked at the visible
TEXT of reference/value fields, labels, or notes. So it reported `0 overlaps`
on sheets whose refdes/value text and net labels are clearly printed on top of
each other (the dominant readability problem on auto-generated schematics).

Added `_parse_visible_text()` (refdes/value fields unless hidden, label /
global_label / hierarchical_label, graphic `text`) with an approximate
stroke-font bbox (`_text_bbox`, ~0.72*size/glyph) that **honors horizontal
justify** (left/right text extends the correct way; center is the default), and
a new pairwise AABB check. Honoring justify matters: flipping a net label's
justify outward (the standard fix for two labels meeting at a symbol) genuinely
separates them, and the detector now reflects that instead of false-flagging. Two fields of the SAME symbol (Reference next to its Value)
share an `owner` and are excluded. Result now includes `overlappingText[]` and
counts it in `totalOverlaps`.

### Why
On SER2RJ45 the tool returned 0 on visibly-messy sheets, so it could not drive
layout QA. With the fix it reports the real counts (LED 17, Power 49,
Ethernet 44, Serial 60, MCU-root 98 text/symbol overlaps) — a usable signal to
minimize while tidying with `move_schematic_component` /
`normalize_schematic_label_justify`.

Also refined the SYMBOL overlap check: `_compute_symbol_bbox_direct(..,
body_only=True)` compares the drawn body rectangles (graphics only, pins
excluded) instead of the pin-extended bbox. This kills the false positives
where a part sitting next to a chip's pin, or a power symbol on a pin, read as
"overlapping" — e.g. Ethernet symbol overlaps 6→0, Power 7→2, Serial 20→4,
leaving only genuinely-stacked symbols (two #PWR at d=0.9, caps 2.5 mm apart).

### Verify
- `python -m pytest tests/test_text_overlap_detection.py -o addopts=""` → 5 passed
  (overlap detected; same-symbol pair excluded; hidden field ignored; justify
  separation; well-spaced clean).
- Read-only, additive output key → backward compatible.
- Python-only change → no `npm run build`; `/mcp` reconnect to load it.

---

## 54. New tool: `auto_resolve_field_overlaps` (tidy schematic text)

**Added:** 2026-06-17
**Status:** ✅ local patch (tag `SER2RJ45`); candidate for upstream PR
**Files:** `python/commands/schematic_analysis.py` (`plan_field_deconflict`),
`python/kicad_interface.py` (`_handle_auto_resolve_field_overlaps` + dispatch),
`python/schemas/tool_schemas.py` (schema). **TS layer not yet wired** — callable
from Python/handler now; add to `src/tools/schematic.ts` + `npm run build` to
expose over MCP stdio.

### What
Connectivity-safe auto-tidy for the dominant readability problem on generated
sheets: reference/value field text and net labels printed on top of each other.
`plan_field_deconflict` (read-only) iteratively plans two safe operations —
move a component Reference/Value FIELD to the side of its symbol, and flip a net
label's horizontal justify outward — simulating with the justify-aware bbox until
no field/label text overlaps remain. The handler applies the plan via the
existing `edit_schematic_component` (field positions) and
`set_schematic_label_orientation` (justify) paths, so wires/pins/net-names/
instances are never touched. Supports `dryRun` and `maxRounds`.

### Why
SER2RJ45 sheets had 40–60 text overlaps each from dense auto-placement. Manual
per-field moves would be 150+ tool calls. This resolves a whole sheet in one
call. Live results (text overlaps): LED 17→0, Power 41→0, Ethernet 37→0,
Serial 41→0; full netlist unchanged at 379 components; format 20260306 preserved.

### Limitations / next
- Handles field↔label / field↔field TEXT overlaps. It does NOT move components
  (symbol-body overlaps) or relocate dense clusters — those need
  `move_schematic_component`.
- `find_overlapping_elements` symbol-overlap check still over-reports power
  symbols sitting on a pin and small parts within a large chip's bbox; refining
  that (exclude pin-attached power symbols; body-rectangle vs full bbox) is a
  good follow-up so the symbol metric is as trustworthy as the text metric.

### Verify
- `dryRun` returns the planned moves; applied run reports `overlapsBefore/After`.
- Python-only change → no `npm run build` for the Python path; `/mcp` reconnect
  to load. Full MCP-stdio exposure needs the TS registration + build.

## #55 — add_hierarchical_sheet: strip cloned sheet pins (wire_manager.py)

`add_hierarchical_sheet` deep-copies an existing (sheet ...) symbol from the root
as a format template, then rewrites name/file/uuid/size/page. But it left the
template's inherited `(pin ...)` entries in place — the clone of another sub-sheet
carried that sheet's pins at their original fixed coordinates, so the new sheet
got duplicate/overlapping sheet pins (e.g. USART_RX at (70,180)) → corrupted
hierarchy. Docstring already promised "no sheet pins". Fix: after deepcopy, drop
all `(pin ...)` children so a new sub-sheet starts empty; pins added later via
add_sheet_pin. Verified: new MCU sheet has 0 pins, netlist intact (113 nets),
kicad-cli upgrade canary OK.

## #56 — move_components_to_sheet: cross-sheet component relocation (NEW tool)

Refactor a flat root schematic into a clean container with components on sub-sheets.
Relocates component instances + the net labels / power symbols attached to their pins from
a source sheet to a target sheet; copies any missing lib_symbols into the target; repairs
hierarchical instance paths (reuses repair_subsheet_instances) so kicad-cli emits the moved
pins. Nets entirely WITHIN the moved set stay intact (their labels move too); CROSS-sheet
signals become local on the target and must be re-exposed by the caller (hierarchical
labels + sheet pins + root nets).

Files: python/commands/wire_manager.py (move_components_to_sheet),
python/kicad_interface.py (_handle_move_components_to_sheet + dispatch),
src/tools/schematic.ts (tool def) + dist/tools/schematic.js (tsc build).

Validated offline with KiCad's python on SER2RJ45: moved 22 MCU-domain components
(U1 + crystals + decoupling + PHY power) root -> MCU sub-sheet; root emptied to a pure
sheet container (0 direct symbols). 45 symbols (incl. #PWR) + 63 labels relocated; intra-
group nets intact on the sub-sheet (HSE_IN={C13,U1.5,Y1.1}, LSE, BOOT0={R2.1,U1.63},
NRST={C12,R1.2,SW1.1,U1.7}); power crosses via globals (+3V3 37 nodes / GND 62); U1
instance path /<root>/<sheet>; kicad-cli upgrade canary SAVEABLE.

NOTE: a NEW tool — the MCP (Node) server must be RESTARTED to advertise it to clients
(hot-reload covers only python command handlers, not the TS tool registry).

## #57 — relocate_labels_to_stubs: flush labels -> stub-wire style (schematic rule)

Project rule (striq): labels go on a short stub wire ~2.54mm out from the pin, NOT flush
against it (flush global flags overlap the symbol body + pin names — "doubled labels").
New tool: per sheet, every net/global/hierarchical label sitting on a component pin gets a
stub wire extending outward (direction from PinLocator.get_pin_angle) and is moved to the
stub end, oriented outward. Connectivity preserved (stub joins pin<->label, net by name).
Collision guard: a stub end that coincides with another stub end or a pin (e.g. crystal
pins facing each other -> would short two nets) is left flush.

Files: wire_manager.py (relocate_labels_to_stubs), kicad_interface.py (handler+dispatch),
src/tools/schematic.ts (+dist). Validated offline on SER2RJ45: 203 labels relocated across
5 sheets, 4 crystal labels skipped, netlist identical (113 nets 1:1), canary SAVEABLE.
NEW tool -> needs MCP (Node) restart to advertise.

## #57b — relocate_labels_to_stubs: correct outward direction + justify (fix)

Two bugs in #57 found on U1 (CH32V317WCU6, 68-pin): (1) direction used
get_pin_angle, which returns the pin's draw angle (often INTO the body) → stubs/
labels were pushed over the symbol; and corner pins picked the wrong axis. Now the
outward direction is the nearest pin-bbox EDGE of the symbol (left/right/top/bottom;
2-pin inline parts handled by their axis). (2) the moved label kept justify "left",
so left/down labels rendered their text back over the body — now justify follows
orientation (right for 180/270, left for 0/90), same rule as add_schematic_net_label.
Re-validated: U1 left+right labels sit cleanly outside the symbol, netlist 113 1:1,
MCU skips 11→2.

## #58 — advertise auto_resolve_field_overlaps to the client (TS schema)

The connectivity-safe field/label de-overlap handler existed in the Python dispatch
(_handle_auto_resolve_field_overlaps) but had no TS tool definition, so clients could
not call it. Added the server.tool() schema (schematicPath, dryRun?, maxRounds?) +
dist build. Used to tidy Serial/Ethernet/LED/Power after the hierarchy refactor +
stub relocation re-laid the labels.

## #58b — auto_resolve_field_overlaps: add fieldsOnly mode

The label-flip step (set_schematic_label_orientation) moved net labels that sit on stub
wires off their stubs → broke connectivity (charge-pump caps, center-tap bias, COMP_RC).
Added a fieldsOnly param: when true, only component value/ref fields are repositioned;
net-label flips are skipped (labels are already oriented by relocate_labels_to_stubs).
Connectivity-safe for the stub-relocated sheets.

## #59 — hide_power_references: hide #PWRxx ref designators (cosmetic)

Power symbols were added with their reference (#PWR301…) visible — non-standard clutter
(power symbols are identified by their graphic, not the ref). New tool hides the Reference
field on every power symbol of a sheet in one call ((hide yes) into the Reference effects).
Cosmetic only, netlist unchanged. Saves ~20 per-symbol edit_schematic_component calls/sheet.
