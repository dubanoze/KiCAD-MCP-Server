"""
Board outline command implementations for KiCAD interface
"""

import logging
import math
from typing import Any, Dict, Optional

import pcbnew

logger = logging.getLogger("kicad_interface")


class BoardOutlineCommands:
    """Handles board outline operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def add_board_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a board outline to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Claude sends dimensions nested inside a "params" key:
            # {"shape": "rectangle", "params": {"x": 0, "y": 0, "width": 38, ...}}
            # Unwrap the inner dict if present so we read dimensions from the right level.
            inner = params.get("params", params)

            shape = params.get("shape", "rectangle")
            width = inner.get("width")
            height = inner.get("height")
            radius = inner.get("radius")
            # Accept both "cornerRadius" and "radius" regardless of shape name.
            # The AI often sends shape=”rectangle” with radius=2.5 — we treat that as rounded_rectangle.
            corner_radius = inner.get("cornerRadius", inner.get("radius", 0))
            if shape == "rectangle" and corner_radius > 0:
                shape = "rounded_rectangle"
            points = inner.get("points", [])
            unit = inner.get("unit", "mm")

            # Position: accept top-left corner (x/y) or center (centerX/centerY).
            # Default: top-left at (0,0) so the board occupies positive coordinate space
            # and is consistent with component placement coordinates.
            x = inner.get("x")
            y = inner.get("y")
            if x is not None or y is not None:
                ox = x if x is not None else 0.0
                oy = y if y is not None else 0.0
                center_x = ox + (width or 0) / 2.0
                center_y = oy + (height or 0) / 2.0
            else:
                raw_cx = inner.get("centerX")
                raw_cy = inner.get("centerY")
                if raw_cx is not None or raw_cy is not None:
                    center_x = raw_cx if raw_cx is not None else 0.0
                    center_y = raw_cy if raw_cy is not None else 0.0
                else:
                    # No position given → place top-left at (0,0)
                    center_x = (width or 0) / 2.0
                    center_y = (height or 0) / 2.0

            if shape not in ["rectangle", "circle", "polygon", "rounded_rectangle"]:
                return {
                    "success": False,
                    "message": "Invalid shape",
                    "errorDetails": f"Shape '{shape}' not supported",
                }

            # Convert to internal units (nanometers)
            scale = (
                1000000 if unit == "mm" else (25400 if unit == "mil" else 25400000)
            )  # mm, mil, or inch to nm

            # Create drawing for edge cuts
            edge_layer = self.board.GetLayerID("Edge.Cuts")

            if shape == "rectangle":
                if width is None or height is None:
                    return {
                        "success": False,
                        "message": "Missing dimensions",
                        "errorDetails": "Both width and height are required for rectangle",
                    }

                width_nm = int(width * scale)
                height_nm = int(height * scale)
                center_x_nm = int(center_x * scale)
                center_y_nm = int(center_y * scale)

                # Create rectangle
                top_left = pcbnew.VECTOR2I(
                    center_x_nm - width_nm // 2, center_y_nm - height_nm // 2
                )
                top_right = pcbnew.VECTOR2I(
                    center_x_nm + width_nm // 2, center_y_nm - height_nm // 2
                )
                bottom_right = pcbnew.VECTOR2I(
                    center_x_nm + width_nm // 2, center_y_nm + height_nm // 2
                )
                bottom_left = pcbnew.VECTOR2I(
                    center_x_nm - width_nm // 2, center_y_nm + height_nm // 2
                )

                # Add lines for rectangle
                self._add_edge_line(top_left, top_right, edge_layer)
                self._add_edge_line(top_right, bottom_right, edge_layer)
                self._add_edge_line(bottom_right, bottom_left, edge_layer)
                self._add_edge_line(bottom_left, top_left, edge_layer)

            elif shape == "rounded_rectangle":
                if width is None or height is None:
                    return {
                        "success": False,
                        "message": "Missing dimensions",
                        "errorDetails": "Both width and height are required for rounded rectangle",
                    }

                width_nm = int(width * scale)
                height_nm = int(height * scale)
                center_x_nm = int(center_x * scale)
                center_y_nm = int(center_y * scale)
                corner_radius_nm = int(corner_radius * scale)

                # Create rounded rectangle
                self._add_rounded_rect(
                    center_x_nm,
                    center_y_nm,
                    width_nm,
                    height_nm,
                    corner_radius_nm,
                    edge_layer,
                )

            elif shape == "circle":
                if radius is None:
                    return {
                        "success": False,
                        "message": "Missing radius",
                        "errorDetails": "Radius is required for circle",
                    }

                center_x_nm = int(center_x * scale)
                center_y_nm = int(center_y * scale)
                radius_nm = int(radius * scale)

                # Create circle
                circle = pcbnew.PCB_SHAPE(self.board)
                circle.SetShape(pcbnew.SHAPE_T_CIRCLE)
                circle.SetCenter(pcbnew.VECTOR2I(center_x_nm, center_y_nm))
                circle.SetEnd(pcbnew.VECTOR2I(center_x_nm + radius_nm, center_y_nm))
                circle.SetLayer(edge_layer)
                circle.SetWidth(0)  # Zero width for edge cuts
                self.board.Add(circle)

            elif shape == "polygon":
                if not points or len(points) < 3:
                    return {
                        "success": False,
                        "message": "Missing points",
                        "errorDetails": "At least 3 points are required for polygon",
                    }

                # Convert points to nm
                polygon_points = []
                for point in points:
                    x_nm = int(point["x"] * scale)
                    y_nm = int(point["y"] * scale)
                    polygon_points.append(pcbnew.VECTOR2I(x_nm, y_nm))

                # Add lines for polygon
                for i in range(len(polygon_points)):
                    self._add_edge_line(
                        polygon_points[i],
                        polygon_points[(i + 1) % len(polygon_points)],
                        edge_layer,
                    )

            return {
                "success": True,
                "message": f"Added board outline: {shape}",
                "outline": {
                    "shape": shape,
                    "width": width,
                    "height": height,
                    "center": {"x": center_x, "y": center_y, "unit": unit},
                    "radius": radius,
                    "cornerRadius": corner_radius,
                    "points": points,
                },
            }

        except Exception as e:
            logger.error(f"Error adding board outline: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add board outline",
                "errorDetails": str(e),
            }

    def add_mounting_hole(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a mounting hole to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            position = params.get("position")
            diameter = params.get("diameter")
            pad_diameter = params.get("padDiameter")
            plated = params.get("plated", False)
            footprint_lib_id = params.get("footprintLibId")

            if not position or not diameter:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "position and diameter are required",
                }

            # Convert to internal units (nanometers)
            scale = (
                1000000
                if position.get("unit", "mm") == "mm"
                else (25400 if position.get("unit", "mm") == "mil" else 25400000)
            )  # mm, mil, or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            diameter_nm = int(diameter * scale)
            pad_diameter_nm = (
                int(pad_diameter * scale) if pad_diameter else diameter_nm + scale
            )  # 1mm larger by default

            # Create footprint for mounting hole with unique reference
            existing_mh = [
                fp.GetReference()
                for fp in self.board.GetFootprints()
                if fp.GetReference().startswith("MH")
            ]
            next_num = 1
            while f"MH{next_num}" in existing_mh:
                next_num += 1

            module = pcbnew.FOOTPRINT(self.board)
            module.SetReference(f"MH{next_num}")
            module.SetValue(f"MountingHole_{diameter}mm")

            # Set a real library:name FPID. Without this, the footprint is
            # written as `(footprint "" ...)` and KiCad's GUI Move tool refuses
            # to select it (no library link → not draggable in the editor).
            if not footprint_lib_id:
                # Strip trailing zeros so 3.2 → "3.2" not "3.20"
                footprint_lib_id = f"MountingHole:MountingHole_{diameter:g}mm"
            if ":" in footprint_lib_id:
                lib_name, fp_name = footprint_lib_id.split(":", 1)
            else:
                lib_name = "MountingHole"
                fp_name = footprint_lib_id
            module.SetFPID(pcbnew.LIB_ID(lib_name, fp_name))

            # Create the pad for the hole
            pad = pcbnew.PAD(module)
            pad.SetNumber(1)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH if plated else pcbnew.PAD_ATTRIB_NPTH)
            pad.SetSize(pcbnew.VECTOR2I(pad_diameter_nm, pad_diameter_nm))
            pad.SetDrillSize(pcbnew.VECTOR2I(diameter_nm, diameter_nm))
            pad.SetPosition(pcbnew.VECTOR2I(0, 0))  # Position relative to module

            if not plated:
                # NPTH must not include *.Cu in pad layers. The default LSET
                # for a circular pad is *.Cu + *.Mask; on a NPTH with
                # padDiameter > diameter that produces phantom copper annular
                # rings on every Cu layer, which trip clearance DRC against
                # neighbouring nets.
                mask_only = pcbnew.LSET()
                mask_only.AddLayer(pcbnew.F_Mask)
                mask_only.AddLayer(pcbnew.B_Mask)
                pad.SetLayerSet(mask_only)

            module.Add(pad)

            # Position the mounting hole
            module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Add to board
            self.board.Add(module)

            return {
                "success": True,
                "message": "Added mounting hole",
                "mountingHole": {
                    "position": position,
                    "diameter": diameter,
                    "padDiameter": pad_diameter or diameter + 1,
                    "plated": plated,
                    "footprintLibId": f"{lib_name}:{fp_name}",
                },
            }

        except Exception as e:
            logger.error(f"Error adding mounting hole: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add mounting hole",
                "errorDetails": str(e),
            }

    def add_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add text annotation to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            text = params.get("text")
            position = params.get("position")
            layer = params.get("layer", "F.SilkS")
            size = params.get("size", 1.0)
            thickness = params.get("thickness", 0.15)
            rotation = params.get("rotation", 0)
            mirror = params.get("mirror", False)

            if not text or not position:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "text and position are required",
                }

            # Convert to internal units (nanometers)
            scale = (
                1000000
                if position.get("unit", "mm") == "mm"
                else (25400 if position.get("unit", "mm") == "mil" else 25400000)
            )  # mm, mil, or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            size_nm = int(size * scale)
            thickness_nm = int(thickness * scale)

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Create text
            pcb_text = pcbnew.PCB_TEXT(self.board)
            pcb_text.SetText(text)
            pcb_text.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))
            pcb_text.SetLayer(layer_id)
            pcb_text.SetTextSize(pcbnew.VECTOR2I(size_nm, size_nm))
            pcb_text.SetTextThickness(thickness_nm)

            # Set rotation angle - KiCAD 9.0 uses EDA_ANGLE
            try:
                # Try KiCAD 9.0+ API (EDA_ANGLE)
                angle = pcbnew.EDA_ANGLE(rotation, pcbnew.DEGREES_T)
                pcb_text.SetTextAngle(angle)
            except (AttributeError, TypeError):
                # Fall back to older API (decidegrees as integer)
                pcb_text.SetTextAngle(int(rotation * 10))

            pcb_text.SetMirrored(mirror)

            # Add to board
            self.board.Add(pcb_text)

            return {
                "success": True,
                "message": "Added text annotation",
                "text": {
                    "text": text,
                    "position": position,
                    "layer": layer,
                    "size": size,
                    "thickness": thickness,
                    "rotation": rotation,
                    "mirror": mirror,
                },
            }

        except Exception as e:
            logger.error(f"Error adding text: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add text",
                "errorDetails": str(e),
            }

    def _add_edge_line(self, start: pcbnew.VECTOR2I, end: pcbnew.VECTOR2I, layer: int) -> None:
        """Add a line to the edge cuts layer"""
        line = pcbnew.PCB_SHAPE(self.board)
        line.SetShape(pcbnew.SHAPE_T_SEGMENT)
        line.SetStart(start)
        line.SetEnd(end)
        line.SetLayer(layer)
        line.SetWidth(0)  # Zero width for edge cuts
        self.board.Add(line)

    def add_edge_cut_line(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a single straight graphic segment on a layer (default Edge.Cuts).

        Used to patch/close a board outline (e.g. after delete_pcb_shape removed
        an edge-slot detour) without redrawing the whole outline.

        Params:
            x1, y1, x2, y2 – segment endpoints (mm, required)
            unit  – "mm" (default)
            layer – layer name (default "Edge.Cuts")
            width – stroke width mm (default 0.0 = hairline, canonical for Edge.Cuts)
        """
        if not self.board:
            return {"success": False, "message": "No board is loaded"}
        try:
            x1 = float(params["x1"]); y1 = float(params["y1"])
            x2 = float(params["x2"]); y2 = float(params["y2"])
        except (KeyError, TypeError, ValueError):
            return {"success": False, "message": "x1,y1,x2,y2 are required (numbers)"}

        unit = params.get("unit", "mm")
        layer_name = params.get("layer", "Edge.Cuts")
        width_mm = float(params.get("width", 0.0))

        def to_nm(v):
            return pcbnew.FromMM(v) if unit == "mm" else int(v)

        layer_id = self.board.GetLayerID(layer_name)
        if layer_id < 0:
            return {"success": False, "message": f"Unknown layer: {layer_name}"}

        seg = pcbnew.PCB_SHAPE(self.board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(layer_id)
        seg.SetWidth(to_nm(width_mm) if width_mm > 0 else 0)
        seg.SetStart(pcbnew.VECTOR2I(to_nm(x1), to_nm(y1)))
        seg.SetEnd(pcbnew.VECTOR2I(to_nm(x2), to_nm(y2)))
        self.board.Add(seg)
        self.board.SetModified()
        pcbnew.Refresh()
        return {
            "success": True,
            "message": f"Added {layer_name} segment ({x1},{y1})->({x2},{y2})",
            "layer": layer_name,
        }

    def _add_rounded_rect(
        self,
        center_x_nm: int,
        center_y_nm: int,
        width_nm: int,
        height_nm: int,
        radius_nm: int,
        layer: int,
    ) -> None:
        """Add a rounded rectangle to the edge cuts layer"""
        if radius_nm <= 0:
            # If no radius, create regular rectangle
            top_left = pcbnew.VECTOR2I(center_x_nm - width_nm // 2, center_y_nm - height_nm // 2)
            top_right = pcbnew.VECTOR2I(center_x_nm + width_nm // 2, center_y_nm - height_nm // 2)
            bottom_right = pcbnew.VECTOR2I(
                center_x_nm + width_nm // 2, center_y_nm + height_nm // 2
            )
            bottom_left = pcbnew.VECTOR2I(center_x_nm - width_nm // 2, center_y_nm + height_nm // 2)

            self._add_edge_line(top_left, top_right, layer)
            self._add_edge_line(top_right, bottom_right, layer)
            self._add_edge_line(bottom_right, bottom_left, layer)
            self._add_edge_line(bottom_left, top_left, layer)
            return

        # Calculate corner centers
        half_width = width_nm // 2
        half_height = height_nm // 2

        # Ensure radius is not larger than half the smallest dimension
        max_radius = min(half_width, half_height)
        if radius_nm > max_radius:
            radius_nm = max_radius

        # Calculate corner centers
        top_left_center = pcbnew.VECTOR2I(
            center_x_nm - half_width + radius_nm, center_y_nm - half_height + radius_nm
        )
        top_right_center = pcbnew.VECTOR2I(
            center_x_nm + half_width - radius_nm, center_y_nm - half_height + radius_nm
        )
        bottom_right_center = pcbnew.VECTOR2I(
            center_x_nm + half_width - radius_nm, center_y_nm + half_height - radius_nm
        )
        bottom_left_center = pcbnew.VECTOR2I(
            center_x_nm - half_width + radius_nm, center_y_nm + half_height - radius_nm
        )

        # Add arcs for corners
        self._add_corner_arc(top_left_center, radius_nm, 180, 270, layer)
        self._add_corner_arc(top_right_center, radius_nm, 270, 0, layer)
        self._add_corner_arc(bottom_right_center, radius_nm, 0, 90, layer)
        self._add_corner_arc(bottom_left_center, radius_nm, 90, 180, layer)

        # Add lines for straight edges
        # Top edge
        self._add_edge_line(
            pcbnew.VECTOR2I(top_left_center.x, top_left_center.y - radius_nm),
            pcbnew.VECTOR2I(top_right_center.x, top_right_center.y - radius_nm),
            layer,
        )
        # Right edge
        self._add_edge_line(
            pcbnew.VECTOR2I(top_right_center.x + radius_nm, top_right_center.y),
            pcbnew.VECTOR2I(bottom_right_center.x + radius_nm, bottom_right_center.y),
            layer,
        )
        # Bottom edge
        self._add_edge_line(
            pcbnew.VECTOR2I(bottom_right_center.x, bottom_right_center.y + radius_nm),
            pcbnew.VECTOR2I(bottom_left_center.x, bottom_left_center.y + radius_nm),
            layer,
        )
        # Left edge
        self._add_edge_line(
            pcbnew.VECTOR2I(bottom_left_center.x - radius_nm, bottom_left_center.y),
            pcbnew.VECTOR2I(top_left_center.x - radius_nm, top_left_center.y),
            layer,
        )

    def add_board_cutout(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add an arbitrary polygon cutout to Edge.Cuts and optionally create a keepout
        zone covering the same polygon on all copper layers.

        Params:
            points   – list of {x, y} vertices in order (mm), e.g. trapezoidal slot
            unit     – "mm" (default)
            keepout  – true (default) = also add a copper keepout zone on every layer
            keepout_clearance – extra clearance around keepout polygon in mm (default 0.2)
        """
        if not self.board:
            return {"success": False, "message": "No board is loaded"}

        raw_pts = params.get("points", [])
        unit = params.get("unit", "mm")
        add_keepout = params.get("keepout", True)
        keepout_clr = float(params.get("keepout_clearance", 0.2))

        if len(raw_pts) < 3:
            return {"success": False, "message": "Need at least 3 points for a cutout polygon"}

        def to_nm(v):
            return pcbnew.FromMM(v) if unit == "mm" else int(v)

        pts_nm = [pcbnew.VECTOR2I(to_nm(p["x"]), to_nm(p["y"])) for p in raw_pts]

        # --- Edge slot vs window cutout ---
        # A closed poly overlapping the existing outline makes the outline
        # self-intersecting (DRC: "malformed outline"). If the polygon crosses
        # exactly one straight Edge.Cuts segment in exactly two points, embed
        # the slot into the outline instead: split that segment and stitch the
        # interior part of the polygon in as line segments.
        edge_layer = pcbnew.Edge_Cuts
        merged = self._try_merge_edge_slot(pts_nm)
        if not merged:
            poly = pcbnew.PCB_SHAPE(self.board)
            poly.SetShape(pcbnew.SHAPE_T_POLY)
            poly.SetLayer(edge_layer)
            poly.SetWidth(0)
            pts = pcbnew.VECTOR_VECTOR2I()
            for p in pts_nm:
                pts.push_back(p)
            poly.SetPolyPoints(pts)
            # SHAPE_T_POLY is implicitly closed — no SetClosed() needed in KiCad 10
            self.board.Add(poly)

        keepout_result = None
        if add_keepout:
            # Create a RULE_AREA (keepout zone) covering all copper layers
            try:
                zone = pcbnew.ZONE(self.board)
                zone.SetIsRuleArea(True)
                zone.SetDoNotAllowZoneFills(True)   # KiCad 10: was SetDoNotAllowCopperPour
                zone.SetDoNotAllowTracks(True)
                zone.SetDoNotAllowVias(True)
                zone.SetDoNotAllowPads(False)
                zone.SetDoNotAllowFootprints(False)
                # Apply to all copper layers (F.Cu through B.Cu)
                zone.SetLayerSet(pcbnew.LSET.AllCuMask())
                outline = zone.Outline()
                outline.NewOutline()
                for p in pts_nm:
                    outline.Append(p.x, p.y)
                zone.SetMinIslandArea(0)
                self.board.Add(zone)
                keepout_result = {"added": True, "layers": "all_copper", "clearance_mm": keepout_clr}
            except Exception as e:
                keepout_result = {"added": False, "error": str(e)}

        self.board.SetModified()
        pcbnew.Refresh()
        mode = "edge slot merged into outline" if merged else "closed window polygon"
        return {
            "success": True,
            "message": f"Added cutout ({len(raw_pts)} points, {mode}) on Edge.Cuts"
                       + (f" + keepout on all copper layers" if add_keepout and keepout_result and keepout_result.get("added") else ""),
            "points": len(raw_pts),
            "mode": "edge_slot" if merged else "window",
            "keepout": keepout_result,
        }

    def _try_merge_edge_slot(self, pts_nm) -> bool:
        """Embed a cutout polygon into the board outline as an edge slot.

        Looks for exactly one straight Edge.Cuts segment crossed by the polygon
        boundary in exactly two points (and no crossings with any other outline
        element). On match: splits that segment at the crossing points and adds
        the interior chain of polygon vertices as outline segments. Returns True
        when merged; False means the caller should fall back to a closed poly.
        """
        EPS = 1000  # 1 µm in nm

        def cross(ox, oy, ax, ay, bx, by):
            return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)

        def seg_intersect(p1, p2, p3, p4):
            """Proper segment intersection point or None (touch counts)."""
            d1x, d1y = p2.x - p1.x, p2.y - p1.y
            d2x, d2y = p4.x - p3.x, p4.y - p3.y
            den = d1x * d2y - d1y * d2x
            if den == 0:
                return None
            t = ((p3.x - p1.x) * d2y - (p3.y - p1.y) * d2x) / den
            u = ((p3.x - p1.x) * d1y - (p3.y - p1.y) * d1x) / den
            if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
                return pcbnew.VECTOR2I(int(round(p1.x + t * d1x)),
                                       int(round(p1.y + t * d1y)))
            return None

        edge_lines, edge_others = [], []
        for d in self.board.GetDrawings():
            if d.GetLayer() != pcbnew.Edge_Cuts:
                continue
            try:
                shape = d.GetShape()
            except Exception:
                continue
            (edge_lines if shape == pcbnew.SHAPE_T_SEGMENT else edge_others).append(d)

        n = len(pts_nm)
        hits = {}  # line drawing -> list of (poly_edge_idx, point)
        for li, line in enumerate(edge_lines):
            ls, le = line.GetStart(), line.GetEnd()
            for i in range(n):
                p = seg_intersect(pts_nm[i], pts_nm[(i + 1) % n], ls, le)
                if p is not None:
                    hits.setdefault(li, []).append((i, p))
        # Polygon must not cross arcs/other outline elements — too ambiguous.
        for other in edge_others:
            bb = other.GetBoundingBox()
            for i in range(n):
                a, b = pts_nm[i], pts_nm[(i + 1) % n]
                if (max(a.x, b.x) >= bb.GetLeft() and min(a.x, b.x) <= bb.GetRight()
                        and max(a.y, b.y) >= bb.GetTop() and min(a.y, b.y) <= bb.GetBottom()):
                    # bbox proximity only — be conservative and only bail when
                    # the polygon edge truly crosses the arc's chord
                    if seg_intersect(a, b, other.GetStart(), other.GetEnd()) is not None:
                        return False

        crossed = [(li, pl) for li, pl in hits.items() if len(pl) > 0]
        if len(crossed) != 1 or len(crossed[0][1]) != 2:
            return False
        li, ((ia, pa), (ib, pb)) = crossed[0][0], sorted(crossed[0][1])
        line = edge_lines[li]
        ls, le = line.GetStart(), line.GetEnd()

        # Interior side of the crossed line = side where the board bbox centre is
        bbox = self.board.GetBoardEdgesBoundingBox()
        c = bbox.GetCenter()
        interior_sign = cross(ls.x, ls.y, le.x, le.y, c.x, c.y)
        if interior_sign == 0:
            return False

        # Candidate chain: vertices strictly between the two crossing edges
        chain = [pts_nm[k % n] for k in range(ia + 1, ib + 1)]
        def chain_interior(ch):
            return all(cross(ls.x, ls.y, le.x, le.y, v.x, v.y) * interior_sign > 0
                       for v in ch)
        if not chain_interior(chain):
            chain = [pts_nm[k % n] for k in range(ib + 1, ia + 1 + n)]
            if not chain_interior(chain):
                return False
            pa, pb = pb, pa  # complementary chain runs from the other crossing

        # Order the crossing points along the original segment
        def t_of(p):
            dx, dy = le.x - ls.x, le.y - ls.y
            return ((p.x - ls.x) * dx + (p.y - ls.y) * dy) / float(dx * dx + dy * dy)
        t_pa, t_pb = t_of(pa), t_of(pb)
        first, last = (pa, pb) if t_pa <= t_pb else (pb, pa)

        def dist2(a, b):
            return (a.x - b.x) ** 2 + (a.y - b.y) ** 2

        new_segs = []
        if dist2(ls, first) > EPS * EPS:
            new_segs.append((ls, first))
        if dist2(last, le) > EPS * EPS:
            new_segs.append((last, le))
        path = [pa] + chain + [pb]
        for i in range(len(path) - 1):
            if dist2(path[i], path[i + 1]) > EPS * EPS:
                new_segs.append((path[i], path[i + 1]))

        self.board.Remove(line)
        for a, b in new_segs:
            seg = pcbnew.PCB_SHAPE(self.board)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetLayer(pcbnew.Edge_Cuts)
            seg.SetWidth(line.GetWidth() or pcbnew.FromMM(0.05))
            seg.SetStart(a)
            seg.SetEnd(b)
            self.board.Add(seg)
        return True

    def delete_pcb_shape(self, params: dict) -> dict:
        """Delete the PCB drawing (line, arc, polygon, rect) nearest to a given point.

        Params:
            x, y      – search point in mm (required)
            layer     – layer name filter, e.g. "Edge.Cuts" (default: any layer)
            shape_type – optional filter: "polygon","line","arc","rect","any" (default: "any")
            tolerance – max search radius in mm (default: 5.0)
        """
        if not self.board:
            return {"success": False, "message": "No board loaded"}

        x_mm = params.get("x"); y_mm = params.get("y")
        if x_mm is None or y_mm is None:
            return {"success": False, "message": "x and y are required"}

        layer_name = params.get("layer", None)
        shape_filter = params.get("shape_type", "any").lower()
        tolerance = float(params.get("tolerance", 5.0))

        target_x = pcbnew.FromMM(float(x_mm))
        target_y = pcbnew.FromMM(float(y_mm))
        tol_nm = pcbnew.FromMM(tolerance)

        # Map layer name to ID
        layer_id = None
        if layer_name:
            layer_id = self.board.GetLayerID(layer_name)
            if layer_id < 0:
                return {"success": False, "message": f"Unknown layer: {layer_name}"}

        # Map shape_filter to SHAPE_T_* values
        SHAPE_MAP = {
            "segment": 0, "line": 0,
            "rect": 1,
            "arc": 2,
            "circle": 3,
            "polygon": 4, "poly": 4,
            "bezier": 5,
        }
        wanted_shape = SHAPE_MAP.get(shape_filter, None) if shape_filter != "any" else None

        best = None
        best_dist = float("inf")

        for drawing in self.board.GetDrawings():
            if layer_id is not None and drawing.GetLayer() != layer_id:
                continue
            if wanted_shape is not None:
                try:
                    if drawing.GetShape() != wanted_shape:
                        continue
                except Exception:
                    continue

            # Use bounding-box centre as the shape's representative point
            try:
                bb = drawing.GetBoundingBox()
                cx = bb.GetCenter().x
                cy = bb.GetCenter().y
            except Exception:
                cx = drawing.GetX()
                cy = drawing.GetY()

            dx = cx - target_x; dy = cy - target_y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < best_dist:
                best_dist = dist
                best = drawing

        # Also search ZONE / RULE_AREA objects
        for zone in self.board.Zones():
            try:
                bb = zone.GetBoundingBox()
                zcx = bb.GetCenter().x; zcy = bb.GetCenter().y
            except Exception:
                continue
            dx = zcx - target_x; dy = zcy - target_y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < best_dist:
                # Apply layer filter if requested (zones can span multiple layers).
                # KiCad 10 renamed LSET.test() -> Contains(); support both.
                if layer_id is not None:
                    ls = zone.GetLayerSet()
                    contains = getattr(ls, "Contains", None) or getattr(ls, "test", None)
                    if contains is not None and not contains(layer_id):
                        continue
                best_dist = dist
                best = zone

        if best is None or best_dist > tol_nm:
            return {
                "success": False,
                "message": f"No PCB shape or zone found within {tolerance} mm of ({x_mm}, {y_mm})"
                           + (f" on layer {layer_name}" if layer_name else ""),
            }

        # Collect info before deletion
        is_zone = isinstance(best, pcbnew.ZONE)
        if is_zone:
            try: bb = best.GetBoundingBox(); cx = pcbnew.ToMM(bb.GetCenter().x); cy = pcbnew.ToMM(bb.GetCenter().y)
            except Exception: cx, cy = 0, 0
            layer_str = "ZONE/RULE_AREA"
            shape_type_num = "zone"
        else:
            try: shape_type_num = best.GetShape()
            except Exception: shape_type_num = -1
            try: bb = best.GetBoundingBox(); cx = pcbnew.ToMM(bb.GetCenter().x); cy = pcbnew.ToMM(bb.GetCenter().y)
            except Exception: cx, cy = pcbnew.ToMM(best.GetX()), pcbnew.ToMM(best.GetY())
            layer_str = self.board.GetLayerName(best.GetLayer())

        self.board.Remove(best)
        self.board.SetModified()
        pcbnew.Refresh()

        return {
            "success": True,
            "message": f"Deleted {layer_str} (type={shape_type_num}) near ({cx:.2f}, {cy:.2f}) mm",
            "deleted": {"layer": layer_str, "shape_type": str(shape_type_num),
                        "center_mm": {"x": cx, "y": cy}, "dist_mm": round(pcbnew.ToMM(best_dist), 3)},
        }

    def _add_corner_arc(
        self,
        center: pcbnew.VECTOR2I,
        radius: int,
        start_angle: float,
        end_angle: float,
        layer: int,
    ) -> None:
        """Add an arc for a rounded corner"""
        # Create arc for corner
        arc = pcbnew.PCB_SHAPE(self.board)
        arc.SetShape(pcbnew.SHAPE_T_ARC)
        arc.SetCenter(center)

        # Calculate start and end points
        start_x = center.x + int(radius * math.cos(math.radians(start_angle)))
        start_y = center.y + int(radius * math.sin(math.radians(start_angle)))
        end_x = center.x + int(radius * math.cos(math.radians(end_angle)))
        end_y = center.y + int(radius * math.sin(math.radians(end_angle)))

        arc.SetStart(pcbnew.VECTOR2I(start_x, start_y))
        arc.SetEnd(pcbnew.VECTOR2I(end_x, end_y))
        arc.SetLayer(layer)
        arc.SetWidth(0)  # Zero width for edge cuts
        self.board.Add(arc)
