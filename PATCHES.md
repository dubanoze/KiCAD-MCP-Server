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

## . set_footprint_3d_model

**Added:** 2026-06-02 · component.py / kicad_interface.py / src/tools/component.ts

Assign/replace a placed footprint's 3D model (FP_3DMODEL). Use when a footprint's bundled
model .step is missing in the install (e.g. USB_C_Receptacle_HRO right-angle) — point it at an
available model such as GCT_USB4105 ...Horizontal.step. Board-mutating (auto-save).
