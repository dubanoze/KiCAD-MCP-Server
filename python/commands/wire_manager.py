"""
Wire Manager for KiCad Schematics

Handles wire creation using S-expression manipulation, similar to dynamic symbol loading.
kicad-skip's wire API doesn't support creating wires with standard parameters, so we
manipulate the .kicad_sch file directly.
"""

import logging
import math
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

# Module-level Symbol constants — avoids repeated allocation on every call
_SYM_WIRE = Symbol("wire")
_SYM_PTS = Symbol("pts")
_SYM_XY = Symbol("xy")
_SYM_AT = Symbol("at")
_SYM_LABEL = Symbol("label")
_SYM_GLOBAL_LABEL = Symbol("global_label")
_SYM_HIERARCHICAL_LABEL = Symbol("hierarchical_label")
_SYM_STROKE = Symbol("stroke")
_SYM_WIDTH = Symbol("width")
_SYM_TYPE = Symbol("type")
_SYM_UUID = Symbol("uuid")
_SYM_SHEET_INSTANCES = Symbol("sheet_instances")
_SYM_JUNCTION = Symbol("junction")
_SYM_LIB_SYMBOLS = Symbol("lib_symbols")
_SYM_LIB_ID = Symbol("lib_id")
_SYM_MIRROR = Symbol("mirror")
_SYM_PIN = Symbol("pin")
_SYM_SYMBOL = Symbol("symbol")
_SYM_UNIT = Symbol("unit")
_IU_PER_MM = 10000


def _find_insertion_point(content: str) -> int:
    """Find the right place to insert new elements in a .kicad_sch file.

    Looks for (sheet_instances (KiCad 8) first, falls back to inserting
    before the final closing paren (KiCad 9+).
    """
    marker = "(sheet_instances"
    pos = content.rfind(marker)
    if pos != -1:
        return pos
    pos = content.rfind(")")
    if pos == -1:
        raise ValueError("Could not find insertion point in schematic")
    return pos


def _text_insert(file_path: Path, sexp_text: str) -> bool:
    """Insert S-expression text into a .kicad_sch file preserving formatting."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    insert_at = _find_insertion_point(content)
    content = content[:insert_at] + sexp_text + content[insert_at:]

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def _make_hierarchical_label_text(
    text: str,
    position: List[float],
    shape: str = "bidirectional",
    orientation: int = 0,
) -> str:
    """Generate a hierarchical_label S-expression as formatted text.

    orientation: 0=right (label points right, justify left),
                 180=left (label points left, justify right),
                 90/270=vertical.
    """
    uid = str(uuid.uuid4())
    justify = "right" if orientation == 180 else "left"
    return (
        f'\t(hierarchical_label "{text}"\n'
        f"\t\t(shape {shape})\n"
        f"\t\t(at {position[0]} {position[1]} {orientation})\n"
        f"\t\t(effects\n"
        f"\t\t\t(font\n"
        f"\t\t\t\t(size 1.27 1.27)\n"
        f"\t\t\t)\n"
        f"\t\t\t(justify {justify})\n"
        f"\t\t)\n"
        f'\t\t(uuid "{uid}")\n'
        f"\t)\n"
    )


def _make_sheet_pin_text(
    pin_name: str,
    pin_type: str,
    position: List[float],
    orientation: int = 0,
) -> str:
    """Generate a sheet pin S-expression as formatted text (indented for inside sheet block).

    orientation: 0=right side of sheet box, 180=left side.
    """
    uid = str(uuid.uuid4())
    justify = "left" if orientation == 0 else "right"
    return (
        f'\t\t(pin "{pin_name}" {pin_type}\n'
        f"\t\t\t(at {position[0]} {position[1]} {orientation})\n"
        f'\t\t\t(uuid "{uid}")\n'
        f"\t\t\t(effects\n"
        f"\t\t\t\t(font\n"
        f"\t\t\t\t\t(size 1.27 1.27)\n"
        f"\t\t\t\t)\n"
        f"\t\t\t\t(justify {justify})\n"
        f"\t\t\t)\n"
        f"\t\t)\n"
    )


class WireManager:
    """Manage wires in KiCad schematics using S-expression manipulation"""

    # Regex to parse sub-unit names like "LM324_2_1" → (base="LM324", unit=2, style=1)
    # The sub-unit suffix is <base>_<unit>_<style> where unit and style are integers.
    # Assumes KiCad's <base>_<unit>_<style> convention (rightmost two underscore-separated numeric groups are unit/style); unparseable names fall back to including all pins via the else branch in _parse_lib_pins.
    _SUB_UNIT_RE = re.compile(r"^(.+)_(\d+)_(\d+)$")

    @staticmethod
    def add_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """
        Add a wire to the schematic using S-expression manipulation

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            stroke_width: Wire width (default 0 for standard)
            stroke_type: Stroke type (default, solid, dashed, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Break any existing wire that passes through a new endpoint (T-junction support)
            for pt in (start_point, end_point):
                splits = WireManager._break_wires_at_point(sch_data, pt)
                if splits:
                    logger.info(f"Broke {splits} wire(s) at new wire endpoint {pt}")

            # Create wire S-expression
            # Format: (wire (pts (xy x1 y1) (xy x2 y2)) (stroke (width N) (type default)) (uuid ...))
            wire_sexp = WireManager._make_wire_sexp(
                start_point, end_point, stroke_width, stroke_type
            )

            # Find insertion point (before sheet_instances on the root sheet,
            # or appended to the end on a hierarchical sub-sheet which has no
            # sheet_instances block).
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                # Sub-sheets in hierarchical designs don't have (sheet_instances).
                sheet_instances_index = len(sch_data)

            # Insert wire before sheet_instances (or at end for sub-sheets)
            sch_data.insert(sheet_instances_index, wire_sexp)
            logger.info(f"Injected wire from {start_point} to {end_point}")

            WireManager.sync_junctions(sch_data)

            # Write back
            with open(schematic_path, "w", encoding="utf-8") as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added wire to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_polyline_wire(
        schematic_path: Path,
        points: List[List[float]],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """
        Add a multi-segment wire (polyline) to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            points: List of [x, y] coordinates for each point in the path
            stroke_width: Wire width
            stroke_type: Stroke type

        Returns:
            True if successful, False otherwise
        """
        try:
            if len(points) < 2:
                logger.error("Polyline requires at least 2 points")
                return False

            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Break any existing wire at the outer endpoints of the new path
            for pt in (points[0], points[-1]):
                splits = WireManager._break_wires_at_point(sch_data, pt)
                if splits:
                    logger.info(f"Broke {splits} wire(s) at new polyline endpoint {pt}")

            # KiCAD wire elements only support exactly 2 pts each.
            # Split N waypoints into N-1 individual wire segments.
            wire_sexps = [
                WireManager._make_wire_sexp(points[i], points[i + 1], stroke_width, stroke_type)
                for i in range(len(points) - 1)
            ]

            # Find insertion point (before sheet_instances on the root sheet,
            # or appended to the end on a hierarchical sub-sheet which has no
            # sheet_instances block).
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                # Sub-sheets in hierarchical designs don't have (sheet_instances).
                sheet_instances_index = len(sch_data)

            # Insert all segments (in reverse so order is preserved after inserts)
            for wire_sexp in reversed(wire_sexps):
                sch_data.insert(sheet_instances_index, wire_sexp)
            logger.info(
                f"Injected {len(wire_sexps)} wire segments for {len(points)}-point polyline"
            )

            WireManager.sync_junctions(sch_data)

            # Write back
            with open(schematic_path, "w", encoding="utf-8") as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added polyline wire to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding polyline wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_label(
        schematic_path: Path,
        text: str,
        position: List[float],
        label_type: str = "label",
        orientation: int = 0,
    ) -> bool:
        """
        Add a net label to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            text: Label text (net name)
            position: [x, y] coordinates for label
            label_type: Type of label ('label', 'global_label', 'hierarchical_label')
            orientation: Rotation angle (0, 90, 180, 270)

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Orientation-aware justify: KiCAD flips horizontal alignment for 180°/270°.
            # Horizontal token only -> vertically centered on the wire (KiCad has no
            # explicit 'center' token; omitting top/bottom centers it). A 'bottom'
            # token would float the text above the wire, which reads as misaligned.
            justify_h = Symbol("right") if orientation in (180, 270) else Symbol("left")

            label_sexp = [
                Symbol(label_type),
                text,
                [Symbol("at"), position[0], position[1], orientation],
                [
                    Symbol("effects"),
                    [Symbol("font"), [Symbol("size"), 1.27, 1.27]],
                    [Symbol("justify"), justify_h],
                ],
                [Symbol("uuid"), str(uuid.uuid4())],
            ]

            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                # Sub-sheets in hierarchical designs don't have (sheet_instances).
                sheet_instances_index = len(sch_data)

            sch_data.insert(sheet_instances_index, label_sexp)

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))

            logger.info(f"Successfully added label '{text}' to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def normalize_label_justify(schematic_path: Path) -> int:
        """Strip the vertical (top/bottom) token from every net label's justify so
        the text is vertically centered on its wire (KiCad has no 'center' token —
        centering = absence of top/bottom). Returns the number of labels changed.
        """
        try:
            sch_data = sexpdata.loads(schematic_path.read_text(encoding="utf-8"))
            types = {_SYM_LABEL, _SYM_GLOBAL_LABEL, _SYM_HIERARCHICAL_LABEL}
            verticals = {"top", "bottom"}
            changed = 0
            for item in sch_data:
                if not (isinstance(item, list) and item and item[0] in types):
                    continue
                eff = next(
                    (p for p in item[1:]
                     if isinstance(p, list) and p and str(p[0]) == "effects"),
                    None,
                )
                if eff is None:
                    continue
                j = next(
                    (p for p in eff if isinstance(p, list) and p and str(p[0]) == "justify"),
                    None,
                )
                if j is None:
                    continue
                kept = [t for t in j[1:] if str(t) not in verticals]
                if len(kept) != len(j[1:]):
                    j[:] = [Symbol("justify")] + kept
                    changed += 1
            if changed:
                schematic_path.write_text(sexpdata.dumps(sch_data), encoding="utf-8")
            logger.info(f"Normalized justify on {changed} labels in {schematic_path.name}")
            return changed
        except Exception as e:
            logger.error(f"Error normalizing label justify: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return -1

    @staticmethod
    def add_rectangle(
        schematic_path: Path,
        start: List[float],
        end: List[float],
        stroke_width: float = 0.3,
        fill: str = "none",
    ) -> bool:
        """Add a graphic rectangle to the schematic (e.g. a block-diagram box).

        fill: 'none' (outline only), 'background' (opaque sheet-background fill —
        hides anything behind it, e.g. a line passing under the box), or 'color'.
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())

            rect_sexp = [
                Symbol("rectangle"),
                [Symbol("start"), start[0], start[1]],
                [Symbol("end"), end[0], end[1]],
                [Symbol("stroke"), [Symbol("width"), stroke_width], [Symbol("type"), Symbol("default")]],
                [Symbol("fill"), [Symbol("type"), Symbol(str(fill))]],
                [Symbol("uuid"), str(uuid.uuid4())],
            ]

            insert_at = len(sch_data)
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and item and item[0] == _SYM_SHEET_INSTANCES:
                    insert_at = i
                    break
            sch_data.insert(insert_at, rect_sexp)

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))
            logger.info(f"Added rectangle {start}-{end} (fill={fill}) to {schematic_path.name}")
            return True
        except Exception as e:
            logger.error(f"Error adding rectangle: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_hierarchical_sheet(
        root_path: Path,
        subsheet_path: Path,
        sheet_name: str,
        position: List[float],
        size: Optional[List[float]] = None,
        sheet_uuid: Optional[str] = None,
        subsheet_uuid: Optional[str] = None,
    ) -> dict:
        """Create a hierarchical sub-sheet: author the (empty) subsheet .kicad_sch and
        add a (sheet ...) symbol on the parent (root). The sheet symbol is cloned from
        an existing one on the root so its property format is guaranteed correct; only
        name/file/uuid/position are rewritten. Connectivity is via global labels (no
        sheet pins), matching the project. Returns the new uuids for instance-path use.
        """
        try:
            import copy as _copy

            w, h = (size or [90, 32])
            x, y = float(position[0]), float(position[1])
            sheet_uuid = sheet_uuid or str(uuid.uuid4())
            subsheet_uuid = subsheet_uuid or str(uuid.uuid4())
            sheet_file = Path(subsheet_path).name
            # Sheetfile must be RELATIVE TO THE ROOT'S DIRECTORY, not just the
            # basename. A subsheet in a subfolder (e.g. Sheets/Foo.kicad_sch) was
            # written as "Foo.kicad_sch", so KiCad could not locate it and the
            # sheet rendered empty / broke the hierarchy. [patch: SER2RJ45]
            try:
                sheet_file_rel = os.path.relpath(
                    str(subsheet_path), str(Path(root_path).parent)
                ).replace(os.sep, "/")
            except ValueError:
                sheet_file_rel = sheet_file

            # 1) Author the subsheet file (minimal valid; standalone page 1).
            if not Path(subsheet_path).exists():
                sub = [
                    Symbol("kicad_sch"),
                    [Symbol("version"), 20260306],
                    [Symbol("generator"), "eeschema"],
                    [Symbol("generator_version"), "10.0"],
                    [Symbol("uuid"), subsheet_uuid],
                    [Symbol("paper"), "A4"],
                    [Symbol("lib_symbols")],
                    [Symbol("sheet_instances"),
                     [Symbol("path"), "/", [Symbol("page"), "1"]]],
                ]
                Path(subsheet_path).write_text(sexpdata.dumps(sub), encoding="utf-8")

            # 2) Add the sheet symbol on the root, cloned from an existing one.
            root = sexpdata.loads(Path(root_path).read_text(encoding="utf-8"))
            sheet_sym = Symbol("sheet")
            template = next(
                (it for it in root if isinstance(it, list) and it and it[0] == sheet_sym),
                None,
            )
            if template is None:
                return {"success": False, "message": "No existing (sheet) to use as template"}
            new_sheet = _copy.deepcopy(template)

            # [patch: SER2RJ45] Strip the template's inherited sheet pins. The
            # cloned template is ANOTHER sub-sheet whose (pin ...) entries sit at
            # fixed coordinates; leaving them on the new sheet creates duplicate/
            # overlapping sheet pins that corrupt the netlist (0 nets). A new
            # sub-sheet must start with NO pins (docstring: connectivity via
            # global labels / pins added explicitly afterwards via add_sheet_pin).
            new_sheet[:] = [
                e for e in new_sheet
                if not (isinstance(e, list) and e and str(e[0]) == "pin")
            ]

            def _set_at(node, nx, ny):
                at = next((p for p in node if isinstance(p, list) and p and str(p[0]) == "at"), None)
                if at is not None:
                    at[1], at[2] = nx, ny

            _set_at(new_sheet, x, y)
            for e in new_sheet:
                if not (isinstance(e, list) and e):
                    continue
                h0 = str(e[0])
                if h0 == "uuid":
                    e[1] = sheet_uuid
                elif h0 == "size" and len(e) >= 3:
                    e[1], e[2] = w, h
                elif h0 == "property" and len(e) >= 3:
                    if str(e[1]) == "Sheetname":
                        e[2] = sheet_name
                        _set_at(e, x, y - 0.8)
                    elif str(e[1]) == "Sheetfile":
                        e[2] = sheet_file_rel
                        _set_at(e, x, y + float(h) + 0.5)

            # Give the new sheet a UNIQUE page number. The template sheet was
            # deep-copied, so its (instances ... (page "N")) was inherited verbatim
            # -> two sheets claimed the same page (duplicate page numbers in the
            # hierarchy). Assign max(existing)+1. [patch: SER2RJ45]
            def _sheet_page_node(sheet_node):
                inst = next((p for p in sheet_node
                             if isinstance(p, list) and p and str(p[0]) == "instances"), None)
                if inst is None:
                    return None
                for pb in inst[1:]:
                    if isinstance(pb, list) and pb and str(pb[0]) == "project":
                        pth = next((q for q in pb
                                    if isinstance(q, list) and q and str(q[0]) == "path"), None)
                        if pth is not None:
                            return next((q for q in pth
                                         if isinstance(q, list) and q and str(q[0]) == "page"), None)
                return None

            existing_pages = []
            for it in root:
                if isinstance(it, list) and it and str(it[0]) == "sheet":
                    pg = _sheet_page_node(it)
                    if pg is not None and len(pg) >= 2:
                        try:
                            existing_pages.append(int(str(pg[1]).strip('"')))
                        except (ValueError, TypeError):
                            pass
            new_pg = _sheet_page_node(new_sheet)
            if new_pg is not None and len(new_pg) >= 2:
                new_pg[1] = str((max(existing_pages) + 1) if existing_pages else 2)

            insert_at = len(root)
            for i, it in enumerate(root):
                if isinstance(it, list) and it and str(it[0]) == "sheet_instances":
                    insert_at = i
                    break
            root.insert(insert_at, new_sheet)
            Path(root_path).write_text(sexpdata.dumps(root), encoding="utf-8")

            root_uuid = next(
                (str(it[1]) for it in root if isinstance(it, list) and str(it[0]) == "uuid"),
                None,
            )
            logger.info(f"Added hierarchical sheet '{sheet_name}' ({sheet_file})")
            return {
                "success": True,
                "sheet_uuid": sheet_uuid,
                "subsheet_uuid": subsheet_uuid,
                "root_uuid": root_uuid,
                "sheet_file": sheet_file_rel,
            }
        except Exception as e:
            logger.error(f"Error adding hierarchical sheet: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def repair_subsheet_instances(subsheet_path: Path, root_path: Path) -> int:
        """Ensure every symbol on a sub-sheet carries the hierarchical instance path
        `(project "<root>" (path "/<root-uuid>/<sheet-symbol-uuid>" (reference)(unit)))`
        in addition to its standalone path, so kicad-cli netlist emits its pins in the
        full hierarchy. Derives the uuids by matching the subsheet's filename to a
        (sheet) on the root. Returns the number of symbols fixed.
        """
        try:
            root = sexpdata.loads(Path(root_path).read_text(encoding="utf-8"))
            root_uuid = next(
                (str(it[1]) for it in root if isinstance(it, list) and str(it[0]) == "uuid"), None
            )
            fname = Path(subsheet_path).name
            sheet_uuid = None
            for it in root:
                if not (isinstance(it, list) and it and str(it[0]) == "sheet"):
                    continue
                sf = next((str(e[2]) for e in it if isinstance(e, list) and str(e[0]) == "property"
                           and len(e) >= 3 and str(e[1]) == "Sheetfile"), None)
                # Sheetfile may now be a subfolder-relative path (e.g.
                # "Sheets/Foo.kicad_sch"); match on the basename. [patch: SER2RJ45]
                if sf is not None and Path(sf).name == fname:
                    sheet_uuid = next((str(e[1]) for e in it if isinstance(e, list)
                                       and str(e[0]) == "uuid"), None)
                    break
            if not (root_uuid and sheet_uuid):
                logger.error("Could not resolve root/sheet uuid for subsheet instances")
                return -1
            # Project name = the .kicad_pro stem next to the root (what real eeschema writes).
            # Must NOT be hard-coded — a wrong name breaks hierarchy resolution on any other
            # project. Fall back to the root schematic's stem if no .kicad_pro is present.
            proj_name = next(
                (p.stem for p in sorted(Path(root_path).parent.glob("*.kicad_pro"))),
                Path(root_path).stem,
            )
            hier_path = f"/{root_uuid}/{sheet_uuid}"

            sch = sexpdata.loads(Path(subsheet_path).read_text(encoding="utf-8"))
            fixed = 0
            sym = Symbol("symbol")
            for it in sch:
                if not (isinstance(it, list) and it and it[0] == sym):
                    continue
                ref = next((str(e[2]) for e in it if isinstance(e, list) and str(e[0]) == "property"
                            and len(e) >= 3 and str(e[1]) == "Reference"), None)
                if not ref:
                    continue
                instances = next((e for e in it if isinstance(e, list) and str(e[0]) == "instances"), None)
                if instances is None:
                    instances = [Symbol("instances")]
                    it.append(instances)
                # unit from existing standalone instance, default 1
                unit = 1
                proj_blocks = [p for p in instances[1:] if isinstance(p, list) and str(p[0]) == "project"]
                for pb in proj_blocks:
                    pth = next((q for q in pb if isinstance(q, list) and str(q[0]) == "path"), None)
                    if pth:
                        u = next((q for q in pth if isinstance(q, list) and str(q[0]) == "unit"), None)
                        if u:
                            unit = u[1]
                # already has the hierarchical project block?
                has_hier = any(
                    str(pb[1]) == proj_name
                    and any(isinstance(q, list) and str(q[0]) == "path" and str(q[1]) == hier_path
                            for q in pb[2:])
                    for pb in proj_blocks
                )
                if has_hier:
                    continue
                instances.append([
                    Symbol("project"), proj_name,
                    [Symbol("path"), hier_path,
                     [Symbol("reference"), ref], [Symbol("unit"), unit]],
                ])
                fixed += 1
            if fixed:
                Path(subsheet_path).write_text(sexpdata.dumps(sch), encoding="utf-8")
            logger.info(f"Repaired hierarchical instances on {fixed} symbols in {fname}")
            return fixed
        except Exception as e:
            logger.error(f"Error repairing subsheet instances: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return -1

    @staticmethod
    def move_components_to_sheet(root_path, source_path, target_path, references) -> dict:
        """[SER2RJ45 #56] Relocate component instances (and the net labels / power
        symbols attached to their pins) from source sheet to target sheet.

        - Copies any missing lib_symbols defs into the target.
        - Repairs hierarchical instance paths on the target (calls
          repair_subsheet_instances) so kicad-cli emits the moved pins.
        NOTE: nets entirely WITHIN the moved set stay intact (their labels move
        too). CROSS-sheet signals become local on the target and must be
        re-exposed by the caller (hierarchical labels + sheet pins + root nets).
        """
        try:
            from commands.pin_locator import PinLocator

            refs = set(references)
            src = sexpdata.loads(Path(source_path).read_text(encoding="utf-8"))
            dst = sexpdata.loads(Path(target_path).read_text(encoding="utf-8"))

            def _ref(node):
                return next((str(e[2]) for e in node if isinstance(e, list) and len(e) >= 3
                             and str(e[0]) == "property" and str(e[1]) == "Reference"), None)

            def _libid(node):
                return next((str(e[1]) for e in node if isinstance(e, list) and str(e[0]) == "lib_id"), None)

            def _at(node):
                a = next((e for e in node if isinstance(e, list) and str(e[0]) == "at"), None)
                return (round(float(a[1]), 2), round(float(a[2]), 2)) if a else None

            # 1) pin endpoints of the moved components (to capture attached labels)
            loc = PinLocator()
            pin_xy = set()
            for r in refs:
                for xy in loc.get_all_symbol_pins(Path(source_path), r).values():
                    pin_xy.add((round(float(xy[0]), 2), round(float(xy[1]), 2)))

            symsym = Symbol("symbol")
            moved, moved_libs, kept = [], set(), []
            for it in src:
                if isinstance(it, list) and it and it[0] == symsym and _ref(it) in refs:
                    moved.append(it)
                    lid = _libid(it)
                    if lid:
                        moved_libs.add(lid)
                else:
                    kept.append(it)
            # labels / power-symbols sitting on the moved pins move too
            kept2 = []
            for it in kept:
                take = False
                if isinstance(it, list) and it:
                    h = str(it[0])
                    if h in ("label", "global_label", "hierarchical_label") and _at(it) in pin_xy:
                        take = True
                    elif h == "symbol":
                        r = _ref(it)
                        if r and r.startswith("#") and _at(it) in pin_xy:
                            take = True
                            lid = _libid(it)
                            if lid:
                                moved_libs.add(lid)
                if take:
                    moved.append(it)
                else:
                    kept2.append(it)

            # 2) copy any missing lib_symbols defs into the target
            def _libsec(tree):
                return next((e for e in tree if isinstance(e, list) and e and str(e[0]) == "lib_symbols"), None)
            src_lib, dst_lib = _libsec(kept2), _libsec(dst)
            if dst_lib is None:
                dst_lib = [Symbol("lib_symbols")]
                dst.insert(1, dst_lib)
            have = {str(e[1]) for e in dst_lib[1:] if isinstance(e, list) and str(e[0]) == "symbol"}
            if src_lib is not None:
                for e in src_lib[1:]:
                    if isinstance(e, list) and str(e[0]) == "symbol" and str(e[1]) in moved_libs and str(e[1]) not in have:
                        dst_lib.append(e)

            # 3) insert moved instances+labels into the target (before sheet_instances)
            ins = len(dst)
            for i, e in enumerate(dst):
                if isinstance(e, list) and e and str(e[0]) == "sheet_instances":
                    ins = i
                    break
            for m in moved:
                dst.insert(ins, m)
                ins += 1

            Path(source_path).write_text(sexpdata.dumps(kept2), encoding="utf-8")
            Path(target_path).write_text(sexpdata.dumps(dst), encoding="utf-8")

            # 4) repair hierarchical instance paths on the target
            fixed = WireManager.repair_subsheet_instances(Path(target_path), Path(root_path))
            n_sym = sum(1 for m in moved if isinstance(m, list) and m and m[0] == symsym)
            n_lbl = sum(1 for m in moved if isinstance(m, list) and m and str(m[0]) in
                        ("label", "global_label", "hierarchical_label"))
            return {"success": True, "moved_symbols": n_sym, "moved_labels": n_lbl,
                    "instances_repaired": fixed}
        except Exception as e:
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def relocate_labels_to_stubs(schematic_path, stub_len: float = 2.54) -> dict:
        """[SER2RJ45 #57] Schematic-style fix: every net / global / hierarchical label
        sitting flush on a component pin gets a short stub wire (stub_len mm) extending
        outward from the pin, and the label is moved to the stub end and oriented
        outward (left pin->180, right->0, up->90, down->270). Keeps connectivity (the
        stub wire joins pin<->label, same net name). Skips labels already off-pin.
        """
        try:
            import math
            from commands.pin_locator import PinLocator

            sp = Path(schematic_path)
            loc = PinLocator()
            tree = sexpdata.loads(sp.read_text(encoding="utf-8"))

            def _ref(node):
                return next((str(e[2]) for e in node if isinstance(e, list) and len(e) >= 3
                             and str(e[0]) == "property" and str(e[1]) == "Reference"), None)

            # 1) pin position -> OUTWARD angle (away from the symbol body), for every
            # real component. Computed as the direction from the symbol's placement
            # origin toward the pin — robust across pin-angle conventions (get_pin_angle
            # returns the pin's draw direction, which for some symbols points INTO the
            # body and would push the stub/label over the symbol).
            symsym = Symbol("symbol")
            pin_ang = {}
            for node in tree:
                if not (isinstance(node, list) and node and node[0] == symsym):
                    continue
                ref = _ref(node)
                if not ref or ref.startswith("#"):
                    continue
                pins = loc.get_all_symbol_pins(sp, ref)          # {num: [x, y]}
                if not pins:
                    continue
                xs = [float(xy[0]) for xy in pins.values()]
                ys = [float(xy[1]) for xy in pins.values()]
                minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
                cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
                for num, xy in pins.items():
                    px, py = float(xy[0]), float(xy[1])
                    if (maxx - minx) < 0.01:             # vertical 2-pin part -> up / down
                        ang = 90.0 if py < cy else 270.0
                    elif (maxy - miny) < 0.01:           # horizontal 2-pin part -> left / right
                        ang = 180.0 if px < cx else 0.0
                    else:                                # 2-D symbol -> nearest pin-bbox edge
                        d = {180.0: px - minx, 0.0: maxx - px, 90.0: py - miny, 270.0: maxy - py}
                        ang = min(d, key=d.get)
                    pin_ang[(round(px, 2), round(py, 2))] = ang

            # 2) for each label at a pin position: add stub wire + move + orient
            def _at(node):
                return next((e for e in node if isinstance(e, list) and str(e[0]) == "at"), None)

            LABELS = ("label", "global_label", "hierarchical_label")
            # pass 1: collect candidates (a label sitting on a pin)
            cands = []
            for node in tree:
                if not (isinstance(node, list) and node and str(node[0]) in LABELS):
                    continue
                a = _at(node)
                if a is None:
                    continue
                key = (round(float(a[1]), 2), round(float(a[2]), 2))
                if key not in pin_ang:
                    continue
                ang = pin_ang[key]
                rad = math.radians(ang)
                ex = round(key[0] + stub_len * math.cos(rad), 2)
                ey = round(key[1] - stub_len * math.sin(rad), 2)   # screen Y-down
                cands.append((node, a, key, ex, ey, ang))

            # collision guard: a stub end that coincides with another stub end or with a
            # pin would short two nets (e.g. crystal pins facing each other). Skip those —
            # leave the label flush (connectivity is unchanged, the net is by name anyway).
            from collections import Counter
            endc = Counter((ex, ey) for _, _, _, ex, ey, _ in cands)
            pinset = set(pin_ang.keys())
            wires, moved, skipped = [], 0, 0
            for node, a, key, ex, ey, ang in cands:
                if endc[(ex, ey)] > 1 or (ex, ey) in pinset:
                    skipped += 1
                    continue
                wires.append([
                    Symbol("wire"),
                    [Symbol("pts"), [Symbol("xy"), key[0], key[1]], [Symbol("xy"), ex, ey]],
                    [Symbol("stroke"), [Symbol("width"), 0], [Symbol("type"), Symbol("default")]],
                    [Symbol("uuid"), str(uuid.uuid4())],
                ])
                a[1], a[2] = ex, ey
                # orient flag outward (snap to nearest 0/90/180/270)
                a3 = int(round(ang / 90.0) * 90) % 360
                if len(a) >= 4:
                    a[3] = a3
                else:
                    a.append(a3)
                # orientation-aware horizontal justify so text reads outward
                # (KiCad flips alignment for 180/270; same rule as add_schematic_net_label)
                jh = Symbol("right") if a3 in (180, 270) else Symbol("left")
                eff = next((e for e in node if isinstance(e, list) and str(e[0]) == "effects"), None)
                if eff is not None:
                    jt = next((e for e in eff if isinstance(e, list) and str(e[0]) == "justify"), None)
                    if jt is None:
                        eff.append([Symbol("justify"), jh])
                    else:
                        jt[:] = [Symbol("justify"), jh]
                moved += 1

            # insert stub wires before (sheet_instances ...)
            ins = len(tree)
            for i, e in enumerate(tree):
                if isinstance(e, list) and e and str(e[0]) == "sheet_instances":
                    ins = i
                    break
            for w in wires:
                tree.insert(ins, w)
                ins += 1

            sp.write_text(sexpdata.dumps(tree), encoding="utf-8")
            return {"success": True, "labels_relocated": moved, "stubs_added": len(wires),
                    "skipped_collisions": skipped}
        except Exception as e:
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def hide_power_references(schematic_path) -> dict:
        """[SER2RJ45 #59] Hide the reference designator (#PWRxx) on every power symbol —
        standard schematic cleanup (power symbols are identified by their graphic, not the
        ref). Purely cosmetic: adds (hide yes) to each power symbol's Reference effects,
        no connectivity / netlist impact.
        """
        try:
            sp = Path(schematic_path)
            tree = sexpdata.loads(sp.read_text(encoding="utf-8"))
            symsym = Symbol("symbol")
            hidden = 0
            for node in tree:
                if not (isinstance(node, list) and node and node[0] == symsym):
                    continue
                lid = next((str(e[1]) for e in node if isinstance(e, list) and str(e[0]) == "lib_id"), "")
                if not lid.startswith("power:"):
                    continue
                for prop in node:
                    if not (isinstance(prop, list) and str(prop[0]) == "property"
                            and len(prop) >= 2 and str(prop[1]) == "Reference"):
                        continue
                    eff = next((e for e in prop if isinstance(e, list) and str(e[0]) == "effects"), None)
                    if eff is None:
                        eff = [Symbol("effects"), [Symbol("font"), [Symbol("size"), 1.27, 1.27]]]
                        prop.append(eff)
                    if not any(isinstance(e, list) and str(e[0]) == "hide" for e in eff):
                        eff.append([Symbol("hide"), Symbol("yes")])
                        hidden += 1
            sp.write_text(sexpdata.dumps(tree), encoding="utf-8")
            return {"success": True, "references_hidden": hidden}
        except Exception as e:
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def add_polyline(
        schematic_path: Path,
        points: List[List[float]],
        stroke_width: float = 0.4,
    ) -> bool:
        """Add a graphic polyline (block-diagram connection line) through points (mm)."""
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())

            pts = [Symbol("pts")] + [
                [Symbol("xy"), float(p[0]), float(p[1])] for p in points
            ]
            poly_sexp = [
                Symbol("polyline"),
                pts,
                [Symbol("stroke"), [Symbol("width"), stroke_width], [Symbol("type"), Symbol("default")]],
                [Symbol("uuid"), str(uuid.uuid4())],
            ]
            insert_at = len(sch_data)
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and item and item[0] == _SYM_SHEET_INSTANCES:
                    insert_at = i
                    break
            sch_data.insert(insert_at, poly_sexp)

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))
            logger.info(f"Added polyline {points} to {schematic_path.name}")
            return True
        except Exception as e:
            logger.error(f"Error adding polyline: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_shape(
        schematic_path: Path,
        shape_type: str,
        point: List[float],
        tolerance: float = 0.5,
    ) -> bool:
        """Delete a graphic shape (rectangle/polyline/circle/arc) by a reference point.

        Matches the first shape of the given type that has any defining coordinate
        (start/end/center/mid or a pts vertex) within tolerance of `point`.
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())
            sym = Symbol(str(shape_type))
            px, py = float(point[0]), float(point[1])
            for i, item in enumerate(sch_data):
                if not (isinstance(item, list) and item and item[0] == sym):
                    continue
                coords = []
                for e in item[1:]:
                    if not (isinstance(e, list) and e):
                        continue
                    h = str(e[0])
                    if h in ("start", "end", "center", "mid", "at") and len(e) >= 3:
                        coords.append((float(e[1]), float(e[2])))
                    elif h == "pts":
                        for xy in e[1:]:
                            if isinstance(xy, list) and xy and str(xy[0]) == "xy":
                                coords.append((float(xy[1]), float(xy[2])))
                if any(abs(x - px) < tolerance and abs(y - py) < tolerance for x, y in coords):
                    del sch_data[i]
                    with open(schematic_path, "w", encoding="utf-8") as f:
                        f.write(sexpdata.dumps(sch_data))
                    logger.info(f"Deleted {shape_type} near {point}")
                    return True
            logger.warning(f"No {shape_type} found near {point}")
            return False
        except Exception as e:
            logger.error(f"Error deleting shape: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def _parse_wire(
        wire_item: Any,
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float], float, str]]:
        """
        Parse a wire S-expression item in a single pass.
        Returns ((x1,y1), (x2,y2), stroke_width, stroke_type), or None if not a valid wire.
        """
        if not (isinstance(wire_item, list) and len(wire_item) >= 2 and wire_item[0] == _SYM_WIRE):
            return None
        start = end = None
        stroke_width: float = 0
        stroke_type: str = "default"
        for part in wire_item[1:]:
            if not isinstance(part, list) or not part:
                continue
            tag = part[0]
            if tag == _SYM_PTS:
                found: List[Tuple[float, float]] = []
                for p in part[1:]:
                    if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_XY:
                        found.append((float(p[1]), float(p[2])))
                        if len(found) == 2:
                            break
                if len(found) == 2:
                    start, end = found[0], found[1]
            elif tag == _SYM_STROKE:
                for sp in part[1:]:
                    if isinstance(sp, list) and len(sp) >= 2:
                        if sp[0] == _SYM_WIDTH:
                            stroke_width = sp[1]
                        elif sp[0] == _SYM_TYPE:
                            stroke_type = str(sp[1])
        if start is not None and end is not None:
            return start, end, stroke_width, stroke_type
        return None

    @staticmethod
    def _point_strictly_on_wire(
        px: float,
        py: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        eps: float = 1e-6,
    ) -> bool:
        """
        Return True if (px, py) lies strictly between (x1,y1) and (x2,y2)
        on a horizontal or vertical wire segment (not at either endpoint).
        """
        if abs(y1 - y2) < eps:  # horizontal wire
            if abs(py - y1) > eps:
                return False
            lo, hi = min(x1, x2), max(x1, x2)
            return lo + eps < px < hi - eps
        if abs(x1 - x2) < eps:  # vertical wire
            if abs(px - x1) > eps:
                return False
            lo, hi = min(y1, y2), max(y1, y2)
            return lo + eps < py < hi - eps
        return False

    @staticmethod
    def _make_wire_sexp(
        start: List[float],
        end: List[float],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> list:
        return [
            _SYM_WIRE,
            [_SYM_PTS, [_SYM_XY, start[0], start[1]], [_SYM_XY, end[0], end[1]]],
            [_SYM_STROKE, [_SYM_WIDTH, stroke_width], [_SYM_TYPE, Symbol(stroke_type)]],
            [_SYM_UUID, str(uuid.uuid4())],
        ]

    @staticmethod
    def _break_wires_at_point(sch_data: list, position: List[float]) -> int:
        """
        Split any wire segment that passes through *position* as a strict
        midpoint (i.e. position is not an existing endpoint).  Mirrors
        KiCAD's SCH_LINE_WIRE_BUS_TOOL::BreakSegments behaviour.

        Returns the number of wires split.
        """
        px, py = float(position[0]), float(position[1])
        splits = 0
        i = 0
        while i < len(sch_data):
            parsed = WireManager._parse_wire(sch_data[i])
            if parsed is not None:
                (x1, y1), (x2, y2), stroke_width, stroke_type = parsed
                if WireManager._point_strictly_on_wire(px, py, x1, y1, x2, y2):
                    seg_a = WireManager._make_wire_sexp(
                        [x1, y1], [px, py], stroke_width, stroke_type
                    )
                    seg_b = WireManager._make_wire_sexp(
                        [px, py], [x2, y2], stroke_width, stroke_type
                    )
                    sch_data[i : i + 1] = [seg_a, seg_b]
                    logger.info(f"Split wire ({x1},{y1})->({x2},{y2}) at ({px},{py})")
                    splits += 1
                    i += 2  # skip the two new segments
                    continue
            i += 1
        return splits

    @staticmethod
    def _collect_wire_endpoints(sch_data: list) -> List[Tuple[float, float]]:
        """Return all (x, y) endpoints for every wire in sch_data."""
        endpoints: List[Tuple[float, float]] = []
        for item in sch_data:
            parsed = WireManager._parse_wire(item)
            if parsed is not None:
                (x1, y1), (x2, y2), _, _ = parsed
                endpoints.append((x1, y1))
                endpoints.append((x2, y2))
        return endpoints

    @staticmethod
    def _get_existing_junctions(sch_data: list) -> dict:
        """Return {(iu_x, iu_y): index_in_sch_data} for every junction element."""
        result: dict = {}
        for i, item in enumerate(sch_data):
            if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_JUNCTION):
                continue
            at_entry = next(
                (p for p in item[1:] if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT),
                None,
            )
            if at_entry is None:
                continue
            x, y = float(at_entry[1]), float(at_entry[2])
            result[(round(x * _IU_PER_MM), round(y * _IU_PER_MM))] = i
        return result

    @staticmethod
    def _make_junction_sexp(x: float, y: float, diameter: float = 0) -> list:
        return [
            _SYM_JUNCTION,
            [_SYM_AT, x, y],
            [Symbol("diameter"), diameter],
            [Symbol("color"), 0, 0, 0, 0],
            [_SYM_UUID, str(uuid.uuid4())],
        ]

    @staticmethod
    def _parse_lib_pins(sym_def: list, unit: int = 1) -> List[Tuple[float, float]]:
        """Extract pin local (x, y) positions for *unit* from a lib_symbols symbol definition.

        Only collects pins from sub-unit symbols whose parsed unit number matches *unit*
        OR is 0 (the "common" body drawn on every unit, e.g. power pins on an op-amp).
        Sub-units whose unit index is neither *unit* nor 0 are skipped entirely.

        If the lib_symbols entry has no nested (symbol ...) children at all (rare, simple
        defs), falls back to collecting every (pin ...) directly from the top-level entry.

        Uses a stack instead of recursion to handle nested sub-unit symbols.
        """
        pins: List[Tuple[float, float]] = []

        # Separate top-level direct children into sub-unit symbols vs other nodes.
        sub_units: list = []
        direct_pins: list = []
        for child in sym_def[1:]:
            if not isinstance(child, list) or not child:
                continue
            if child[0] == _SYM_SYMBOL:
                sub_units.append(child)
            elif child[0] == _SYM_PIN:
                direct_pins.append(child)

        if not sub_units:
            # Fallback: simple definition with no nested sub-unit symbols — collect all pins.
            nodes_to_search = direct_pins
        else:
            # Filter sub-units by parsed unit number.
            nodes_to_search = []
            for sub in sub_units:
                sub_name = (
                    sub[1]
                    if len(sub) > 1 and isinstance(sub[1], str)
                    else str(sub[1]) if len(sub) > 1 else ""
                )
                m = WireManager._SUB_UNIT_RE.match(sub_name)
                if m:
                    sub_unit_num = int(m.group(2))
                    if sub_unit_num == unit or sub_unit_num == 0:
                        nodes_to_search.extend(sub[1:])
                else:
                    # Name doesn't match the expected pattern — include it (fail-safe).
                    logger.debug(
                        "lib_symbols sub-unit name %r did not match <base>_<unit>_<style>; "
                        "including all its pins as fallback",
                        sub_name,
                    )
                    nodes_to_search.extend(sub[1:])

        # Walk the selected nodes to collect (pin ...) entries via stack.
        stack: list = list(nodes_to_search)
        while stack:
            node = stack.pop()
            if not isinstance(node, list) or not node:
                continue
            if node[0] == _SYM_PIN:
                at = next(
                    (
                        p
                        for p in node[1:]
                        if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT
                    ),
                    None,
                )
                if at:
                    pins.append((float(at[1]), float(at[2])))
                continue  # don't recurse into pin sub-expressions
            stack.extend(node[1:])
        return pins

    @staticmethod
    def _collect_pin_positions(sch_data: list) -> List[Tuple[float, float]]:
        """Return world (x, y) positions for every placed component pin in sch_data.

        Parses lib_symbols for pin local coordinates (unit-aware), then applies the KiCad
        transform chain (y-negate → mirror → rotate → translate) to each pin.
        """
        # Build {lib_id: sym_def} from the embedded lib_symbols section.
        # We defer pin extraction until we know which unit each placed instance uses.
        lib_sym_defs: dict = {}
        for item in sch_data:
            if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_LIB_SYMBOLS):
                continue
            for sym_def in item[1:]:
                if not (
                    isinstance(sym_def, list) and len(sym_def) > 1 and sym_def[0] == _SYM_SYMBOL
                ):
                    continue
                lib_id = sym_def[1] if isinstance(sym_def[1], str) else str(sym_def[1])
                lib_sym_defs[lib_id] = sym_def
            break

        # Transform each placed symbol's pins to world coordinates
        world_positions: List[Tuple[float, float]] = []
        for item in sch_data:
            if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SYMBOL):
                continue
            lib_id_part = next(
                (
                    p
                    for p in item[1:]
                    if isinstance(p, list) and len(p) >= 2 and p[0] == _SYM_LIB_ID
                ),
                None,
            )
            if lib_id_part is None:
                continue  # not a placed instance (e.g. sub-unit inside lib_symbols)
            lib_id = lib_id_part[1] if isinstance(lib_id_part[1], str) else str(lib_id_part[1])

            # Read the placed unit number (default 1 for single-unit parts).
            unit_part = next(
                (p for p in item[1:] if isinstance(p, list) and len(p) >= 2 and p[0] == _SYM_UNIT),
                None,
            )
            unit_num = int(unit_part[1]) if unit_part is not None else 1

            at_part = next(
                (p for p in item[1:] if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT),
                None,
            )
            if at_part is None:
                continue
            sym_x, sym_y = float(at_part[1]), float(at_part[2])
            rotation = float(at_part[3]) if len(at_part) > 3 else 0.0

            mirror_x = mirror_y = False
            for part in item[1:]:
                if isinstance(part, list) and len(part) >= 2 and part[0] == _SYM_MIRROR:
                    if part[1] == Symbol("x"):
                        mirror_x = True
                    elif part[1] == Symbol("y"):
                        mirror_y = True

            sym_def = lib_sym_defs.get(lib_id)
            if sym_def is None:
                continue
            local_pins = WireManager._parse_lib_pins(sym_def, unit=unit_num)

            for lx, ly in local_pins:
                # KiCad lib uses y-up; schematic uses y-down — negate before transform
                ly = -ly
                if mirror_x:
                    ly = -ly
                if mirror_y:
                    lx = -lx
                if rotation != 0.0:
                    rad = math.radians(rotation)
                    c, s = math.cos(rad), math.sin(rad)
                    lx, ly = lx * c - ly * s, lx * s + ly * c
                world_positions.append((sym_x + lx, sym_y + ly))

        return world_positions

    @staticmethod
    def sync_junctions(sch_data: list) -> Tuple[int, int]:
        """Add missing junctions and remove stale ones in sch_data in-place.

        A junction is needed at any point where the total of wire endpoints plus
        component pin positions is ≥ 3 and at least one wire endpoint is present.
        This covers wire-only T/X junctions and wire-meets-pin-with-another-wire cases.

        Returns (added_count, removed_count).
        """
        from collections import Counter

        wire_endpoints = WireManager._collect_wire_endpoints(sch_data)
        wire_iu: Counter = Counter(
            (round(x * _IU_PER_MM), round(y * _IU_PER_MM)) for x, y in wire_endpoints
        )

        pin_positions = WireManager._collect_pin_positions(sch_data)
        pin_iu: Counter = Counter(
            (round(x * _IU_PER_MM), round(y * _IU_PER_MM)) for x, y in pin_positions
        )

        # wire_iu.items() guarantees wire_cnt >= 1, so no extra guard needed
        needed_iu = {iu for iu, wire_cnt in wire_iu.items() if wire_cnt + pin_iu.get(iu, 0) >= 3}

        existing = WireManager._get_existing_junctions(sch_data)
        existing_iu = set(existing.keys())

        # Remove stale junctions; work in reverse index order to avoid shifting
        stale_indices = sorted([existing[iu] for iu in existing_iu - needed_iu], reverse=True)
        for idx in stale_indices:
            del sch_data[idx]
        removed = len(stale_indices)

        # Locate insertion point for new junctions
        sheet_instances_index = None
        for i, item in enumerate(sch_data):
            if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                sheet_instances_index = i
                break

        to_add = needed_iu - existing_iu
        added = 0
        if to_add:
            if sheet_instances_index is None:
                logger.warning("sync_junctions: no sheet_instances found, skipping junction insert")
            else:
                for iu_x, iu_y in to_add:
                    x = iu_x / _IU_PER_MM
                    y = iu_y / _IU_PER_MM
                    sch_data.insert(sheet_instances_index, WireManager._make_junction_sexp(x, y))
                    sheet_instances_index += 1
                    added += 1

        if added or removed:
            logger.info(f"sync_junctions: added {added}, removed {removed}")
        return added, removed

    @staticmethod
    def add_no_connect(schematic_path: Path, position: List[float]) -> bool:
        """
        Add a no-connect flag to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            position: [x, y] coordinates for no-connect flag

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create no_connect S-expression
            # Format: (no_connect (at x y) (uuid ...))
            no_connect_sexp = [
                Symbol("no_connect"),
                [Symbol("at"), position[0], position[1]],
                [Symbol("uuid"), str(uuid.uuid4())],
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert no_connect
            sch_data.insert(sheet_instances_index, no_connect_sexp)
            logger.info(f"Injected no-connect at {position}")

            # Write back
            with open(schematic_path, "w", encoding="utf-8") as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added no-connect to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding no-connect: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        tolerance: float = 0.5,
    ) -> bool:
        """
        Delete a wire from the schematic matching given start/end coordinates.

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            tolerance: Maximum coordinate difference to consider a match (mm)

        Returns:
            True if a wire was found and removed, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            sx, sy = start_point
            ex, ey = end_point

            for i, item in enumerate(sch_data):
                if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_WIRE):
                    continue

                # Extract pts from the wire s-expression
                pts_list = None
                for part in item[1:]:
                    if isinstance(part, list) and len(part) > 0 and part[0] == _SYM_PTS:
                        pts_list = part
                        break

                if pts_list is None:
                    continue

                xy_points = [
                    p
                    for p in pts_list[1:]
                    if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_XY
                ]
                if len(xy_points) < 2:
                    continue

                x1, y1 = float(xy_points[0][1]), float(xy_points[0][2])
                x2, y2 = float(xy_points[-1][1]), float(xy_points[-1][2])

                match_fwd = (
                    abs(x1 - sx) < tolerance
                    and abs(y1 - sy) < tolerance
                    and abs(x2 - ex) < tolerance
                    and abs(y2 - ey) < tolerance
                )
                match_rev = (
                    abs(x1 - ex) < tolerance
                    and abs(y1 - ey) < tolerance
                    and abs(x2 - sx) < tolerance
                    and abs(y2 - sy) < tolerance
                )

                if match_fwd or match_rev:
                    del sch_data[i]
                    WireManager.sync_junctions(sch_data)
                    with open(schematic_path, "w", encoding="utf-8") as f:
                        f.write(sexpdata.dumps(sch_data))
                    logger.info(f"Deleted wire from {start_point} to {end_point}")
                    return True

            logger.warning(f"No matching wire found for {start_point} to {end_point}")
            return False

        except Exception as e:
            logger.error(f"Error deleting wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_no_connect(
        schematic_path: Path,
        position: List[float],
        tolerance: float = 0.5,
    ) -> bool:
        """Delete a no-connect (X) flag whose (at x y) matches position (mm)."""
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())
            px, py = float(position[0]), float(position[1])
            nc = Symbol("no_connect")
            for i, item in enumerate(sch_data):
                if not (isinstance(item, list) and item and item[0] == nc):
                    continue
                at = next(
                    (p for p in item[1:] if isinstance(p, list) and p and p[0] == _SYM_AT),
                    None,
                )
                if at is None:
                    continue
                if abs(float(at[1]) - px) < tolerance and abs(float(at[2]) - py) < tolerance:
                    del sch_data[i]
                    with open(schematic_path, "w", encoding="utf-8") as f:
                        f.write(sexpdata.dumps(sch_data))
                    logger.info(f"Deleted no-connect at {position}")
                    return True
            logger.warning(f"No matching no-connect at {position}")
            return False
        except Exception as e:
            logger.error(f"Error deleting no-connect: {e}")
            return False

    @staticmethod
    def _find_text_index(sch_data, position=None, text=None, tolerance=0.5) -> int:
        """Index of a (text "...") element matched by exact text or (at) position."""
        tsym = Symbol("text")
        for i, item in enumerate(sch_data):
            if not (isinstance(item, list) and len(item) >= 2 and item[0] == tsym):
                continue
            if text is not None and str(item[1]) == text:
                return i
            if position is not None:
                at = next(
                    (p for p in item[2:] if isinstance(p, list) and p and p[0] == _SYM_AT),
                    None,
                )
                if (
                    at is not None
                    and abs(float(at[1]) - position[0]) < tolerance
                    and abs(float(at[2]) - position[1]) < tolerance
                ):
                    return i
        return -1

    @staticmethod
    def delete_text(
        schematic_path: Path,
        position: Optional[List[float]] = None,
        text: Optional[str] = None,
        tolerance: float = 0.5,
    ) -> bool:
        """Delete a free-form (text "...") annotation by exact text or by position."""
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())
            idx = WireManager._find_text_index(sch_data, position, text, tolerance)
            if idx < 0:
                logger.warning(f"No matching text (pos={position}, text={text})")
                return False
            del sch_data[idx]
            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))
            logger.info("Deleted schematic text")
            return True
        except Exception as e:
            logger.error(f"Error deleting text: {e}")
            return False

    @staticmethod
    def edit_text(
        schematic_path: Path,
        new_text: str,
        position: Optional[List[float]] = None,
        old_text: Optional[str] = None,
        tolerance: float = 0.5,
    ) -> bool:
        """Replace the string of a (text "...") annotation (located by old_text or position)."""
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())
            idx = WireManager._find_text_index(sch_data, position, old_text, tolerance)
            if idx < 0:
                logger.warning(f"No matching text to edit (pos={position}, old={old_text})")
                return False
            sch_data[idx][1] = new_text
            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))
            logger.info("Edited schematic text")
            return True
        except Exception as e:
            logger.error(f"Error editing text: {e}")
            return False

    # Electrical pin types accepted by KiCad's (pin <type> <shape> ...) field.
    _PIN_TYPES = {
        "input", "output", "bidirectional", "tri_state", "passive", "free",
        "unspecified", "power_in", "power_out", "open_collector",
        "open_emitter", "no_connect",
    }

    @staticmethod
    def _lib_id_for_ref(sch_data, component_ref: str) -> Optional[str]:
        """Resolve a placed symbol's lib_id string from its Reference property."""
        sym = Symbol("symbol")
        lib_id_s = Symbol("lib_id")
        prop = Symbol("property")
        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == sym):
                continue
            ref = None
            lib_id = None
            for p in item[1:]:
                if not (isinstance(p, list) and p):
                    continue
                if p[0] == lib_id_s and len(p) >= 2:
                    lib_id = str(p[1])
                elif p[0] == prop and len(p) >= 3 and str(p[1]) == "Reference":
                    ref = str(p[2])
            if ref == component_ref:
                return lib_id
        return None

    @staticmethod
    def set_pin_type(
        schematic_path: Path,
        pin_number: str,
        pin_type: str,
        component_ref: Optional[str] = None,
        lib_id: Optional[str] = None,
    ) -> bool:
        """Set the electrical type of one pin in a symbol's (lib_symbols ...) definition.

        ERC reads pin electrical types from the schematic's cached symbol definition,
        so patching it here is what clears pin_to_pin / power_pin_not_driven noise.
        Locate the symbol by component_ref (resolved to its lib_id) or lib_id directly;
        match the pin by its (number "N"); rewrite the leading type token.
        """
        try:
            pin_type = str(pin_type)
            if pin_type not in WireManager._PIN_TYPES:
                logger.error(
                    f"Invalid pin type '{pin_type}'; expected one of {sorted(WireManager._PIN_TYPES)}"
                )
                return False
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())

            target = lib_id
            if target is None and component_ref is not None:
                target = WireManager._lib_id_for_ref(sch_data, component_ref)
            if target is None:
                logger.error(
                    f"Could not resolve lib_id (ref={component_ref}, lib_id={lib_id})"
                )
                return False

            sym = Symbol("symbol")
            lib_symbols_s = Symbol("lib_symbols")
            pin_s = Symbol("pin")
            number_s = Symbol("number")
            want = str(pin_number)

            lib_symbols = next(
                (it for it in sch_data
                 if isinstance(it, list) and it and it[0] == lib_symbols_s),
                None,
            )
            if lib_symbols is None:
                logger.error("No (lib_symbols ...) block in schematic")
                return False

            sym_def = next(
                (it for it in lib_symbols[1:]
                 if isinstance(it, list) and len(it) >= 2
                 and it[0] == sym and str(it[1]) == target),
                None,
            )
            if sym_def is None:
                logger.error(f"Symbol definition '{target}' not found in lib_symbols")
                return False

            # Pins live in the per-unit sub-(symbol ...) children of the top definition.
            def _patch_pins(node) -> bool:
                changed = False
                for child in node:
                    if not (isinstance(child, list) and child):
                        continue
                    if child[0] == sym:
                        if _patch_pins(child):
                            changed = True
                    elif child[0] == pin_s and len(child) >= 3:
                        num = next(
                            (p for p in child[2:]
                             if isinstance(p, list) and p and p[0] == number_s),
                            None,
                        )
                        if num is not None and str(num[1]) == want:
                            child[1] = Symbol(pin_type)
                            changed = True
                return changed

            if not _patch_pins(sym_def):
                logger.warning(f"Pin {want} not found in symbol '{target}'")
                return False

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))
            logger.info(f"Set pin {want} of '{target}' to type '{pin_type}'")
            return True
        except Exception as e:
            logger.error(f"Error setting pin type: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def set_component_dnp(
        schematic_path: Path,
        reference: str,
        dnp: bool = True,
        in_bom: Optional[bool] = None,
    ) -> bool:
        """Set the DNP (Do Not Populate) attribute of a placed symbol.

        Finds the top-level placed (symbol ...) block whose (property "Reference")
        matches `reference` and rewrites its (dnp yes|no) token; inserts the token
        after (on_board ...) when the symbol predates the attribute. Optionally
        also rewrites (in_bom yes|no) — KiCad convention keeps DNP parts in the
        BOM unless explicitly excluded, so in_bom is left untouched by default.
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())

            sym_s = Symbol("symbol")
            prop_s = Symbol("property")
            dnp_s = Symbol("dnp")
            in_bom_s = Symbol("in_bom")
            on_board_s = Symbol("on_board")
            yes_s, no_s = Symbol("yes"), Symbol("no")

            def _set_token(block: list, key: Symbol, val: bool) -> None:
                for ch in block:
                    if isinstance(ch, list) and ch and ch[0] == key:
                        ch[1] = yes_s if val else no_s
                        return
                # token absent (old-format symbol) — insert after (on_board ...)
                idx = None
                for i, ch in enumerate(block):
                    if isinstance(ch, list) and ch and ch[0] == on_board_s:
                        idx = i + 1
                        break
                entry = [key, yes_s if val else no_s]
                block.insert(idx if idx is not None else len(block), entry)

            changed = False
            for it in sch_data:
                if not (isinstance(it, list) and it and it[0] == sym_s):
                    continue
                ref = None
                for ch in it:
                    if (isinstance(ch, list) and ch and ch[0] == prop_s
                            and len(ch) >= 3 and str(ch[1]) == "Reference"):
                        ref = str(ch[2])
                        break
                if ref != reference:
                    continue
                _set_token(it, dnp_s, dnp)
                if in_bom is not None:
                    _set_token(it, in_bom_s, in_bom)
                changed = True

            if not changed:
                logger.error(f"Component '{reference}' not found in {schematic_path}")
                return False

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))
            logger.info(f"Set DNP={dnp} on {reference} in {schematic_path}")
            return True
        except Exception as e:
            logger.error(f"Error setting DNP: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_label(
        schematic_path: Path,
        net_name: str,
        position: Optional[List[float]] = None,
        tolerance: float = 0.5,
    ) -> bool:
        """
        Delete a net label from the schematic by name (and optionally position).

        Args:
            schematic_path: Path to .kicad_sch file
            net_name: Net label text to match
            position: Optional [x, y] to disambiguate when multiple labels share a name
            tolerance: Maximum coordinate difference to consider a match (mm)

        Returns:
            True if a label was found and removed, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            _LABEL_TYPES = {_SYM_LABEL, _SYM_GLOBAL_LABEL, _SYM_HIERARCHICAL_LABEL}
            for i, item in enumerate(sch_data):
                if not (isinstance(item, list) and len(item) > 0 and item[0] in _LABEL_TYPES):
                    continue

                # Second element is the label text
                if len(item) < 2 or item[1] != net_name:
                    continue

                if position is not None:
                    # Find (at x y ...) sub-expression and check coordinates
                    at_entry = next(
                        (
                            p
                            for p in item[1:]
                            if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT
                        ),
                        None,
                    )
                    if at_entry is None:
                        continue
                    lx, ly = float(at_entry[1]), float(at_entry[2])
                    if not (
                        abs(lx - position[0]) < tolerance and abs(ly - position[1]) < tolerance
                    ):
                        continue

                del sch_data[i]
                with open(schematic_path, "w", encoding="utf-8") as f:
                    f.write(sexpdata.dumps(sch_data))
                logger.info(f"Deleted label '{net_name}'")
                return True

            logger.warning(f"No matching label found for '{net_name}'")
            return False

        except Exception as e:
            logger.error(f"Error deleting label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def set_label_orientation(
        schematic_path: Path,
        net_name: str,
        rotation: Optional[float] = None,
        justify: Optional[str] = None,
        position: Optional[List[float]] = None,
        label_type: Optional[str] = None,
        tolerance: float = 0.5,
    ) -> bool:
        """Set a net label's rotation (the angle in `(at x y angle)`) and/or its
        text justify (left/right/top/bottom). Position never changes, so wire
        connectivity is preserved — this only flips which way the label text /
        global-label flag points, fixing overlaps with the symbol body or wires.
        """
        try:
            sch_data = sexpdata.loads(schematic_path.read_text(encoding="utf-8"))

            type_map = {
                "label": _SYM_LABEL,
                "global_label": _SYM_GLOBAL_LABEL,
                "hierarchical_label": _SYM_HIERARCHICAL_LABEL,
            }
            allowed = (
                {type_map[label_type]} if label_type in type_map
                else {_SYM_LABEL, _SYM_GLOBAL_LABEL, _SYM_HIERARCHICAL_LABEL}
            )
            justify_sym = Symbol("justify")
            effects_sym = Symbol("effects")

            for item in sch_data:
                if not (isinstance(item, list) and len(item) >= 2 and item[0] in allowed):
                    continue
                if str(item[1]) != net_name:
                    continue
                at_entry = next(
                    (p for p in item[1:]
                     if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT),
                    None,
                )
                if at_entry is None:
                    continue
                if position is not None:
                    lx, ly = float(at_entry[1]), float(at_entry[2])
                    if not (abs(lx - position[0]) < tolerance
                            and abs(ly - position[1]) < tolerance):
                        continue

                if rotation is not None:
                    if len(at_entry) >= 4:
                        at_entry[3] = rotation
                    else:
                        at_entry.append(rotation)

                if justify is not None:
                    effects = next(
                        (p for p in item[1:]
                         if isinstance(p, list) and p and p[0] == effects_sym),
                        None,
                    )
                    if effects is None:
                        effects = [effects_sym]
                        item.append(effects)
                    j_entry = next(
                        (p for p in effects[1:]
                         if isinstance(p, list) and p and p[0] == justify_sym),
                        None,
                    )
                    new_j = [justify_sym] + [Symbol(t) for t in str(justify).split()]
                    if j_entry is None:
                        effects.append(new_j)
                    else:
                        j_entry[:] = new_j

                schematic_path.write_text(sexpdata.dumps(sch_data), encoding="utf-8")
                logger.info(
                    f"Set label '{net_name}' orientation (rotation={rotation}, justify={justify})"
                )
                return True

            logger.warning(f"No matching label found for '{net_name}'")
            return False
        except Exception as e:
            logger.error(f"Error setting label orientation: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def create_orthogonal_path(
        start: List[float], end: List[float], prefer_horizontal_first: bool = True
    ) -> List[List[float]]:
        """
        Create an orthogonal (right-angle) path between two points

        Args:
            start: [x, y] start coordinates
            end: [x, y] end coordinates
            prefer_horizontal_first: If True, route horizontally first, else vertically first

        Returns:
            List of points defining the path: [start, corner, end]
        """
        x1, y1 = start
        x2, y2 = end

        if prefer_horizontal_first:
            # Route: start → (x2, y1) → end
            corner = [x2, y1]
        else:
            # Route: start → (x1, y2) → end
            corner = [x1, y2]

        # If start and end are already aligned, return direct path
        if x1 == x2 or y1 == y2:
            return [start, end]

        return [start, corner, end]

    @staticmethod
    def list_texts(schematic_path: Path) -> Optional[List[Any]]:
        """Return all free-form text annotations (SCH_TEXT) in a schematic.

        Each entry is a dict with keys: text, position (x/y), angle,
        font_size, bold, italic, justify, uuid.
        Returns None on parse error.
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())

            _SYM_TEXT = Symbol("text")
            _SYM_EFFECTS = Symbol("effects")
            _SYM_FONT = Symbol("font")
            _SYM_SIZE = Symbol("size")
            _SYM_JUSTIFY = Symbol("justify")
            _SYM_BOLD = Symbol("bold")
            _SYM_ITALIC = Symbol("italic")

            results = []
            for item in sch_data:
                if not (isinstance(item, list) and len(item) >= 2 and item[0] == _SYM_TEXT):
                    continue
                # item[1] is the text string
                text_val = item[1] if len(item) > 1 else ""

                pos_x = pos_y = angle = 0.0
                font_size = 1.27
                bold = italic = False
                justify = "left"
                uid = ""

                for part in item[2:]:
                    if not isinstance(part, list) or not part:
                        continue
                    tag = part[0]
                    if tag == _SYM_AT and len(part) >= 3:
                        pos_x = float(part[1])
                        pos_y = float(part[2])
                        angle = float(part[3]) if len(part) >= 4 else 0.0
                    elif tag == _SYM_UUID and len(part) >= 2:
                        uid = str(part[1])
                    elif tag == _SYM_EFFECTS:
                        for eff in part[1:]:
                            if not isinstance(eff, list) or not eff:
                                continue
                            if eff[0] == _SYM_FONT:
                                for fp in eff[1:]:
                                    if not isinstance(fp, list) or not fp:
                                        continue
                                    if fp[0] == _SYM_SIZE and len(fp) >= 2:
                                        font_size = float(fp[1])
                                    elif fp[0] == _SYM_BOLD and len(fp) >= 2:
                                        bold = str(fp[1]).lower() == "yes"
                                    elif fp[0] == _SYM_ITALIC and len(fp) >= 2:
                                        italic = str(fp[1]).lower() == "yes"
                            elif eff[0] == _SYM_JUSTIFY and len(eff) >= 2:
                                justify = str(eff[1])

                results.append(
                    {
                        "text": text_val,
                        "position": {"x": pos_x, "y": pos_y},
                        "angle": angle,
                        "font_size": font_size,
                        "bold": bold,
                        "italic": italic,
                        "justify": justify,
                        "uuid": uid,
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Error listing texts: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def add_text(
        schematic_path: Path,
        text: str,
        position: List[float],
        angle: float = 0,
        font_size: float = 1.27,
        bold: bool = False,
        italic: bool = False,
        justify: str = "left",
    ) -> bool:
        """Add a free-form text annotation (SCH_TEXT) to a KiCad schematic."""
        try:
            # KiCad's parser rejects raw newlines inside quoted string literals,
            # so escape them along with backslashes and quotes. Order matters:
            # backslashes first, otherwise we double-escape our own escapes.
            text_escaped = (
                text.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
            )
            uid = str(uuid.uuid4())
            font_attrs = f"\n\t\t\t\t(size {font_size} {font_size})"
            if bold:
                font_attrs += "\n\t\t\t\t(bold yes)"
            if italic:
                font_attrs += "\n\t\t\t\t(italic yes)"
            text_sexp = (
                f'\t(text "{text_escaped}"\n'
                f"\t\t(exclude_from_sim no)\n"
                f"\t\t(at {position[0]} {position[1]} {angle})\n"
                f"\t\t(effects\n"
                f"\t\t\t(font{font_attrs}\n"
                f"\t\t\t)\n"
                f"\t\t\t(justify {justify} bottom)\n"
                f"\t\t)\n"
                f'\t\t(uuid "{uid}")\n'
                f"\t)\n"
            )
            _text_insert(schematic_path, text_sexp)
            logger.info(f"Added text '{text}' at {position}")
            return True
        except Exception as e:
            logger.error(f"Error adding text: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_hierarchical_label(
        schematic_path: Path,
        text: str,
        position: List[float],
        shape: str = "bidirectional",
        orientation: int = 0,
    ) -> bool:
        """Add a hierarchical label to a sub-sheet schematic."""
        try:
            label_text = _make_hierarchical_label_text(text, position, shape, orientation)
            _text_insert(schematic_path, label_text)
            logger.info(f"Added hierarchical_label '{text}' at {position} shape={shape}")
            return True
        except Exception as e:
            logger.error(f"Error adding hierarchical label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_sheet_pin(
        content: str,
        sheet_name: str,
        pin_name: str,
        pin_type: str,
        position: List[float],
        orientation: int = 0,
    ) -> Tuple[str, bool]:
        """Insert a sheet pin into the named sheet block in the parent schematic.

        Returns (modified_content, success).
        """
        lines = content.split("\n")
        sheetname_pattern = re.compile(
            r'\(property\s+"Sheetname"\s+"' + re.escape(sheet_name) + r'"'
        )
        sheet_block_pattern = re.compile(r"^\t\(sheet\b")

        # Find the sheet block that contains the target Sheetname property
        i = 0
        while i < len(lines):
            if sheet_block_pattern.match(lines[i]):
                # Walk forward to find closing paren of this block
                depth = sum(1 for c in lines[i] if c == "(") - sum(1 for c in lines[i] if c == ")")
                j = i + 1
                found_name = False
                while j < len(lines) and depth > 0:
                    if sheetname_pattern.search(lines[j]):
                        found_name = True
                    depth += sum(1 for c in lines[j] if c == "(") - sum(
                        1 for c in lines[j] if c == ")"
                    )
                    j += 1
                b_end = j - 1  # index of closing ")" line of the sheet block

                if found_name:
                    # Insert pin text before the closing paren of the sheet block
                    pin_text = _make_sheet_pin_text(pin_name, pin_type, position, orientation)
                    pin_lines = pin_text.rstrip("\n").split("\n")
                    for offset, line in enumerate(pin_lines):
                        lines.insert(b_end + offset, line)
                    logger.info(f"Added sheet pin '{pin_name}' to sheet '{sheet_name}'")
                    return "\n".join(lines), True

                i = b_end + 1
                continue
            i += 1

        return content, False


if __name__ == "__main__":
    # Test wire creation
    import shutil
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    print("=" * 80)
    print("WIRE MANAGER TEST")
    print("=" * 80)

    # Create test schematic (cross-platform temp directory)
    test_path = Path(tempfile.gettempdir()) / "test_wire_manager.kicad_sch"
    template_path = Path(__file__).parent.parent / "templates" / "empty.kicad_sch"

    shutil.copy(template_path, test_path)
    print(f"\n✓ Created test schematic: {test_path}")

    # Test 1: Add simple wire
    print("\n[1/4] Testing simple wire creation...")
    success = WireManager.add_wire(test_path, [50.8, 50.8], [101.6, 50.8])
    print(f"  {'✓' if success else '✗'} Simple wire: {success}")

    # Test 2: Add orthogonal wire
    print("\n[2/4] Testing orthogonal wire...")
    path = WireManager.create_orthogonal_path([50.8, 60.96], [101.6, 88.9])
    print(f"  Orthogonal path: {path}")
    success = WireManager.add_polyline_wire(test_path, path)
    print(f"  {'✓' if success else '✗'} Polyline wire: {success}")

    # Test 3: Add label
    print("\n[3/4] Testing label creation...")
    success = WireManager.add_label(test_path, "VCC", [76.2, 50.8])
    print(f"  {'✓' if success else '✗'} Label: {success}")

    # Test 4: Add no-connect
    print("\n[4/4] Testing no-connect creation...")
    success = WireManager.add_no_connect(test_path, [127, 50.8])
    print(f"  {'✓' if success else '✗'} No-connect: {success}")

    # Verify with kicad-skip
    print("\n[Verification] Loading with kicad-skip...")
    try:
        from skip import Schematic

        sch = Schematic(str(test_path))
        wire_count = len(list(sch.wire)) if hasattr(sch, "wire") else 0
        print(f"  ✓ Loaded successfully")
        print(f"  ✓ Wire count: {wire_count}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

    print("\n" + "=" * 80)
    print(f"Test schematic saved: {test_path}")
    print("Open in KiCad to verify visual appearance!")
    print("=" * 80)
