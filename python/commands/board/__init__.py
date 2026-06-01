"""
Board-related command implementations for KiCAD interface
"""

import logging
from typing import Any, Dict, Optional

import pcbnew

from .layers import BoardLayerCommands
from .outline import BoardOutlineCommands

# Import specialized modules
from .size import BoardSizeCommands
from .view import BoardViewCommands
from .visibility import BoardVisibilityCommands

logger = logging.getLogger("kicad_interface")


class BoardCommands:
    """Handles board-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

        # Initialize specialized command classes
        self.size_commands = BoardSizeCommands(board)
        self.layer_commands = BoardLayerCommands(board)
        self.outline_commands = BoardOutlineCommands(board)
        self.view_commands = BoardViewCommands(board)
        self.visibility_commands = BoardVisibilityCommands(board)

    # Delegate board size commands
    def set_board_size(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the size of the PCB board"""
        self.size_commands.board = self.board
        return self.size_commands.set_board_size(params)

    # Delegate layer commands
    def add_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new layer to the PCB"""
        self.layer_commands.board = self.board
        return self.layer_commands.add_layer(params)

    def set_active_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the active layer for PCB operations"""
        self.layer_commands.board = self.board
        return self.layer_commands.set_active_layer(params)

    def get_layer_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all layers in the PCB"""
        self.layer_commands.board = self.board
        return self.layer_commands.get_layer_list(params)

    # Delegate board outline commands
    def add_board_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a board outline to the PCB"""
        self.outline_commands.board = self.board
        return self.outline_commands.add_board_outline(params)

    def add_mounting_hole(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a mounting hole to the PCB"""
        self.outline_commands.board = self.board
        return self.outline_commands.add_mounting_hole(params)

    def add_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add text annotation to the PCB"""
        self.outline_commands.board = self.board
        return self.outline_commands.add_text(params)

    def add_board_cutout(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add an arbitrary polygon cutout to Edge.Cuts with optional copper keepout on all layers"""
        self.outline_commands.board = self.board
        return self.outline_commands.add_board_cutout(params)

    def delete_pcb_shape(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete the PCB drawing nearest to a given point (line/arc/polygon on any layer)"""
        self.outline_commands.board = self.board
        return self.outline_commands.delete_pcb_shape(params)

    # Delegate view commands
    def get_board_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current board"""
        self.view_commands.board = self.board
        return self.view_commands.get_board_info(params)

    def get_board_2d_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a 2D image of the PCB"""
        self.view_commands.board = self.board
        return self.view_commands.get_board_2d_view(params)

    def get_board_extents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get the bounding box extents of the board"""
        self.view_commands.board = self.board
        return self.view_commands.get_board_extents(params)

    # Delegate visibility commands
    def set_layer_visibility(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Show or hide named layers by writing a preset into .kicad_pro"""
        self.visibility_commands.board = self.board
        return self.visibility_commands.set_layer_visibility(params)

    def center_board_on_sheet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move all board content so Edge.Cuts bbox is centred on the paper sheet"""
        self.visibility_commands.board = self.board
        return self.visibility_commands.center_board_on_sheet(params)
