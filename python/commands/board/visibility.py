"""
Board layer visibility and view utilities.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pcbnew

logger = logging.getLogger("kicad_interface")

# KiCad layer-name → layer-ID mapping (standard layers only)
_LAYER_IDS: Dict[str, int] = {
    "F.Cu": 0, "B.Cu": 31,
    "F.Adhesive": 32, "B.Adhesive": 33,
    "F.Paste": 34, "B.Paste": 35,
    "F.Silkscreen": 36, "B.Silkscreen": 37,
    "F.Mask": 38, "B.Mask": 39,
    "User.Drawings": 40, "User.Comments": 41,
    "User.Eco1": 42, "User.Eco2": 43,
    "Edge.Cuts": 44,
    "F.Courtyard": 46, "B.Courtyard": 47,
    "F.Fab": 48, "B.Fab": 49,
    "In1.Cu": 1, "In2.Cu": 2, "In3.Cu": 3, "In4.Cu": 4,
    "In5.Cu": 5, "In6.Cu": 6, "In7.Cu": 7, "In8.Cu": 8,
    "Margin": 45,
}

# All standard layers visible bitmask (128-bit as 4×32 hex groups)
_ALL_VISIBLE = (1 << 64) - 1   # lower 64 bits all set; upper 64 = 0 in KiCad 10


class BoardVisibilityCommands:
    """Layer visibility and sheet-centering commands."""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        self.board = board

    # ------------------------------------------------------------------ #
    #  set_layer_visibility                                                #
    # ------------------------------------------------------------------ #
    def set_layer_visibility(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Show or hide named layers by writing a preset into .kicad_pro.

        Params:
            layers   – list of layer names, e.g. ["F.Courtyard", "B.Courtyard"]
            visible  – true = show, false = hide  (default: false)
            preset_name – name for the preset entry (default: "custom")
        """
        if not self.board:
            return {"success": False, "message": "No board loaded"}

        layers: List[str] = params.get("layers", [])
        visible: bool = bool(params.get("visible", False))
        preset_name: str = params.get("preset_name", "custom")

        pro_path = self._find_pro_file()
        if pro_path is None:
            return {"success": False, "message": "Could not locate .kicad_pro file"}

        # Load project JSON
        try:
            with open(pro_path, encoding="utf-8") as f:
                project = json.load(f)
        except Exception as e:
            return {"success": False, "message": f"Failed to read .kicad_pro: {e}"}

        # Resolve existing visible-layers mask from active preset, or start with all visible
        board_section = project.setdefault("board", {})
        presets: List[Dict] = board_section.setdefault("layer_presets", [])

        active_name = board_section.get("active_layer_preset", "")
        existing = next((p for p in presets if p.get("name") == active_name), None)
        if existing and "visibleLayers" in existing:
            try:
                mask = int(existing["visibleLayers"], 16)
            except (ValueError, TypeError):
                mask = _ALL_VISIBLE
        else:
            mask = _ALL_VISIBLE

        changed: List[str] = []
        unknown: List[str] = []
        for name in layers:
            lid = _LAYER_IDS.get(name)
            if lid is None:
                unknown.append(name)
                continue
            if visible:
                mask |= (1 << lid)
            else:
                mask &= ~(1 << lid)
            changed.append(name)

        # Encode as 32-char hex string (128-bit, upper 64 = 0)
        vis_str = f"0x{mask & ((1 << 128) - 1):032x}"

        # Upsert the preset
        preset_entry = {"name": preset_name, "visibleLayers": vis_str}
        presets_by_name = {p["name"]: i for i, p in enumerate(presets)}
        if preset_name in presets_by_name:
            presets[presets_by_name[preset_name]] = preset_entry
        else:
            presets.append(preset_entry)

        board_section["active_layer_preset"] = preset_name

        try:
            with open(pro_path, "w", encoding="utf-8") as f:
                json.dump(project, f, indent=2)
        except Exception as e:
            return {"success": False, "message": f"Failed to write .kicad_pro: {e}"}

        msg = (
            f"{'Showed' if visible else 'Hid'} {len(changed)} layer(s): {', '.join(changed)}. "
            f"Preset '{preset_name}' saved. Reload the board in KiCad to apply."
        )
        if unknown:
            msg += f" Unknown layers ignored: {', '.join(unknown)}"
        return {"success": True, "message": msg, "changed": changed, "unknown": unknown,
                "preset": preset_name, "visibleLayers": vis_str}

    # ------------------------------------------------------------------ #
    #  center_board_on_sheet                                               #
    # ------------------------------------------------------------------ #
    def center_board_on_sheet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move all board content so the Edge.Cuts bounding box is centred on the
        current paper sheet.  Moves footprints, tracks, zones, drawings, vias.

        Params:
            sheet_width_mm  – override sheet width  (default: auto from board paper)
            sheet_height_mm – override sheet height (default: auto from board paper)
        """
        if not self.board:
            return {"success": False, "message": "No board loaded"}

        # Determine sheet size — PAGE_INFO SWIG bindings are dead in KiCad 10 headless.
        # Read paper type directly from the .kicad_pcb S-expression, then look up standard sizes.
        sheet_w = params.get("sheet_width_mm")
        sheet_h = params.get("sheet_height_mm")

        if not sheet_w or not sheet_h:
            w, h = self._get_sheet_size_mm()
            sheet_w = sheet_w or w
            sheet_h = sheet_h or h

        # Compute Edge.Cuts bounding box
        bbox = self.board.ComputeBoundingBox(aBoardEdgesOnly=True)
        if bbox.GetWidth() == 0 and bbox.GetHeight() == 0:
            return {"success": False, "message": "Board has no Edge.Cuts outline"}

        board_cx = pcbnew.ToMM(bbox.GetCenter().x)
        board_cy = pcbnew.ToMM(bbox.GetCenter().y)

        # KiCad coordinate origin is top-left; sheet centre in mm
        target_cx = sheet_w / 2
        target_cy = sheet_h / 2

        dx = pcbnew.FromMM(target_cx - board_cx)
        dy = pcbnew.FromMM(target_cy - board_cy)

        if abs(dx) < pcbnew.FromMM(0.1) and abs(dy) < pcbnew.FromMM(0.1):
            return {"success": True, "message": "Board is already centred on the sheet",
                    "dx_mm": 0, "dy_mm": 0}

        move = pcbnew.VECTOR2I(int(dx), int(dy))

        # Move footprints
        for fp in self.board.GetFootprints():
            fp.Move(move)

        # Move tracks and vias
        for track in self.board.GetTracks():
            track.Move(move)

        # Move zones
        for zone in self.board.Zones():
            zone.Move(move)

        # Move board drawings (Edge.Cuts, silkscreen graphics, etc.)
        for drawing in self.board.GetDrawings():
            drawing.Move(move)

        self.board.SetModified()
        pcbnew.Refresh()

        dx_mm = round(pcbnew.ToMM(dx), 3)
        dy_mm = round(pcbnew.ToMM(dy), 3)
        return {
            "success": True,
            "message": f"Board centred on {sheet_w}×{sheet_h} mm sheet. "
                       f"Moved by ({dx_mm}, {dy_mm}) mm.",
            "dx_mm": dx_mm,
            "dy_mm": dy_mm,
            "sheet_mm": {"width": sheet_w, "height": sheet_h},
        }

    # ------------------------------------------------------------------ #
    #  helpers                                                             #
    # ------------------------------------------------------------------ #
    def _get_sheet_size_mm(self):
        """Read paper type from .kicad_pcb S-expression and return (width_mm, height_mm).
        PAGE_INFO SWIG bindings are broken in KiCad 10 headless, so we parse the file directly."""
        import re
        PAPER_SIZES = {
            "A0": (1189, 841), "A1": (841, 594), "A2": (594, 420),
            "A3": (420, 297),  "A4": (297, 210),  "A5": (210, 148),
            "B0": (1414, 1000),"B1": (1000, 707), "B2": (707, 500),
            "B3": (500, 353),  "B4": (353, 250),
            "LETTER": (279, 216), "LEGAL": (356, 216), "LEDGER": (432, 279),
            "A": (279, 216), "B": (432, 279), "C": (559, 432), "D": (864, 559), "E": (1117, 864),
        }
        try:
            pcb_path = Path(self.board.GetFileName())
            text = pcb_path.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'\(paper\s+"?([^"\)\s]+)"?\s*(\w+)?', text)
            if m:
                paper_type = m.group(1).upper()
                portrait = (m.group(2) or "").lower() == "portrait"
                w, h = PAPER_SIZES.get(paper_type, (297, 210))
                return (h, w) if portrait else (w, h)
        except Exception as e:
            logger.warning(f"Could not read paper type from .kicad_pcb: {e}")
        return (297, 210)  # A4 landscape fallback

    def _find_pro_file(self) -> Optional[Path]:
        """Locate the .kicad_pro file next to the loaded board."""
        if not self.board:
            return None
        pcb_path = Path(self.board.GetFileName())
        pro = pcb_path.with_suffix(".kicad_pro")
        if pro.exists():
            return pro
        # Try parent directory
        for p in pcb_path.parent.glob("*.kicad_pro"):
            return p
        return None
