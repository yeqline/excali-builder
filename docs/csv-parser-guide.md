# CSV Parser User Guide

This guide explains how to use the CSV parser to create Excalidraw diagrams from CSV files.

## Overview

The CSV parser reads node and edge definitions from CSV files and converts them into Excalidraw diagrams. The parser supports two types of connections:

- **Container connections**: Grouping/hierarchy relationships (children are grouped with their parent)
- **Line connections**: Relationship arrows between nodes

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
- `label`: Optional label text for the edge (currently not displayed, reserved for future use)

**Example:**

```csv
from,to,edge_type,label
root,auth,port_group,
root,db,port_group,
root,api,port_group,
auth,user-service,port_group,
db,user-service,directional_link,queries
user-service,cache,directional_link,uses
api,user-service,directional_link,calls
```

**Important**: The `connection_type` (container vs line) is determined from `edge_config.json` based on the `edge_type`. You don't specify it in the CSV.

## Configuration Files

### config.json

General configuration for the diagram project.

```json
{
  "parser_type": "csv",
  "default_layout": "radial"
}
```

**Options:**

- `parser_type`: Must be `"csv"` for CSV parser
- `default_layout`: Default layout algorithm for nodes without positions
  - `"radial"`: Circular hierarchical layout (default)
  - `"tree"`: Traditional tree layout

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

Defines styling and behavior for different edge types. Each edge type must specify its `connection_type` (container or line) along with its styling properties.

#### Container Connection Configuration

For edge types with `"connection_type": "container"`:

```json
{
  "port_group": {
    "connection_type": "container",
    "placement": "outside",
    "direction": "bottom",
    "child_offset": 30,
    "group_padding": 20
  }
}
```

**Container Connection Options:**

- `connection_type`: Must be `"container"` for grouping connections
- `placement`: How children are positioned relative to parent
  - `"inside"`: Children are positioned inside the parent's bounds
  - `"outside"`: Children are positioned outside/around the parent (default)
- `direction`: Direction children are arranged relative to parent
  - `"top"`: Children arranged above the parent
  - `"bottom"`: Children arranged below the parent (default)
  - `"left"`: Children arranged to the left of the parent
  - `"right"`: Children arranged to the right of the parent
  - `"radial"`: Children arranged in a circular pattern around the parent
  - `"center_h"`: Children arranged horizontally at the center height (middle of container) - only for `placement: "inside"`
  - `"center_v"`: Children arranged vertically at the center width (middle of container) - only for `placement: "inside"`
- `child_offset`: Spacing between parent and children in pixels (integer, used when `placement: "outside"`)
- `group_padding`: Padding inside parent bounds in pixels (integer, used when `placement: "inside"`)

**Container Connection Behavior:**

- Container connections create visual groups in Excalidraw
- Selecting one element in a group selects all elements in that group
- No arrows are drawn for container connections (they represent grouping, not relationships)

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
    "arrow_end": "arrow"
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

**Line Connection Behavior:**

- Line connections create arrows between nodes
- Arrows are bound to nodes, so they move together when nodes are moved
- Arrow endpoints automatically connect to node edges

## Workflow

### 1. Create Your Diagram Files

1. Create a folder for your diagram
2. Add `node.csv` with your nodes
3. Add `edge.csv` with your connections
4. Create `node_config.json` with node type styling
5. Create `edge_config.json` with edge type styling (including `connection_type` for each edge type)
6. Create `config.json` with parser type and layout settings

### 2. Build the Diagram

Run the build command:

```bash
uv run excali-builder your-diagram-folder
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
root,child1,port_group,
root,child2,port_group,
```

**edge_config.json:**

```json
{
  "port_group": {
    "connection_type": "container",
    "placement": "outside",
    "direction": "bottom",
    "child_offset": 30,
    "group_padding": 20
  }
}
```

This creates a hierarchy where `child1` and `child2` are grouped with `root` and arranged below it.

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

### Example 3: Mixed Container and Line Connections

You can combine both types in the same diagram:

**edge.csv:**

```csv
from,to,edge_type,label
root,module-a,port_group,
root,module-b,port_group,
module-a,service-x,calls,
module-b,service-x,calls,
```

**edge_config.json:**

```json
{
  "port_group": {
    "connection_type": "container",
    "placement": "outside",
    "direction": "radial",
    "child_offset": 50,
    "group_padding": 15
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

This creates a diagram where `module-a` and `module-b` are grouped with `root` in a radial pattern, and both call `service-x` via arrows.

## Tips and Best Practices

1. **Stable Node IDs**: Use stable, meaningful IDs in `node_id` column. These are used for syncing positions, so changing them will lose saved positions.

2. **Edge Types**: Create meaningful edge type names (e.g., `"dependency"`, `"inheritance"`, `"port_group"`) rather than generic names. This makes your configuration more maintainable.

3. **Container vs Line**: Use container connections for grouping/hierarchy (e.g., modules containing components). Use line connections for relationships (e.g., dependencies, data flow).

4. **Position Persistence**: After editing positions in Excalidraw, always run the build command again to sync positions. The positions are saved to `positions.json` and will be used in future builds.

5. **Layout Direction**: For container connections, choose `direction` based on your diagram's flow:

   - `"bottom"`: Top-down hierarchy (most common)
   - `"right"`: Left-to-right flow
   - `"radial"`: Circular/network diagrams

6. **Color Schemes**: Use consistent color schemes across node types to create visual categories (e.g., all modules use green, all components use yellow).

7. **Arrow Styles**: Use different arrow styles to convey different relationship types:
   - Solid arrows: Strong relationships
   - Dashed arrows: Optional/weak relationships
   - No arrowheads: Bidirectional or undirected relationships

## Troubleshooting

### Nodes not appearing in groups

- Check that `edge_type` in `edge.csv` matches a key in `edge_config.json`
- Verify that the edge type has `"connection_type": "container"` in `edge_config.json`
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

- Adjust `child_offset` and `group_padding` values for better spacing
- Try different `direction` values for container connections
- Use `default_layout` in `config.json` to change the overall layout algorithm
