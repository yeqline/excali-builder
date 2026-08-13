# Development Guide

This document is for developers working on excali-builder. It explains the architecture, design decisions, and where to find/modify specific functionality.

## Purpose

excali-builder converts structured data into Excalidraw diagrams with persistent layout. The key innovation is the **two-way sync**: content comes from source files, but layout (positions/sizes) is preserved from user edits in Excalidraw.

## Core Concepts

### Connection Types

The system distinguishes three rendering behaviors for connections:

1. **Line connections** (`connection_type: "line"`):
   - Represent relationships between nodes
   - Rendered as arrows/lines in Excalidraw
   - Can have arrowheads, different colors, styles
   - Can define `max_length` to replace overlong arrows with two generated internal-link nodes
   - Example: A dependency arrow between services

2. **Group connections** (`connection_type: "group"`):
   - Do not draw visible arrows
   - Can be used to group related nodes in Excalidraw
   - Do not control layout
   - Example: Hide parent-child arrows while keeping a grouped hierarchy

3. **Enclosing group connections** (`connection_type: "enclosing_group"`):
   - Do not draw visible arrows
   - Group related nodes in Excalidraw
   - Resize and reposition the parent node around its children after base layout
   - Example: Draw a dbt domain box around the models assigned to that domain

### Stable IDs

Every node has a stable ID that persists across rebuilds. This ID is:
- Stored in Excalidraw element's `customData.node_id`
- Used to match positions from `positions.json` to nodes
- Must be unique within a project folder

Every edge also has a stable ID. Direct graphs declare it in `graph.json`; other producers receive a deterministic ID during the build. Edge IDs distinguish parallel relationships and provide stable Excalidraw arrow and label element IDs. Edge geometry is generated rather than synced.

### Data Flow

```
Build Flow:
  Source Files (graph.json/CSV/MD/dbt)
    → Parser 
    → Graph IR (nodes + edges) 
    → Merge positions.json 
    → Layout for new nodes 
    → Excalidraw export

Sync Flow:
  Excalidraw file 
    → Extract geometry by node_id from customData 
    → Update positions.json
```

## Architecture

```
excali_builder/
├── core/           # Data models (Node, Edge, Graph)
├── parsers/        # Input format parsers (graph, CSV, Markdown, dbt)
├── config/         # Configuration loading and schemas
├── layout/         # Positioning algorithms
├── excalidraw/     # Excalidraw import/export/sync
├── builder.py      # Main orchestration
└── cli.py          # Command-line interface
```

### Module Responsibilities

#### `core/` - Data Models

| File | Purpose |
|------|---------|
| `node.py` | Node model with id, label, type, geometry, metadata |
| `edge.py` | Edge model with source/target, connection_type, edge_type |
| `graph.py` | Graph container with nodes dict and edges list |

**Design decision**: Nodes store geometry (x, y, width, height) directly. This is authoritative when loaded from `positions.json`.

#### `parsers/` - Input Parsing

| File | Purpose |
|------|---------|
| `base.py` | Abstract `BaseParser` interface |
| `registry.py` | Parser registration by format name |
| `csv.py` | CSV parser (node.csv, edge.csv) |
| `dbt.py` | dbt manifest parser with optional `dbt_overlay.json` annotations |
| `graph.py` | Direct versioned graph parser (`graph.json`) |
| `markdown.py` | Markdown parser (headings with anchors) |

**To add a new parser**:
1. Create new file in `parsers/`
2. Extend `BaseParser`, implement `parse()` and `get_supported_formats()`
3. Register in `builder.py`'s `__init__`
4. Add to `parsers/__init__.py` exports

**Design decision**: Parsers produce the same raw `Graph` contract. The direct graph parser declares nodes and edges without inference. Markdown, CSV, and dbt act as graph-producing conventions. `connection_type` is looked up from `edge_config.json` based on `edge_type`. In Markdown, heading hierarchy is also stored on nodes as `hierarchy_parent_id`, so built-in child node types can render with a different inferred edge type without changing layout.
Markdown also supports built-in `link` and `comment` node types. Nested `link` nodes receive a default `link` edge to their parent unless the author explicitly declares `link:` edges. Nested `comment` nodes receive a default `comment` edge to their parent.

#### `config/` - Configuration

| File | Purpose |
|------|---------|
| `schema.py` | Pydantic models for config validation |
| `loader.py` | Load JSON config files from folder |

**Config files per project**:
- `config.json`: Parser type, tree layout settings
- `node_config.json`: Styling per node type
- `edge_config.json`: Styling and connection_type per edge type

**Design decision**: `edge_config.json` defines `connection_type` per edge_type. Markdown and CSV structural layout follows heading hierarchy or `parent_child` edges. `enclosing_group` then adjusts parent bounds around children after the base layout has run. For line edges with `max_length`, overlong arrows are replaced after layout with deterministic `link` nodes so their moved positions can be synced like any other generated node.

#### `layout/` - Positioning

| File | Purpose |
|------|---------|
| `base.py` | Abstract `BaseLayout` interface |
| `dag.py` | Layered DAG layout algorithm |
| `freeform.py` | Neighbour-aware placement for nodes without saved positions |
| `tree.py` | Tree layout algorithm |

**Key concept**: Layout only runs for nodes without positions. If a node has geometry from `positions.json`, it's used as-is. Initial placement uses the configured layout algorithm.

`layout.algorithm` selects the layout implementation. The default is `tree`, which preserves the existing Markdown and CSV behavior. Direct graphs default to `freeform` when no algorithm is declared. `dag` ranks nodes by configured dependency edge types such as `lineage`.

#### `excalidraw/` - Excalidraw Integration

| File | Purpose |
|------|---------|
| `exporter.py` | Convert Graph to Excalidraw JSON |
| `importer.py` | Parse Excalidraw JSON files |
| `sync.py` | Extract positions from Excalidraw to positions.json |

**Exporter creates**:
- Rectangle/ellipse elements for nodes
- Text elements bound to shape containers
- Arrow elements for line connections
- Bound text labels for non-empty line-edge labels
- Groups for `group` and `enclosing_group` relationships
- `customData.node_id` for position syncing
- Deterministic shape/text element IDs so internal link nodes can target other nodes reliably
- Deterministic edge and edge-label element IDs derived from stable edge IDs

**Design decision**: Only node positions are synced, not edge positions. Edges are regenerated from source and bound to nodes, so they auto-update when nodes move.

#### `builder.py` - Orchestration

The `ExcaliBuilder` class coordinates the full pipeline:
1. Detect parser from `config.json`
2. Parse source files → Graph
3. Load `positions.json` → apply to matching nodes
4. Run layout for unpositioned nodes
5. Export to Excalidraw

**Design decision**: Build always syncs first (if excalidraw file exists). This means running build after editing in Excalidraw automatically preserves your layout.

#### `cli.py` - Command Line

Simple CLI with one command: `excali-builder <folder>`

Runs sync (if excalidraw exists) then build.

## Common Development Tasks

### Adding a New Node Shape

1. Add shape to `config/schema.py` `NodeTypeConfig.shape` comment
2. Handle in `excalidraw/exporter.py` `_create_node_element()`

### Adding a New Edge Style Property

1. Add field to `config/schema.py` `EdgeTypeConfig`
2. Handle in `config/loader.py` `get_line_config()`
3. Apply in `excalidraw/exporter.py` `_create_edge_element()`

### Adding a New Layout Algorithm

1. Create new file in `layout/`
2. Extend `BaseLayout`, implement `apply_layout()`
3. Add to `builder.py` `_apply_layout_to_new_nodes()` selection logic

### Adding a New Parser

1. Create new file in `parsers/`
2. Extend `BaseParser`:
   ```python
   class MyParser(BaseParser):
       def parse(self, path: Path, options: Dict[str, Any]) -> Graph:
           # Parse files, create nodes and edges
           # Use ConfigLoader.get_connection_type() for edge types
           pass
       
       def get_supported_formats(self) -> List[str]:
           return ["myformat"]
   ```
3. Register in `builder.py`:
   ```python
   self.parser_registry.register("myformat", MyParser)
   ```
4. Export in `parsers/__init__.py`

### Debugging Position Sync Issues

1. Check `customData.node_id` in Excalidraw file matches source IDs
2. Verify `positions.json` is being written with correct IDs
3. Check sync runs before build (it should automatically)

## Design Principles

1. **Source files are authoritative for content**: Titles, relationships, types all come from CSV/MD files

2. **Excalidraw is authoritative for layout**: After user edits positions, those are preserved

3. **Hierarchy is explicit**: `parent_child` defines structural layout, while `connection_type` only changes rendering

4. **Stable IDs enable syncing**: Every node needs a unique, stable ID that persists across rebuilds

5. **Parsers produce uniform Graph IR**: Different input formats all produce the same internal representation

## Testing Locally

```bash
# Create an examples folder (gitignored)
mkdir -p examples/my-test

# Add source files and config to examples/my-test/

# Build
uv run excali-builder examples/my-test

# Open output.excalidraw in Excalidraw, edit positions, save

# Rebuild (positions are preserved)
uv run excali-builder examples/my-test
```

## Code Style

- Use Ruff for linting (configured in pyproject.toml)
- Only add comments explaining "why", not "how"
- Keep functions focused and modular
- Follow existing patterns when adding new features
