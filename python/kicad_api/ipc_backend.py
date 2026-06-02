"""
IPC API Backend (KiCAD 9.0+)

Uses the official kicad-python library for inter-process communication
with a running KiCAD instance. This enables REAL-TIME UI synchronization.

Note: Requires KiCAD to be running with IPC server enabled:
    Preferences > Plugins > Enable IPC API Server

Key Benefits over SWIG:
- Changes appear instantly in KiCAD UI (no reload needed)
- Transaction support for undo/redo
- Stable API that won't break between versions
- Multi-language support
"""

import logging
import os
import platform
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from kicad_api.base import APINotAvailableError, BoardAPI, ConnectionError, KiCADBackend

logger = logging.getLogger(__name__)

# Unit conversion constant: KiCAD IPC uses nanometers internally
MM_TO_NM = 1_000_000
INCH_TO_NM = 25_400_000


class IPCBackend(KiCADBackend):
    """
    KiCAD IPC API backend for real-time UI synchronization.

    Communicates with KiCAD via Protocol Buffers over UNIX sockets.
    Requires KiCAD 9.0+ to be running with IPC enabled.

    Changes made through this backend appear immediately in the KiCAD UI
    without requiring manual reload.
    """

    def __init__(self) -> None:
        self._kicad = None
        self._connected = False
        self._version: Optional[str] = None
        self._on_change_callbacks: List[Callable] = []

    @staticmethod
    def _windows_socket_candidates() -> list:
        """Build a de-duplicated list of likely Windows KiCad IPC socket paths.

        kipy's default is ``ipc://{tempfile.gettempdir()}\\kicad\\api.sock``. We
        cover the standard temp roots AND a ``\\claude`` sub-dir variant, because a
        sandbox-launched KiCad may set TMPDIR/TEMP to ``...\\Temp\\claude`` while this
        backend's own gettempdir() resolves to ``...\\Temp``. Each candidate is tried
        by the connect/ping loop; the first that answers wins.
        """
        import tempfile

        roots = []
        for ev in ("TMPDIR", "TEMP", "TMP"):
            v = os.environ.get(ev)
            if v:
                roots.append(v)
        roots.append(tempfile.gettempdir())
        la = os.environ.get("LOCALAPPDATA")
        if la:
            roots.append(os.path.join(la, "Temp"))

        candidates = []
        seen = set()
        for r in roots:
            r = r.rstrip("\\/")
            for base in (r, os.path.join(r, "claude")):
                sock = f"ipc://{base}\\kicad\\api.sock"
                if sock not in seen:
                    seen.add(sock)
                    candidates.append(sock)
        return candidates

    def connect(self, socket_path: Optional[str] = None) -> bool:
        """
        Connect to running KiCAD instance via IPC.

        Args:
            socket_path: Optional socket path. If not provided, will try common locations.
                        Use format: ipc:///tmp/kicad/api.sock

        Returns:
            True if connection successful

        Raises:
            ConnectionError: If connection fails
        """
        try:
            # Import here to allow module to load even without kicad-python
            from kipy import KiCad

            logger.info("Connecting to KiCAD via IPC...")

            # Try to connect with provided path or auto-detect
            socket_paths_to_try = []
            if socket_path:
                socket_paths_to_try.append(socket_path)
            else:
                # Common socket locations (Unix-like systems only)
                # Windows uses named pipes, handled by auto-detect
                if platform.system() != "Windows":
                    socket_paths_to_try.append("ipc:///tmp/kicad/api.sock")  # Linux default
                    # XDG runtime directory (requires getuid, Unix only)
                    if hasattr(os, "getuid"):
                        socket_paths_to_try.append(f"ipc:///run/user/{os.getuid()}/kicad/api.sock")
                else:
                    # Windows: KiCad creates the socket under its OWN temp dir
                    # (kipy default = gettempdir()\kicad\api.sock). When KiCad is
                    # launched from a different environment than this MCP backend
                    # (e.g. a sandbox that sets TMPDIR=...\Temp\claude), the two
                    # temp dirs differ and auto-detect fails. The socket is a named
                    # pipe and is NOT visible to os.path.exists/glob, so we cannot
                    # probe the filesystem — instead we enumerate likely temp roots
                    # (and their \claude sub-dir variant) and let the connect/ping
                    # loop below pick the first that actually answers.
                    socket_paths_to_try.extend(self._windows_socket_candidates())

                # Auto-detect for all platforms (Windows uses named pipes, Unix uses sockets)
                socket_paths_to_try.append(None)

            last_error = None
            for path in socket_paths_to_try:
                try:
                    if path:
                        logger.debug(f"Trying socket path: {path}")
                        self._kicad = KiCad(socket_path=path)
                    else:
                        logger.debug("Trying auto-detection")
                        self._kicad = KiCad()

                    # Verify connection with ping (ping returns None on success)
                    self._kicad.ping()
                    logger.info(f"Connected via socket: {path or 'auto-detected'}")
                    break
                except Exception as e:
                    last_error = e
                    logger.debug(f"Failed to connect via {path}: {e}")
                    continue
            else:
                # None of the paths worked
                raise ConnectionError(f"Could not connect to KiCAD IPC: {last_error}")

            # Get version info
            self._version = self._get_kicad_version()
            logger.info(f"Connected to KiCAD {self._version} via IPC")
            self._connected = True
            return True

        except ImportError as e:
            logger.error("kicad-python library not found")
            raise APINotAvailableError(
                "IPC backend requires kicad-python. " "Install with: pip install kicad-python"
            ) from e
        except Exception as e:
            logger.error(f"Failed to connect via IPC: {e}")
            logger.info(
                "Ensure KiCAD is running with IPC enabled: "
                "Preferences > Plugins > Enable IPC API Server"
            )
            raise ConnectionError(f"IPC connection failed: {e}") from e

    def _get_kicad_version(self) -> str:
        """Get KiCAD version string."""
        try:
            if self._kicad.check_version():
                return self._kicad.get_api_version()
            return "9.0+ (version mismatch)"
        except Exception:
            return "unknown"

    def disconnect(self) -> None:
        """Disconnect from KiCAD."""
        if self._kicad:
            self._kicad = None
            self._connected = False
            logger.info("Disconnected from KiCAD IPC")

    def is_connected(self) -> bool:
        """Check if connected to KiCAD."""
        if not self._connected or not self._kicad:
            return False
        try:
            # ping() returns None on success, raises on failure
            self._kicad.ping()
            return True
        except Exception:
            self._connected = False
            return False

    def get_version(self) -> str:
        """Get KiCAD version."""
        return self._version or "unknown"

    def register_change_callback(self, callback: Callable) -> None:
        """Register a callback to be called when changes are made."""
        self._on_change_callbacks.append(callback)

    def _notify_change(self, change_type: str, details: Dict[str, Any]) -> None:
        """Notify registered callbacks of a change."""
        for callback in self._on_change_callbacks:
            try:
                callback(change_type, details)
            except Exception as e:
                logger.warning(f"Change callback error: {e}")

    # Project Operations
    def create_project(self, path: Path, name: str) -> Dict[str, Any]:
        """
        Create a new KiCAD project.

        Note: The IPC API doesn't directly create projects.
        Projects must be created through the UI or file system.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        # IPC API doesn't have project creation - use file-based approach
        logger.warning("Project creation via IPC not fully supported - using hybrid approach")

        # For now, we'll return info about what needs to happen
        return {
            "success": False,
            "message": "Direct project creation not supported via IPC",
            "suggestion": "Open KiCAD and create a new project, or use SWIG backend",
        }

    def open_project(self, path: Path) -> Dict[str, Any]:
        """Open existing project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            # Check for open documents
            documents = self._kicad.get_open_documents()

            # Look for matching project
            path_str = str(path)
            for doc in documents:
                if path_str in str(doc):
                    return {
                        "success": True,
                        "message": f"Project already open: {path}",
                        "path": str(path),
                    }

            return {
                "success": False,
                "message": "Project not currently open in KiCAD",
                "suggestion": "Open the project in KiCAD first, then connect via IPC",
            }

        except Exception as e:
            logger.error(f"Failed to check project: {e}")
            return {"success": False, "message": "Failed to check project", "errorDetails": str(e)}

    def save_project(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Save current project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            board = self._kicad.get_board()
            if path:
                board.save_as(str(path))
            else:
                board.save()

            self._notify_change("save", {"path": str(path) if path else "current"})

            return {"success": True, "message": "Project saved successfully"}
        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            return {"success": False, "message": "Failed to save project", "errorDetails": str(e)}

    def close_project(self) -> None:
        """Close current project (not supported via IPC)."""
        logger.warning("Closing projects via IPC is not supported")

    # Board Operations
    def get_board(self) -> BoardAPI:
        """Get board API for real-time manipulation."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        return IPCBoardAPI(self._kicad, self._notify_change)


class IPCBoardAPI(BoardAPI):
    """
    Board API implementation for IPC backend.

    All changes made through this API appear immediately in the KiCAD UI.
    Uses transactions for proper undo/redo support.
    """

    def __init__(self, kicad_instance: Any, notify_callback: Callable) -> None:
        self._kicad = kicad_instance
        self._board = None
        self._notify = notify_callback
        self._current_commit = None

    def _get_board(self) -> Any:
        """Get board instance, connecting if needed."""
        if self._board is None:
            try:
                self._board = self._kicad.get_board()
            except Exception as e:
                logger.error(f"Failed to get board: {e}")
                raise ConnectionError(f"No board open in KiCAD: {e}")
        return self._board

    def begin_transaction(self, description: str = "MCP Operation") -> None:
        """Begin a transaction for grouping operations into a single undo step."""
        board = self._get_board()
        self._current_commit = board.begin_commit()
        logger.debug(f"Started transaction: {description}")

    def commit_transaction(self, description: str = "MCP Operation") -> None:
        """Commit the current transaction."""
        if self._current_commit:
            board = self._get_board()
            board.push_commit(self._current_commit, description)
            self._current_commit = None
            logger.debug(f"Committed transaction: {description}")

    def rollback_transaction(self) -> None:
        """Roll back the current transaction."""
        if self._current_commit:
            board = self._get_board()
            board.drop_commit(self._current_commit)
            self._current_commit = None
            logger.debug("Rolled back transaction")

    def save(self) -> bool:
        """Save the board immediately."""
        try:
            board = self._get_board()
            board.save()
            self._notify("save", {})
            return True
        except Exception as e:
            logger.error(f"Failed to save board: {e}")
            return False

    def set_size(self, width: float, height: float, unit: str = "mm") -> bool:
        """
        Set board size.

        Note: Board size in KiCAD is typically defined by the board outline,
        not a direct size property. This method may need to create/modify
        the board outline.
        """
        try:
            from kipy.board_types import BoardRectangle
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self._get_board()

            # Convert to nm
            if unit == "mm":
                w = from_mm(width)
                h = from_mm(height)
            else:
                w = int(width * INCH_TO_NM)
                h = int(height * INCH_TO_NM)

            # Create board outline rectangle on Edge.Cuts layer
            rect = BoardRectangle()
            rect.start = Vector2.from_xy(0, 0)
            rect.end = Vector2.from_xy(w, h)
            rect.layer = BoardLayer.BL_Edge_Cuts
            rect.width = from_mm(0.1)  # Standard edge cut width

            # Begin transaction for undo support
            commit = board.begin_commit()
            board.create_items(rect)
            board.push_commit(commit, f"Set board size to {width}x{height} {unit}")

            self._notify("board_size", {"width": width, "height": height, "unit": unit})

            return True

        except Exception as e:
            logger.error(f"Failed to set board size: {e}")
            return False

    def get_size(self) -> Dict[str, Any]:
        """Get current board size from bounding box."""
        try:
            board = self._get_board()

            # Get shapes on Edge.Cuts layer to determine board size
            shapes = board.get_shapes()

            if not shapes:
                return {"width": 0, "height": 0, "unit": "mm"}

            # Find bounding box of edge cuts
            from kipy.util.units import to_mm

            min_x = min_y = float("inf")
            max_x = max_y = float("-inf")

            for shape in shapes:
                # Check if on Edge.Cuts layer
                bbox = board.get_item_bounding_box(shape)
                if bbox:
                    left, top, right, bottom = self._get_box2_extents(bbox)
                    min_x = min(min_x, left)
                    min_y = min(min_y, top)
                    max_x = max(max_x, right)
                    max_y = max(max_y, bottom)

            if min_x == float("inf"):
                return {"width": 0, "height": 0, "unit": "mm"}

            return {"width": to_mm(max_x - min_x), "height": to_mm(max_y - min_y), "unit": "mm"}

        except Exception as e:
            logger.error(f"Failed to get board size: {e}")
            return {"width": 0, "height": 0, "unit": "mm", "error": str(e)}

    @staticmethod
    def _get_box2_extents(bbox: Any) -> tuple[float, float, float, float]:
        """Return left/top/right/bottom for kipy Box2 wrappers across versions."""
        if hasattr(bbox, "min") and hasattr(bbox, "max"):
            return bbox.min.x, bbox.min.y, bbox.max.x, bbox.max.y

        if hasattr(bbox, "pos") and hasattr(bbox, "size"):
            x1 = bbox.pos.x
            y1 = bbox.pos.y
            x2 = x1 + bbox.size.x
            y2 = y1 + bbox.size.y
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

        raise AttributeError("Unsupported Box2 shape: expected min/max or pos/size")

    def add_layer(self, layer_name: str, layer_type: str) -> bool:
        """Add layer to the board (layers are typically predefined in KiCAD)."""
        logger.warning("Layer management via IPC is limited - layers are predefined")
        return False

    def get_enabled_layers(self) -> List[str]:
        """Get list of enabled layers."""
        try:
            board = self._get_board()
            layers = board.get_enabled_layers()
            return [str(layer) for layer in layers]
        except Exception as e:
            logger.error(f"Failed to get enabled layers: {e}")
            return []

    def list_components(self) -> List[Dict[str, Any]]:
        """List all components (footprints) on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            footprints = board.get_footprints()

            components = []
            for fp in footprints:
                try:
                    pos = fp.position

                    # Try to get bounding box
                    bbox_data = None
                    try:
                        bbox = board.get_item_bounding_box(fp)
                        if bbox:
                            bbox_data = {
                                "min_x": to_mm(bbox.min.x),
                                "min_y": to_mm(bbox.min.y),
                                "max_x": to_mm(bbox.max.x),
                                "max_y": to_mm(bbox.max.y),
                                "width": to_mm(bbox.max.x - bbox.min.x),
                                "height": to_mm(bbox.max.y - bbox.min.y),
                                "unit": "mm",
                            }
                    except Exception:
                        pass  # Bounding box may not be available via IPC

                    # Fallback: compute bounding box from pad positions + sizes
                    if not bbox_data:
                        try:
                            pads = fp.pads if hasattr(fp, "pads") else []
                            pad_list = list(pads)
                            if pad_list:
                                min_x = float("inf")
                                min_y = float("inf")
                                max_x = float("-inf")
                                max_y = float("-inf")
                                for pad in pad_list:
                                    px = to_mm(pad.position.x) if pad.position else 0
                                    py = to_mm(pad.position.y) if pad.position else 0
                                    pw = (
                                        to_mm(pad.size.x) / 2
                                        if hasattr(pad, "size") and pad.size
                                        else 0.5
                                    )
                                    ph = (
                                        to_mm(pad.size.y) / 2
                                        if hasattr(pad, "size") and pad.size
                                        else 0.5
                                    )
                                    min_x = min(min_x, px - pw)
                                    min_y = min(min_y, py - ph)
                                    max_x = max(max_x, px + pw)
                                    max_y = max(max_y, py + ph)
                                margin = 0.25  # mm — small margin for component body beyond pads
                                bbox_data = {
                                    "min_x": min_x - margin,
                                    "min_y": min_y - margin,
                                    "max_x": max_x + margin,
                                    "max_y": max_y + margin,
                                    "width": (max_x - min_x) + 2 * margin,
                                    "height": (max_y - min_y) + 2 * margin,
                                    "unit": "mm",
                                }
                        except Exception as e:
                            logger.debug(f"Could not compute bbox from pads: {e}")

                    components.append(
                        {
                            "reference": (
                                fp.reference_field.text.value if fp.reference_field else ""
                            ),
                            "value": fp.value_field.text.value if fp.value_field else "",
                            "footprint": (
                                str(fp.definition.library_link)
                                if fp.definition and hasattr(fp.definition, "library_link")
                                else (
                                    str(fp.definition.id)
                                    if fp.definition and hasattr(fp.definition, "id")
                                    else ""
                                )
                            ),
                            "position": {
                                "x": to_mm(pos.x) if pos else 0,
                                "y": to_mm(pos.y) if pos else 0,
                                "unit": "mm",
                            },
                            "rotation": fp.orientation.degrees if fp.orientation else 0,
                            "layer": str(fp.layer) if hasattr(fp, "layer") else "F.Cu",
                            "id": str(fp.id) if hasattr(fp, "id") else "",
                            "boundingBox": bbox_data,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing footprint: {e}")
                    continue

            return components

        except Exception as e:
            logger.error(f"Failed to list components: {e}")
            return []

    def place_component(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float = 0,
        layer: str = "F.Cu",
        value: str = "",
    ) -> bool:
        """
        Place a component on the board.

        The component appears immediately in the KiCAD UI.

        This method uses a hybrid approach:
        1. Load the footprint definition from the library using pcbnew (SWIG)
        2. Place it on the board via IPC for real-time UI updates

        Args:
            reference: Component reference designator (e.g., "R1", "U1")
            footprint: Footprint path in format "Library:FootprintName" or just "FootprintName"
            x: X position in mm
            y: Y position in mm
            rotation: Rotation angle in degrees
            layer: Layer name ("F.Cu" for top, "B.Cu" for bottom)
            value: Component value (optional)
        """
        try:
            # First, try to load the footprint from library using pcbnew SWIG
            loaded_fp = self._load_footprint_from_library(footprint)

            if loaded_fp:
                # We have the footprint from the library - place it via SWIG
                # then sync to IPC for UI update
                return self._place_loaded_footprint(
                    loaded_fp, reference, x, y, rotation, layer, value
                )
            else:
                # Fallback: Create a basic placeholder footprint via IPC
                logger.warning(
                    f"Could not load footprint '{footprint}' from library, creating placeholder"
                )
                return self._place_placeholder_footprint(
                    reference, footprint, x, y, rotation, layer, value
                )

        except Exception as e:
            logger.error(f"Failed to place component: {e}")
            return False

    def _load_footprint_from_library(self, footprint_path: str) -> Any:
        """
        Load a footprint from the library using pcbnew SWIG API.

        Args:
            footprint_path: Either "Library:FootprintName" or just "FootprintName"

        Returns:
            pcbnew.FOOTPRINT object or None if not found
        """
        try:
            import pcbnew

            # Parse library and footprint name
            if ":" in footprint_path:
                lib_name, fp_name = footprint_path.split(":", 1)
            else:
                # Try to find the footprint in all libraries
                lib_name = None
                fp_name = footprint_path

            # Get the footprint library table
            fp_lib_table = pcbnew.GetGlobalFootprintLib()

            if lib_name:
                # Load from specific library
                try:
                    loaded_fp = pcbnew.FootprintLoad(fp_lib_table, lib_name, fp_name)
                    if loaded_fp:
                        logger.info(f"Loaded footprint '{fp_name}' from library '{lib_name}'")
                        return loaded_fp
                except Exception as e:
                    logger.warning(f"Could not load from {lib_name}: {e}")
            else:
                # Search all libraries for the footprint
                lib_names = fp_lib_table.GetLogicalLibs()
                for lib in lib_names:
                    try:
                        loaded_fp = pcbnew.FootprintLoad(fp_lib_table, lib, fp_name)
                        if loaded_fp:
                            logger.info(f"Found footprint '{fp_name}' in library '{lib}'")
                            return loaded_fp
                    except:
                        continue

            logger.warning(f"Footprint '{footprint_path}' not found in any library")
            return None

        except ImportError:
            logger.warning("pcbnew not available - cannot load footprints from library")
            return None
        except Exception as e:
            logger.error(f"Error loading footprint from library: {e}")
            return None

    def _place_loaded_footprint(
        self,
        loaded_fp: Any,
        reference: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str,
    ) -> bool:
        """
        Place a loaded pcbnew footprint onto the board.

        Uses SWIG to add the footprint, then notifies for IPC sync.
        """
        try:
            import pcbnew

            # Get the board file path from IPC to load via pcbnew
            board = self._get_board()

            # Get the pcbnew board instance
            # We need to get the actual board file path
            project = board.get_project()
            board_path = None

            # Try to get the board path from kipy
            try:
                docs = self._kicad.get_open_documents()
                for doc in docs:
                    if hasattr(doc, "path") and str(doc.path).endswith(".kicad_pcb"):
                        board_path = str(doc.path)
                        break
            except Exception as e:
                logger.debug(f"Could not get board path from IPC: {e}")

            if board_path and os.path.exists(board_path):
                # Load board via pcbnew
                pcb_board = pcbnew.LoadBoard(board_path)
            else:
                # Try to get from pcbnew directly
                pcb_board = pcbnew.GetBoard()

            if not pcb_board:
                logger.error("Could not get pcbnew board instance")
                return self._place_placeholder_footprint(
                    reference, "", x, y, rotation, layer, value
                )

            # Set footprint position and properties
            scale = MM_TO_NM
            loaded_fp.SetPosition(pcbnew.VECTOR2I(int(x * scale), int(y * scale)))
            loaded_fp.SetOrientationDegrees(rotation)

            # Set reference
            loaded_fp.SetReference(reference)

            # Set value if provided
            if value:
                loaded_fp.SetValue(value)

            # Set layer (flip if bottom)
            if layer == "B.Cu":
                if not loaded_fp.IsFlipped():
                    loaded_fp.Flip(loaded_fp.GetPosition(), False)

            # Add to board
            pcb_board.Add(loaded_fp)

            # Save the board so IPC can see the changes
            pcbnew.SaveBoard(board_path, pcb_board)

            # Refresh IPC view
            try:
                board.revert()  # Reload from disk to sync IPC
            except Exception as e:
                logger.debug(f"Could not refresh IPC board: {e}")

            self._notify(
                "component_placed",
                {
                    "reference": reference,
                    "footprint": loaded_fp.GetFPIDAsString(),
                    "position": {"x": x, "y": y},
                    "rotation": rotation,
                    "layer": layer,
                    "loaded_from_library": True,
                },
            )

            logger.info(
                f"Placed component {reference} ({loaded_fp.GetFPIDAsString()}) at ({x}, {y}) mm"
            )
            return True

        except Exception as e:
            logger.error(f"Error placing loaded footprint: {e}")
            # Fall back to placeholder
            return self._place_placeholder_footprint(reference, "", x, y, rotation, layer, value)

    def _place_placeholder_footprint(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str,
    ) -> bool:
        """
        Place a placeholder footprint when library loading fails.

        Creates a basic footprint via IPC with just reference/value fields.
        """
        try:
            from kipy.board_types import Footprint
            from kipy.geometry import Angle, Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create footprint
            fp = Footprint()
            fp.position = Vector2.from_xy(from_mm(x), from_mm(y))
            fp.orientation = Angle.from_degrees(rotation)

            # Set layer
            if layer == "B.Cu":
                fp.layer = BoardLayer.BL_B_Cu
            else:
                fp.layer = BoardLayer.BL_F_Cu

            # Set reference and value
            if fp.reference_field:
                fp.reference_field.text.value = reference
            if fp.value_field:
                fp.value_field.text.value = value if value else footprint

            # Begin transaction
            commit = board.begin_commit()
            board.create_items(fp)
            board.push_commit(commit, f"Placed component {reference}")

            self._notify(
                "component_placed",
                {
                    "reference": reference,
                    "footprint": footprint,
                    "position": {"x": x, "y": y},
                    "rotation": rotation,
                    "layer": layer,
                    "loaded_from_library": False,
                    "is_placeholder": True,
                },
            )

            logger.info(f"Placed placeholder component {reference} at ({x}, {y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to place placeholder component: {e}")
            return False

    def move_component(
        self, reference: str, x: float, y: float, rotation: Optional[float] = None
    ) -> bool:
        """Move a component to a new position (updates UI immediately)."""
        try:
            from kipy.geometry import Angle, Vector2
            from kipy.util.units import from_mm

            board = self._get_board()
            footprints = board.get_footprints()

            # Find the footprint by reference
            target_fp = None
            for fp in footprints:
                if fp.reference_field and fp.reference_field.text.value == reference:
                    target_fp = fp
                    break

            if not target_fp:
                logger.error(f"Component not found: {reference}")
                return False

            # Update position
            target_fp.position = Vector2.from_xy(from_mm(x), from_mm(y))

            if rotation is not None:
                target_fp.orientation = Angle.from_degrees(rotation)

            # Apply changes
            commit = board.begin_commit()
            board.update_items([target_fp])
            board.push_commit(commit, f"Moved component {reference}")

            self._notify(
                "component_moved",
                {"reference": reference, "position": {"x": x, "y": y}, "rotation": rotation},
            )

            return True

        except Exception as e:
            logger.error(f"Failed to move component: {e}")
            return False

    def delete_component(self, reference: str) -> bool:
        """Delete a component from the board."""
        try:
            board = self._get_board()
            footprints = board.get_footprints()

            # Find the footprint by reference
            target_fp = None
            for fp in footprints:
                if fp.reference_field and fp.reference_field.text.value == reference:
                    target_fp = fp
                    break

            if not target_fp:
                logger.error(f"Component not found: {reference}")
                return False

            # Remove component
            commit = board.begin_commit()
            board.remove_items([target_fp])
            board.push_commit(commit, f"Deleted component {reference}")

            self._notify("component_deleted", {"reference": reference})

            return True

        except Exception as e:
            logger.error(f"Failed to delete component: {e}")
            return False

    def add_track(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        width: float = 0.25,
        layer: str = "F.Cu",
        net_name: Optional[str] = None,
    ) -> bool:
        """
        Add a track (trace) to the board.

        The track appears immediately in the KiCAD UI.
        """
        try:
            from kipy.board_types import Track
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create track
            track = Track()
            track.start = Vector2.from_xy(from_mm(start_x), from_mm(start_y))
            track.end = Vector2.from_xy(from_mm(end_x), from_mm(end_y))
            track.width = from_mm(width)

            # Set layer
            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
            }
            track.layer = layer_map.get(layer, BoardLayer.BL_F_Cu)

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        track.net = net
                        break

            # Add track with transaction
            commit = board.begin_commit()
            board.create_items(track)
            board.push_commit(commit, "Added track")

            self._notify(
                "track_added",
                {
                    "start": {"x": start_x, "y": start_y},
                    "end": {"x": end_x, "y": end_y},
                    "width": width,
                    "layer": layer,
                    "net": net_name,
                },
            )

            logger.info(f"Added track from ({start_x}, {start_y}) to ({end_x}, {end_y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to add track: {e}")
            return False

    def add_arc_track(
        self,
        start_x: float,
        start_y: float,
        mid_x: float,
        mid_y: float,
        end_x: float,
        end_y: float,
        width: float = 0.25,
        layer: str = "F.Cu",
        net_name: Optional[str] = None,
    ) -> bool:
        """Add a copper arc track to the board."""
        try:
            from kipy.board_types import ArcTrack
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self._get_board()

            arc = ArcTrack()
            arc.start = Vector2.from_xy(from_mm(start_x), from_mm(start_y))
            arc.mid = Vector2.from_xy(from_mm(mid_x), from_mm(mid_y))
            arc.end = Vector2.from_xy(from_mm(end_x), from_mm(end_y))
            arc.width = from_mm(width)

            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
            }
            arc.layer = layer_map.get(layer, BoardLayer.BL_F_Cu)

            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        arc.net = net
                        break

            commit = board.begin_commit()
            board.create_items(arc)
            board.push_commit(commit, "Added arc track")

            self._notify(
                "arc_track_added",
                {
                    "start": {"x": start_x, "y": start_y},
                    "mid": {"x": mid_x, "y": mid_y},
                    "end": {"x": end_x, "y": end_y},
                    "width": width,
                    "layer": layer,
                    "net": net_name,
                },
            )
            logger.info(
                f"Added arc track start=({start_x}, {start_y}) mid=({mid_x}, {mid_y}) end=({end_x}, {end_y}) mm"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add arc track: {e}")
            return False

    def add_via(
        self,
        x: float,
        y: float,
        diameter: float = 0.8,
        drill: float = 0.4,
        net_name: Optional[str] = None,
        via_type: str = "through",
    ) -> bool:
        """
        Add a via to the board.

        The via appears immediately in the KiCAD UI.
        """
        try:
            from kipy.board_types import Via
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import ViaType
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create via
            via = Via()
            via.position = Vector2.from_xy(from_mm(x), from_mm(y))
            via.diameter = from_mm(diameter)
            via.drill_diameter = from_mm(drill)

            # Set via type (enum values: VT_THROUGH=1, VT_BLIND_BURIED=2, VT_MICRO=3)
            type_map = {
                "through": ViaType.VT_THROUGH,
                "blind": ViaType.VT_BLIND_BURIED,
                "micro": ViaType.VT_MICRO,
            }
            via.type = type_map.get(via_type, ViaType.VT_THROUGH)

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        via.net = net
                        break

            # Add via with transaction
            commit = board.begin_commit()
            board.create_items(via)
            board.push_commit(commit, "Added via")

            self._notify(
                "via_added",
                {
                    "position": {"x": x, "y": y},
                    "diameter": diameter,
                    "drill": drill,
                    "net": net_name,
                    "type": via_type,
                },
            )

            logger.info(f"Added via at ({x}, {y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to add via: {e}")
            return False

    def add_text(
        self,
        text: str,
        x: float,
        y: float,
        layer: str = "F.SilkS",
        size: float = 1.0,
        rotation: float = 0,
    ) -> bool:
        """Add text to the board."""
        try:
            from kipy.board_types import BoardText
            from kipy.geometry import Angle, Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create text
            board_text = BoardText()
            board_text.value = text
            board_text.position = Vector2.from_xy(from_mm(x), from_mm(y))
            board_text.angle = Angle.from_degrees(rotation)

            # Set layer
            layer_map = {
                "F.SilkS": BoardLayer.BL_F_SilkS,
                "B.SilkS": BoardLayer.BL_B_SilkS,
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
            }
            board_text.layer = layer_map.get(layer, BoardLayer.BL_F_SilkS)

            # Add text with transaction
            commit = board.begin_commit()
            board.create_items(board_text)
            board.push_commit(commit, f"Added text: {text}")

            self._notify("text_added", {"text": text, "position": {"x": x, "y": y}, "layer": layer})

            return True

        except Exception as e:
            logger.error(f"Failed to add text: {e}")
            return False

    def delete_traces(self, net: Optional[str] = None, include_vias: bool = True) -> int:
        """Remove tracks (and optionally vias) from the live board via kipy.

        net: net name to match; "*" or None matches ALL. include_vias: also remove vias.
        Returns the number of items removed, or -1 on error. Single transaction (no
        per-item dehydration), operates on the live KiCAD board.
        """
        try:
            board = self._get_board()
            want_all = (net is None) or (net == "*")
            victims = []
            for t in board.get_tracks():
                if want_all or (t.net.name if getattr(t, "net", None) else "") == net:
                    victims.append(t)
            if include_vias:
                for v in board.get_vias():
                    if want_all or (v.net.name if getattr(v, "net", None) else "") == net:
                        victims.append(v)
            if victims:
                board.remove_items(victims)
                self._notify("traces_deleted", {"count": len(victims), "net": net})
                logger.info(f"Deleted {len(victims)} tracks/vias (net={net!r})")
            return len(victims)
        except Exception as e:
            logger.error(f"Failed to delete traces: {e}")
            return -1

    def save_live_board(self) -> bool:
        """Save the live (GUI) board document to disk via the IPC API."""
        try:
            self._get_board().save()
            return True
        except Exception as e:
            logger.error(f"save_live_board failed: {e}")
            return False

    def revert_live_board(self) -> bool:
        """Reload the live (GUI) board from disk — discards any unsaved GUI edits
        and makes the open editor reflect the current file contents."""
        try:
            self._get_board().revert()
            return True
        except Exception as e:
            logger.error(f"revert_live_board failed: {e}")
            return False

    def get_board_filename(self) -> Optional[str]:
        """Return the file path of the live board, or None."""
        try:
            return self._get_board().name
        except Exception as e:
            logger.warning(f"get_board_filename failed: {e}")
            return None

    # Friendly grid action -> KiCad run_action identifier. The IPC API exposes no
    # way to set an exact grid size, so the editor's grid list is stepped through
    # (gridNext/gridPrev) or the two user-configurable "fast" grids are selected.
    _GRID_ACTIONS = {
        "finer": "common.Control.gridNext",
        "coarser": "common.Control.gridPrev",
        "fast1": "common.Control.gridFast1",
        "fast2": "common.Control.gridFast2",
        "cycle": "common.Control.gridFastCycle",
    }

    def set_grid(self, action: str) -> Dict[str, Any]:
        """Change the active editor grid by firing a KiCad GUI action.

        Returns {"ok": bool, "status": int|None, "action_id": str|None}. KiCad's
        RunActionStatus uses 1 == RAS_OK; anything else means the action was not
        accepted (e.g. no editor frame open).
        """
        action_id = self._GRID_ACTIONS.get(action)
        if action_id is None:
            return {"ok": False, "error": f"unknown grid action '{action}'", "action_id": None}
        try:
            response = self._kicad.run_action(action_id)
            status = getattr(response, "status", None)
            status = int(status) if status is not None else None
            return {"ok": status == 1, "status": status, "action_id": action_id}
        except Exception as e:
            logger.error(f"set_grid({action}) failed: {e}")
            return {"ok": False, "error": str(e), "action_id": action_id}

    def get_tracks(self) -> List[Dict[str, Any]]:
        """Get all tracks on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            tracks = board.get_tracks()

            result = []
            for track in tracks:
                try:
                    result.append(
                        {
                            "start": {"x": to_mm(track.start.x), "y": to_mm(track.start.y)},
                            "end": {"x": to_mm(track.end.x), "y": to_mm(track.end.y)},
                            "width": to_mm(track.width),
                            "layer": str(track.layer),
                            "net": track.net.name if track.net else "",
                            "id": str(track.id) if hasattr(track, "id") else "",
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing track: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get tracks: {e}")
            return []

    def get_vias(self) -> List[Dict[str, Any]]:
        """Get all vias on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            vias = board.get_vias()

            result = []
            for via in vias:
                try:
                    result.append(
                        {
                            "position": {"x": to_mm(via.position.x), "y": to_mm(via.position.y)},
                            "diameter": to_mm(via.diameter),
                            "drill": to_mm(via.drill_diameter),
                            "net": via.net.name if via.net else "",
                            "type": str(via.type),
                            "id": str(via.id) if hasattr(via, "id") else "",
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing via: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get vias: {e}")
            return []

    def get_nets(self) -> List[Dict[str, Any]]:
        """Get all nets on the board."""
        try:
            board = self._get_board()
            nets = board.get_nets()

            result = []
            for net in nets:
                try:
                    result.append(
                        {"name": net.name, "code": net.code if hasattr(net, "code") else 0}
                    )
                except Exception as e:
                    logger.warning(f"Error processing net: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get nets: {e}")
            return []

    def add_zone(
        self,
        points: List[Dict[str, float]],
        layer: str = "F.Cu",
        net_name: Optional[str] = None,
        clearance: float = 0.5,
        min_thickness: float = 0.25,
        priority: int = 0,
        fill_mode: str = "solid",
        name: str = "",
    ) -> bool:
        """
        Add a copper pour zone to the board.

        The zone appears immediately in the KiCAD UI.

        Args:
            points: List of points defining the zone outline, e.g. [{"x": 0, "y": 0}, ...]
            layer: Layer name (F.Cu, B.Cu, etc.)
            net_name: Net to connect the zone to (e.g., "GND")
            clearance: Clearance from other copper in mm
            min_thickness: Minimum copper thickness in mm
            priority: Zone priority (higher = fills first)
            fill_mode: "solid" or "hatched"
            name: Optional zone name
        """
        try:
            from kipy.board_types import Zone, ZoneFillMode, ZoneType
            from kipy.geometry import PolyLine, PolyLineNode, Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self._get_board()

            if len(points) < 3:
                logger.error("Zone requires at least 3 points")
                return False

            # Create zone
            zone = Zone()
            zone.type = ZoneType.ZT_COPPER

            # Set layer
            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
                "In3.Cu": BoardLayer.BL_In3_Cu,
                "In4.Cu": BoardLayer.BL_In4_Cu,
            }
            zone.layers = [layer_map.get(layer, BoardLayer.BL_F_Cu)]

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        zone.net = net
                        break

            # Set zone properties
            zone.clearance = from_mm(clearance)
            zone.min_thickness = from_mm(min_thickness)
            zone.priority = priority

            if name:
                zone.name = name

            # Set fill mode. Some kipy builds expose Zone.fill_mode as a read-only
            # property (no setter) → attempting to assign raises AttributeError and
            # aborts the whole zone creation. Try the property, fall back to the proto
            # field, and finally just keep KiCad's default (solid) if neither works.
            try:
                mode = ZoneFillMode.ZFM_HATCHED if fill_mode == "hatched" else ZoneFillMode.ZFM_SOLID
                try:
                    zone.fill_mode = mode
                except AttributeError:
                    try:
                        zone._proto.fill_mode = int(mode)
                    except Exception:
                        logger.warning(
                            "kipy Zone.fill_mode is not settable; using default solid fill"
                        )
            except Exception:
                logger.warning("Could not resolve fill mode; using default solid fill")

            # Create outline polyline
            outline = PolyLine()
            outline.closed = True

            for point in points:
                x = point.get("x", 0)
                y = point.get("y", 0)
                node = PolyLineNode.from_xy(from_mm(x), from_mm(y))
                outline.append(node)

            # Set the outline on the zone
            # Note: Zone outline is set via the proto directly since kipy
            # doesn't expose a direct setter for creating new zones
            zone._proto.outline.polygons.add()
            zone._proto.outline.polygons[0].outline.CopyFrom(outline._proto)

            # Add zone with transaction
            commit = board.begin_commit()
            board.create_items(zone)
            board.push_commit(commit, f"Added copper zone on {layer}")

            self._notify(
                "zone_added",
                {"layer": layer, "net": net_name, "points": len(points), "priority": priority},
            )

            logger.info(f"Added zone on {layer} with {len(points)} points")
            return True

        except Exception as e:
            logger.error(f"Failed to add zone: {e}")
            return False

    def get_zones(self) -> List[Dict[str, Any]]:
        """Get all zones on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            zones = board.get_zones()

            result = []
            for zone in zones:
                try:
                    result.append(
                        {
                            "name": zone.name if hasattr(zone, "name") else "",
                            "net": zone.net.name if zone.net else "",
                            "priority": zone.priority if hasattr(zone, "priority") else 0,
                            "layers": (
                                [str(l) for l in zone.layers] if hasattr(zone, "layers") else []
                            ),
                            "filled": zone.filled if hasattr(zone, "filled") else False,
                            "id": str(zone.id) if hasattr(zone, "id") else "",
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing zone: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get zones: {e}")
            return []

    def delete_zones(
        self,
        layer: Optional[str] = None,
        net_name: Optional[str] = None,
        copper_only: bool = True,
    ) -> int:
        """Remove board zones matching the given filters.

        Args:
            layer: restrict to this copper layer name (e.g. "In2.Cu"); None = any.
            net_name: restrict to zones whose net equals this exactly. Pass "" to match
                      netless (no-net) zones. None = any net.
            copper_only: when True, never touch rule-area / keepout zones (so antenna
                         keepouts are safe).

        Returns the number of zones removed, or -1 on error.
        """
        try:
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.board_types import ZoneType

            board = self._get_board()
            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
                "In3.Cu": BoardLayer.BL_In3_Cu,
                "In4.Cu": BoardLayer.BL_In4_Cu,
            }
            want_layer = layer_map.get(layer) if layer else None

            victims = []
            for zone in board.get_zones():
                # Never delete rule areas / keepouts when copper_only is set.
                if copper_only and hasattr(zone, "type") and zone.type != ZoneType.ZT_COPPER:
                    continue
                znet = zone.net.name if getattr(zone, "net", None) else ""
                if net_name is not None and znet != net_name:
                    continue
                if want_layer is not None:
                    zlayers = list(zone.layers) if hasattr(zone, "layers") else []
                    if want_layer not in zlayers:
                        continue
                victims.append(zone)

            if victims:
                board.remove_items(victims)
                self._notify("zones_deleted", {"count": len(victims), "layer": layer, "net": net_name})
                logger.info(f"Deleted {len(victims)} zone(s) layer={layer} net={net_name!r}")
            return len(victims)
        except Exception as e:
            logger.error(f"Failed to delete zones: {e}")
            return -1

    def refill_zones(self) -> bool:
        """Refill all copper pour zones."""
        try:
            board = self._get_board()
            board.refill_zones()
            self._notify("zones_refilled", {})
            return True
        except Exception as e:
            logger.error(f"Failed to refill zones: {e}")
            return False

    def get_selection(self) -> List[Dict[str, Any]]:
        """Get currently selected items in the KiCAD UI."""
        try:
            board = self._get_board()
            selection = board.get_selection()

            result = []
            for item in selection:
                result.append(
                    {"type": type(item).__name__, "id": str(item.id) if hasattr(item, "id") else ""}
                )

            return result
        except Exception as e:
            logger.error(f"Failed to get selection: {e}")
            return []

    def clear_selection(self) -> bool:
        """Clear the current selection in KiCAD UI."""
        try:
            board = self._get_board()
            board.clear_selection()
            return True
        except Exception as e:
            logger.error(f"Failed to clear selection: {e}")
            return False


# Export for factory
__all__ = ["IPCBackend", "IPCBoardAPI"]
