# CSV Parser User Guide

This guide explains how to use the CSV parser to create Excalidraw diagrams from CSV files.

## Overview

The CSV parser reads node and edge definitions from CSV files and converts them into Excalidraw diagrams. Fresh builds always use a tree layout. The hierarchy for that tree comes from edges with `edge_type: parent_child`.

- **Line connections**: Relationship arrows between nodes
- **Group connections**: No arrow is drawn; related nodes are grouped in Excalidraw
- **Enclosing group connections**: No arrow is drawn; the parent node is resized around child nodes

## Project Structure

A diagram project folder should contain:

```
your-diagram/
├── node.csv            # Node definitions
├── edge.csv            # Edge/connection definitions
├── node_config.json    # Node styling configuration
├── edge_config.json    # Edge styling configuration
├── config.json         # General configuration
├── positions.json      # Layout positions (auto-generated after sync)
└── output.excalidraw   # Generated Excalidraw file
```

## CSV Files

### node.csv

Defines all nodes in your diagram. Required columns:

- `node_id`: Unique identifier for the node (used for syncing positions)
- `node_type`: Type of node (used for styling lookup in `node_config.json`)
- `node_title`: Title text displayed on the first line of the node
- `node_text`: Additional text displayed on the second line of the node (optional)

**Example:**

```csv
node_id,node_type,node_title,node_text
root,module,Root Module,Main entry point of the system
auth,module,Authentication,Handles user authentication
db,module,Database,Database connection and queries
user-service,component,User Service,Manages user operations
api,port,API Gateway,External API interface
cache,component,Cache Layer,In-memory caching system
```

### edge.csv

Defines connections between nodes. Required columns:

- `from`: Source node ID (must match a `node_id` in `node.csv`)
- `to`: Target node ID (must match a `node_id` in `node.csv`)
- `edge_type`: Type of edge (used for styling and connection type lookup in `edge_config.json`)
- `label`: Optional label text rendered on line connections by default

**Example:**

```csv
from,to,edge_type,label
root,auth,parent_child,
root,db,parent_child,
root,api,parent_child,
auth,user-service,parent_child,
db,user-service,directional_link,queries
user-service,cache,directional_link,uses
api,user-service,directional_link,calls
```

**Important**:

- Use `edge_type: parent_child` for edges that should define the tree layout.
- The `connection_type` is still determined from `edge_config.json`; it only affects rendering.

## Configuration Files

### config.json

General configuration for the diagram project.

```json
{
  "parser_type": "csv",
  "layout": {
    "direction": "left-right",
    "level_spacing": 180,
    "sibling_spacing": 40,
    "root_spacing": 100,
    "start_x": 120,
    "start_y": 120
  }
}
```

**Options:**

- `parser_type`: Must be `"csv"` for CSV parser
- `layout.direction`: Tree direction. One of `"left-right"`, `"right-left"`, `"top-down"`, `"bottom-up"`
- `layout.level_spacing`: Gap between parent and child levels
- `layout.sibling_spacing`: Gap between sibling subtrees
- `layout.root_spacing`: Gap between separate top-level trees
- `layout.start_x`, `layout.start_y`: Starting position for the initial layout

### node_config.json

Defines styling for different node types. Each node type can have its own visual style.

```json
{
  "module": {
    "color": "#2D5F2D",
    "backgroundColor": "#E8F5E8",
    "shape": "rectangle",
    "font_size": 16,
    "padding": 15,
    "borderRadius": 8
  },
  "component": {
    "color": "#7C2D12",
    "backgroundColor": "#FEF3C7",
    "shape": "rectangle",
    "font_size": 14,
    "padding": 10,
    "borderRadius": 4
  },
  "port": {
    "color": "#1E40AF",
    "backgroundColor": "#EFF6FF",
    "shape": "ellipse",
    "font_size": 12,
    "padding": 8,
    "borderRadius": 15
  }
}
```

**Node Type Configuration Options:**

- `color`: Text color (hex color code, e.g., `"#2D5F2D"`)
- `backgroundColor`: Background color of the node (hex color code)
- `shape`: Node shape
  - `"rectangle"`: Rectangular box (default)
  - `"ellipse"`: Circular/oval shape
  - `"diamond"`: Diamond shape
- `font_size`: Font size in pixels (integer)
- `font_family`: Font family name (e.g., `"Arial"`, `"Helvetica"`)
- `padding`: Internal padding around text in pixels (integer)
- `borderRadius`: Corner radius for rectangles in pixels (integer, 0 = sharp corners)

### edge_config.json

Defines rendering behavior for different edge types. Each edge type must specify its `connection_type` (`line`, `group`, or `enclosing_group`) along with any styling properties.

#### Parent-Child Hierarchy

Only edges with `edge_type: parent_child` define the tree layout. You can still choose how those edges render:

```json
{
  "parent_child": {
    "connection_type": "group"
  }
}
```

or

```json
{
  "parent_child": {
    "connection_type": "line",
    "arrow_end": "arrow"
  }
}
```

**Behavior:**

- Tree placement follows the same hierarchy.
- `line` draws a visible parent-child line.
- `group` hides the arrow and groups the related nodes in Excalidraw.
- `enclosing_group` hides the arrow, groups the related nodes in Excalidraw, and resizes the parent node around its children.

#### Line Connection Configuration

For edge types with `"connection_type": "line"`:

```json
{
  "directional_link": {
    "connection_type": "line",
    "color": "#DC2626",
    "stroke_width": 3,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow",
    "max_length": 1600
  },
  "link": {
    "connection_type": "line",
    "color": "#6B7280",
    "stroke_width": 3,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": null
  }
}
```

**Line Connection Options:**

- `connection_type`: Must be `"line"` for relationship arrows
- `color`: Arrow/line color (hex color code)
- `stroke_width`: Line thickness in pixels (integer)
- `stroke_style`: Line style
  - `"solid"`: Solid line (default)
  - `"dashed"`: Dashed line
  - `"dotted"`: Dotted line
- `arrow_start`: Arrowhead at the start of the line
  - `null`: No arrowhead
  - `"arrow"`: Standard arrowhead
  - `"circle"`: Circular arrowhead
- `arrow_end`: Arrowhead at the end of the line
  - `null`: No arrowhead
  - `"arrow"`: Standard arrowhead (default)
  - `"circle"`: Circular arrowhead
- `max_length`: Optional center-to-center maximum length in pixels. Longer positioned lines are replaced with two generated internal-link nodes.
- `show_label`: Whether non-empty edge labels are rendered. Defaults to `true`.
- `label_color`: Label color. Defaults to the line color when omitted or `null`.
- `label_font_size`: Label font size. Defaults to `14`.

**Line Connection Behavior:**

- Line connections create arrows between nodes
- Arrows are bound to nodes, so they move together when nodes are moved
- Arrow endpoints automatically connect to node edges
- Generated long-line link nodes use stable IDs and persist moved positions in `positions.json`

## Workflow

### 1. Create Your Diagram Files

1. Create a folder for your diagram
2. Add `node.csv` with your nodes
3. Add `edge.csv` with your connections
4. Create `node_config.json` with node type styling
5. Create `edge_config.json` with edge type styling (including `connection_type` for each edge type)
6. Create `config.json` with parser type and tree layout settings

### 2. Build the Diagram

Run the build command:

```bash
uv run excali-builder your-diagram-folder
```

To discard the current saved layout and generate a fresh first-pass layout while preserving saved node sizes:

```bash
uv run excali-builder --full-refresh your-diagram-folder
```

This will:

1. Sync positions from any existing `output.excalidraw` file (if present)
2. Parse your CSV files
3. Apply saved positions from `positions.json` (if present)
4. Layout new nodes using the configured layout algorithm
5. Generate `output.excalidraw`

### 3. Edit in Excalidraw

1. Open `output.excalidraw` in Excalidraw
2. Move nodes to desired positions
3. Resize nodes if needed
4. Save the file

### 4. Sync Positions

The next time you run the build command, it will automatically:

1. Read the `output.excalidraw` file
2. Extract node positions and sizes
3. Save them to `positions.json`
4. Use these positions when rebuilding

**Note**: Only node positions and sizes are synced. Content (titles, text, connections) always comes from your CSV files.

## Examples

### Example 1: Simple Hierarchy

**node.csv:**

```csv
node_id,node_type,node_title,node_text
root,module,Root,Main module
child1,component,Child 1,First child
child2,component,Child 2,Second child
```

**edge.csv:**

```csv
from,to,edge_type,label
root,child1,parent_child,
root,child2,parent_child,
```

**edge_config.json:**

```json
{
  "parent_child": {
    "connection_type": "group"
  }
}
```

This creates a hierarchy where `child1` and `child2` are laid out as children of `root`, without visible parent-child arrows.

### Example 2: Relationship Diagram

**edge.csv:**

```csv
from,to,edge_type,label
service-a,service-b,dependency,depends on
service-b,database,queries,queries
```

**edge_config.json:**

```json
{
  "dependency": {
    "connection_type": "line",
    "color": "#DC2626",
    "stroke_width": 2,
    "stroke_style": "dashed",
    "arrow_start": null,
    "arrow_end": "arrow"
  },
  "queries": {
    "connection_type": "line",
    "color": "#059669",
    "stroke_width": 3,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow"
  }
}
```

This creates arrows showing relationships between services.

### Example 3: Mixed Hierarchy and Relationship Edges

You can combine both types in the same diagram:

**edge.csv:**

```csv
from,to,edge_type,label
root,module-a,parent_child,
root,module-b,parent_child,
module-a,service-x,calls,
module-b,service-x,calls,
```

**edge_config.json:**

```json
{
  "parent_child": {
    "connection_type": "group"
  },
  "calls": {
    "connection_type": "line",
    "color": "#3B82F6",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow"
  }
}
```

This creates a diagram where `module-a` and `module-b` are laid out as children of `root`, and both call `service-x` via arrows.

## Tips and Best Practices

1. **Stable Node IDs**: Use stable, meaningful IDs in `node_id` column. These are used for syncing positions, so changing them will lose saved positions.

2. **Edge Types**: Create meaningful edge type names (e.g., `"dependency"`, `"queries"`, `"calls"`) rather than generic names. Reserve `parent_child` for hierarchy.

3. **Group vs Line**: Use `parent_child` for hierarchy, then choose whether that hierarchy should render as `group`, `enclosing_group`, or `line`. Use other line edge types for relationships such as dependencies or data flow.

4. **Position Persistence**: After editing positions in Excalidraw, always run the build command again to sync positions. The positions are saved to `positions.json` and will be used in future builds.

5. **Layout Direction**: Choose `layout.direction` in `config.json` based on your diagram's flow:

   - `"left-right"`: Most mind maps and concept maps
   - `"top-down"`: Traditional org-chart style
   - `"right-left"` / `"bottom-up"`: Alternative directional flows

6. **Color Schemes**: Use consistent color schemes across node types to create visual categories (e.g., all modules use green, all components use yellow).

7. **Arrow Styles**: Use different arrow styles to convey different relationship types:
   - Solid arrows: Strong relationships
   - Dashed arrows: Optional/weak relationships
   - No arrowheads: Bidirectional or undirected relationships

## Troubleshooting

### Nodes not appearing in groups

- Check that `edge_type` in `edge.csv` matches a key in `edge_config.json`
- Verify that the edge type has `"connection_type": "group"` or `"connection_type": "enclosing_group"` in `edge_config.json`
- Ensure parent and child node IDs exist in `node.csv`

### Arrows not showing

- Verify that `edge_type` has `"connection_type": "line"` in `edge_config.json`
- Check that source and target node IDs exist in `node.csv`
- Ensure arrow color is visible against the background

### Positions not persisting

- Make sure you save the `output.excalidraw` file in Excalidraw
- Run the build command after saving to sync positions
- Check that `positions.json` is being created/updated

### Layout issues

- Adjust `layout.level_spacing`, `layout.sibling_spacing`, or `layout.root_spacing` in `config.json`
- Try a different `layout.direction`
- Use `--full-refresh` when you want to rebuild the tree from scratch while keeping saved node sizes
