/**
 * Board management tools for KiCAD MCP server
 *
 * These tools handle board setup, layer management, and board properties
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register board management tools with the MCP server
 *
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerBoardTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info("Registering board management tools");

  // ------------------------------------------------------
  // Set Board Size Tool
  // ------------------------------------------------------
  server.tool(
    "set_board_size",
    "Set the PCB board dimensions (width and height) in the specified unit.",
    {
      width: z.number().describe("Board width"),
      height: z.number().describe("Board height"),
      unit: z.enum(["mm", "mil", "inch"]).describe("Unit of measurement"),
    },
    async ({ width, height, unit }) => {
      logger.debug(`Setting board size to ${width}x${height} ${unit}`);
      const result = await callKicadScript("set_board_size", {
        width,
        height,
        unit,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Layer Tool
  // ------------------------------------------------------
  server.tool(
    "add_layer",
    "Add a new copper or technical layer to the PCB stackup.",
    {
      name: z.string().describe("Layer name"),
      type: z.enum(["copper", "technical", "user", "signal"]).describe("Layer type"),
      position: z.enum(["top", "bottom", "inner"]).describe("Layer position"),
      number: z.number().optional().describe("Layer number (for inner layers)"),
    },
    async ({ name, type, position, number }) => {
      logger.debug(`Adding ${type} layer: ${name}`);
      const result = await callKicadScript("add_layer", {
        name,
        type,
        position,
        number,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Set Active Layer Tool
  // ------------------------------------------------------
  server.tool(
    "set_active_layer",
    "Set the currently active PCB layer by name (e.g. F.Cu, B.Cu).",
    {
      layer: z.string().describe("Layer name to set as active"),
    },
    async ({ layer }) => {
      logger.debug(`Setting active layer to: ${layer}`);
      const result = await callKicadScript("set_active_layer", { layer });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Board Info Tool
  // ------------------------------------------------------
  server.tool(
    "get_board_info",
    "Retrieve general information about the current PCB board (dimensions, layer count, DRC status).",
    {},
    async () => {
      logger.debug("Getting board information");
      const result = await callKicadScript("get_board_info", {});

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Layer List Tool
  // ------------------------------------------------------
  server.tool(
    "get_layer_list",
    "Return the list of all layers defined in the current PCB board.",
    {},
    async () => {
      logger.debug("Getting layer list");
      const result = await callKicadScript("get_layer_list", {});

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Board Outline Tool
  // ------------------------------------------------------
  server.tool(
    "add_board_outline",
    "Draw the PCB board outline (Edge.Cuts layer) as a rectangle, rounded rectangle, circle or polygon.",
    {
      shape: z
        .enum(["rectangle", "circle", "polygon", "rounded_rectangle"])
        .describe("Shape of the outline"),
      params: z
        .object({
          // For rectangle / rounded_rectangle
          width: z.number().optional().describe("Width of rectangle"),
          height: z.number().optional().describe("Height of rectangle"),
          cornerRadius: z.number().optional().describe("Corner radius for rounded_rectangle (mm)"),
          // For circle
          radius: z.number().optional().describe("Radius of circle"),
          // For polygon
          points: z
            .array(
              z.object({
                x: z.number().describe("X coordinate"),
                y: z.number().describe("Y coordinate"),
              }),
            )
            .optional()
            .describe("Points of polygon"),
          // Position: top-left corner for rectangles/rounded_rectangle, center for circle
          x: z.number().describe("X coordinate of top-left corner for rectangles (default: 0)"),
          y: z.number().describe("Y coordinate of top-left corner for rectangles (default: 0)"),
          unit: z.enum(["mm", "mil", "inch"]).describe("Unit of measurement"),
        })
        .describe("Parameters for the outline shape"),
    },
    async ({ shape, params }) => {
      logger.debug(`Adding ${shape} board outline`);
      // Pass x/y as-is to Python; outline.py treats them as top-left corner
      // and computes the center internally (center = x + width/2, y + height/2).
      const result = await callKicadScript("add_board_outline", {
        shape,
        ...params,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Mounting Hole Tool
  // ------------------------------------------------------
  server.tool(
    "add_mounting_hole",
    "Place a mounting hole (NPTH or PTH) at the specified position on the PCB.",
    {
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "mil", "inch"]).describe("Unit of measurement"),
        })
        .describe("Position of the mounting hole"),
      diameter: z.number().describe("Diameter of the hole"),
      padDiameter: z.number().optional().describe("Optional diameter of the pad around the hole"),
    },
    async ({ position, diameter, padDiameter }) => {
      logger.debug(`Adding mounting hole at (${position.x},${position.y}) ${position.unit}`);
      const result = await callKicadScript("add_mounting_hole", {
        position,
        diameter,
        padDiameter,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Text Tool
  // ------------------------------------------------------
  server.tool(
    "add_board_text",
    "Add a text label to a PCB layer (e.g. silkscreen, fab, courtyard).",
    {
      text: z.string().describe("Text content"),
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "mil", "inch"]).describe("Unit of measurement"),
        })
        .describe("Position of the text"),
      layer: z.string().describe("Layer to place the text on"),
      size: z.number().describe("Text size"),
      thickness: z.number().optional().describe("Line thickness"),
      rotation: z.number().optional().describe("Rotation angle in degrees"),
      style: z.enum(["normal", "italic", "bold"]).optional().describe("Text style"),
    },
    async ({ text, position, layer, size, thickness, rotation, style }) => {
      logger.debug(`Adding text "${text}" at (${position.x},${position.y}) ${position.unit}`);
      const result = await callKicadScript("add_board_text", {
        text,
        position,
        layer,
        size,
        thickness,
        rotation,
        style,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Zone Tool
  // ------------------------------------------------------
  server.tool(
    "add_zone",
    "Create a copper fill zone (pour) on a PCB layer for a specified net.",
    {
      layer: z.string().describe("Layer for the zone"),
      net: z.string().describe("Net name for the zone"),
      points: z
        .array(
          z.object({
            x: z.number().describe("X coordinate"),
            y: z.number().describe("Y coordinate"),
          }),
        )
        .describe("Points defining the zone outline"),
      unit: z.enum(["mm", "mil", "inch"]).describe("Unit of measurement"),
      clearance: z.number().optional().describe("Clearance value"),
      minWidth: z.number().optional().describe("Minimum width"),
      padConnection: z
        .enum(["thermal", "solid", "none"])
        .optional()
        .describe("Pad connection type"),
    },
    async ({ layer, net, points, unit, clearance, minWidth, padConnection }) => {
      logger.debug(`Adding zone on layer ${layer} for net ${net}`);
      const result = await callKicadScript("add_zone", {
        layer,
        net,
        points,
        unit,
        clearance,
        minWidth,
        padConnection,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Keepout (Rule Area) Zone Tool
  // ------------------------------------------------------
  server.tool(
    "add_keepout_zone",
    "Create a named rule-area (keepout) zone. Unlike add_zone (a filled copper pour), " +
      "this places a rule area with configurable doNotAllow flags. Default = a component-" +
      "placement keepout: footprints FORBIDDEN, tracks/vias/pads/copper-pour ALLOWED — e.g. " +
      "an antenna clearance boundary where no parts may intrude but GND stitching vias still can. " +
      "Multi-layer (defaults to all copper layers), not filled.",
    {
      points: z
        .array(z.object({ x: z.number(), y: z.number() }))
        .describe("Polygon outline points (>=3) of the keepout, in mm"),
      name: z.string().optional().describe("Zone name (e.g. 'antenna_keepout')"),
      layers: z
        .array(z.string())
        .optional()
        .describe("Copper layers (default: F.Cu, In1.Cu, In2.Cu, B.Cu)"),
      forbidFootprints: z.boolean().optional().describe("Forbid component footprints (default true)"),
      forbidTracks: z.boolean().optional().describe("Forbid tracks (default false)"),
      forbidVias: z.boolean().optional().describe("Forbid vias (default false — vias allowed)"),
      forbidPads: z.boolean().optional().describe("Forbid pads (default false)"),
      forbidCopperPour: z.boolean().optional().describe("Forbid copper pour fill (default false)"),
    },
    async (args: any) => {
      const result = await callKicadScript("add_keepout_zone", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Board Extents Tool
  // ------------------------------------------------------
  server.tool(
    "get_board_extents",
    "Return the bounding box (min/max X and Y) of all objects on the current PCB board.",
    {
      unit: z.enum(["mm", "mil", "inch"]).optional().describe("Unit of measurement for the result"),
    },
    async ({ unit }) => {
      logger.debug("Getting board extents");
      const result = await callKicadScript("get_board_extents", { unit });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Board 2D View Tool
  // ------------------------------------------------------
  server.tool(
    "get_board_2d_view",
    [
      "Render a 2D image of the PCB using kicad-cli. Returns PNG, JPG, or SVG.",
      "Use layers to filter — e.g. [\"F.Cu\",\"B.Cu\",\"Edge.Cuts\"] for copper + outline only.",
      "Use responseMode to choose delivery:",
      '  "inline" (default) — PNG/JPG rendered as an image visible to Claude; SVG returned as text.',
      '  "file" — image written next to the .kicad_pcb as <board>_2d_view.<ext>; filePath is returned.',
      "Use file mode for large boards to avoid MCP message-size limits.",
    ].join(" "),
    {
      pcbPath: z.string().optional().describe("Absolute path to the .kicad_pcb file. Falls back to the currently loaded board if omitted."),
      layers: z.array(z.string()).optional().describe("Layer names to include, e.g. [\"F.Cu\",\"B.Cu\",\"Edge.Cuts\"]. Omit for all layers."),
      width: z.number().optional().describe("Output image width in pixels (default: 1600)"),
      height: z.number().optional().describe("Output image height in pixels (default: 1200)"),
      format: z.enum(["png", "jpg", "svg"]).optional().describe("Output format (default: png)"),
      responseMode: z
        .enum(["inline", "file"])
        .optional()
        .describe(
          '"inline" (default): image returned directly; "file": written to disk, filePath returned',
        ),
    },
    async ({ pcbPath, layers, width, height, format, responseMode }) => {
      logger.debug("Getting 2D board view");
      const result = await callKicadScript("get_board_2d_view", {
        pcbPath,
        layers,
        width,
        height,
        format,
        responseMode,
      });

      if (result.success) {
        // file mode — just return the path as text
        if (responseMode === "file" || result.filePath) {
          return {
            content: [{ type: "text" as const, text: result.message || result.filePath }],
          };
        }
        // inline svg (or fallback svg) — return as text, prepend any notice
        if (result.format === "svg") {
          const parts: { type: "text"; text: string }[] = [];
          if (result.message) parts.push({ type: "text" as const, text: result.message });
          parts.push({ type: "text" as const, text: Buffer.from(result.imageData, "base64").toString("utf-8") });
          return { content: parts };
        }
        // inline png/jpg — return as renderable image
        return {
          content: [
            {
              type: "image" as const,
              data: result.imageData,
              mimeType: result.format === "jpg" ? "image/jpeg" : "image/png",
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to get board view: ${result.message || result.errorDetails || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  logger.info("Board management tools registered");

  // Import SVG logo onto PCB layer (silkscreen)
  server.tool(
    "import_svg_logo",
    "Imports an SVG file as filled graphic polygons onto a KiCAD PCB layer (default F.SilkS / front silkscreen). Curves are linearised automatically. Ideal for placing a company or project logo on the board.",
    {
      pcbPath: z.string().describe("Path to the .kicad_pcb file"),
      svgPath: z.string().describe("Path to the SVG logo file"),
      x: z.number().describe("X position of the logo top-left corner in mm"),
      y: z.number().describe("Y position of the logo top-left corner in mm"),
      width: z
        .number()
        .describe("Target width of the logo in mm (height is scaled to preserve aspect ratio)"),
      layer: z
        .string()
        .optional()
        .describe("PCB layer name, e.g. F.SilkS or B.SilkS (default: F.SilkS)"),
      strokeWidth: z
        .number()
        .optional()
        .describe("Outline stroke width in mm (0 = no outline, default 0)"),
      filled: z.boolean().optional().describe("Fill polygons with solid colour (default true)"),
    },
    async (args: {
      pcbPath: string;
      svgPath: string;
      x: number;
      y: number;
      width: number;
      layer?: string;
      strokeWidth?: number;
      filled?: boolean;
    }) => {
      const result = await callKicadScript("import_svg_logo", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: [
                result.message,
                `Polygons: ${result.polygon_count}`,
                `Size: ${result.logo_width_mm?.toFixed(2)} × ${result.logo_height_mm?.toFixed(2)} mm`,
                `Layer: ${result.layer}`,
              ].join("\n"),
            },
          ],
        };
      } else {
        return {
          content: [
            { type: "text", text: `SVG import failed: ${result.message || "Unknown error"}` },
          ],
        };
      }
    },
  );

  // ------------------------------------------------------
  // Set Layer Visibility Tool
  // ------------------------------------------------------
  server.tool(
    "set_layer_visibility",
    "Show or hide named PCB layers by writing a named preset into the .kicad_pro file. Reload the board in KiCad GUI to apply. Example: hide F.Courtyard and B.Courtyard to remove purple outlines.",
    {
      layers: z
        .array(z.string())
        .describe('Layer names to change, e.g. ["F.Courtyard", "B.Courtyard"]'),
      visible: z
        .boolean()
        .optional()
        .describe("true = show, false = hide (default: false)"),
      preset_name: z
        .string()
        .optional()
        .describe('Name for the layer preset entry (default: "custom")'),
    },
    async (args: { layers: string[]; visible?: boolean; preset_name?: string }) => {
      const result = await callKicadScript("set_layer_visibility", args);
      if (result.success) {
        return { content: [{ type: "text", text: result.message }] };
      } else {
        return { content: [{ type: "text", text: `set_layer_visibility failed: ${result.message}` }] };
      }
    },
  );

  // ------------------------------------------------------
  // Center Board on Sheet Tool
  // ------------------------------------------------------
  server.tool(
    "center_board_on_sheet",
    "Move all board content (footprints, tracks, zones, drawings) so the Edge.Cuts bounding box is centred on the current paper sheet. Fixes boards that appear off-sheet in the KiCad editor.",
    {
      sheet_width_mm: z
        .number()
        .optional()
        .describe("Override sheet width in mm (default: auto-detected from board paper settings)"),
      sheet_height_mm: z
        .number()
        .optional()
        .describe("Override sheet height in mm (default: auto-detected from board paper settings)"),
    },
    async (args: { sheet_width_mm?: number; sheet_height_mm?: number }) => {
      const result = await callKicadScript("center_board_on_sheet", args);
      if (result.success) {
        return { content: [{ type: "text", text: result.message }] };
      } else {
        return { content: [{ type: "text", text: `center_board_on_sheet failed: ${result.message}` }] };
      }
    },
  );

  // ------------------------------------------------------
  // Add Board Cutout Tool
  // ------------------------------------------------------
  server.tool(
    "add_board_cutout",
    "Add an arbitrary polygon cutout to Edge.Cuts (e.g. a triangular/trapezoidal slot at the board edge for an integrated PCB antenna). Optionally creates a copper keepout zone on all layers over the same polygon to prevent copper pour and traces from entering the cutout area.",
    {
      points: z
        .array(z.object({ x: z.number(), y: z.number() }))
        .min(3)
        .describe("Polygon vertices in order (mm), e.g. [{x:160,y:88},{x:154,y:88},{x:156.5,y:92},{x:159.5,y:92}]"),
      unit: z.string().optional().describe("Unit: 'mm' (default)"),
      keepout: z.boolean().optional().describe("Also add copper keepout on all layers (default: true)"),
      keepout_clearance: z.number().optional().describe("Extra clearance around keepout in mm (default 0.2)"),
    },
    async (args: { points: {x: number, y: number}[]; unit?: string; keepout?: boolean; keepout_clearance?: number }) => {
      const result = await callKicadScript("add_board_cutout", args);
      if (result.success) {
        return { content: [{ type: "text", text: result.message }] };
      } else {
        return { content: [{ type: "text", text: `add_board_cutout failed: ${result.message}` }] };
      }
    },
  );

  // ------------------------------------------------------
  // Delete PCB Shape Tool
  // ------------------------------------------------------
  server.tool(
    "delete_pcb_shape",
    "Delete the PCB drawing (line, arc, polygon, rect) nearest to a given point. Use to remove unwanted Edge.Cuts cutouts, silkscreen graphics, or other board drawings without opening KiCad GUI.",
    {
      x: z.number().describe("Search point X in mm"),
      y: z.number().describe("Search point Y in mm"),
      layer: z.string().optional().describe("Layer name filter, e.g. 'Edge.Cuts' (default: any layer)"),
      shape_type: z.string().optional().describe("Shape filter: 'polygon', 'line', 'arc', 'rect', 'any' (default: 'any')"),
      tolerance: z.number().optional().describe("Max search radius in mm (default: 5.0)"),
    },
    async (args: { x: number; y: number; layer?: string; shape_type?: string; tolerance?: number }) => {
      const result = await callKicadScript("delete_pcb_shape", args);
      if (result.success) {
        return { content: [{ type: "text", text: result.message }] };
      } else {
        return { content: [{ type: "text", text: `delete_pcb_shape failed: ${result.message}` }] };
      }
    },
  );

  // ------------------------------------------------------
  // Add Edge Cut Line Tool
  // ------------------------------------------------------
  server.tool(
    "add_edge_cut_line",
    "Add a single straight segment on a layer (default Edge.Cuts) between two points. Use to patch/close a board outline (e.g. after delete_pcb_shape removed an edge-slot detour) without redrawing the whole outline.",
    {
      x1: z.number().describe("Start point X in mm"),
      y1: z.number().describe("Start point Y in mm"),
      x2: z.number().describe("End point X in mm"),
      y2: z.number().describe("End point Y in mm"),
      layer: z.string().optional().describe("Layer name (default: 'Edge.Cuts')"),
      width: z.number().optional().describe("Stroke width in mm (default: 0 = hairline)"),
      unit: z.enum(["mm", "mil", "inch"]).optional().describe("Unit (default: mm)"),
    },
    async (args: { x1: number; y1: number; x2: number; y2: number; layer?: string; width?: number; unit?: string }) => {
      const result = await callKicadScript("add_edge_cut_line", args);
      if (result.success) {
        return { content: [{ type: "text", text: result.message }] };
      } else {
        return { content: [{ type: "text", text: `add_edge_cut_line failed: ${result.message}` }] };
      }
    },
  );
}
