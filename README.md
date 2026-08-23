# Excali-Builder

A Python tool that generates [Excalidraw](https://excalidraw.com/) diagrams from direct graphs, CSV, Markdown, or dbt manifest files with persistent layout.

## Why?

- **Version control your diagrams**: Keep diagram content in JSON, CSV, or Markdown, and track changes with git
- **Preserve manual layouts**: Edit positions in Excalidraw, and they persist across rebuilds
- **Type-based styling**: Define visual styles per node/edge type in config files
- **Deterministic initial layout**: Fresh builds use free-form, tree, or DAG placement
- **Multiple rendering modes for edges**: Draw arrows with `line`, visually group nodes with `group`, or draw enclosing groups with `enclosing_group`
- **Visible relationship labels**: Render non-empty line-edge labels by default, with per-type styling and opt-out
- **Built-in Markdown link/comment nodes**: Create clickable resource nodes or annotation nodes with default styling
- **Markdown image attachments**: Keep standard `![alt](path)` images in `.md` previews and render them as attached Excalidraw images
- **Built-in procedures and ordered steps**: Model long step-by-step flows without abusing heading depth
- **Configs become explicit**: When a build encounters a used node or edge type missing from config, it writes that type into the config file and then renders from config only

## Quick Start

Run the CLI directly with `uv`. No separate install step is required for normal local use.

```bash
# Start the live mind-map workflow
uv run excali-builder serve path/to/your-diagram-folder
```

## Main Workflow

The intended workflow is an AI-assisted editing loop:

1. Ask an AI agent to create an initial mind map for a subject in a diagram folder.
2. Run `uv run excali-builder serve path/to/your-diagram-folder`.
3. Open the local viewer URL printed by the command.
4. Review the generated Excalidraw map in the browser.
5. Reposition or resize nodes directly in the viewer; layout saves automatically to `positions.json`.
6. Ask the AI agent to edit `graph.json`, Markdown, CSV, or config files while `serve` keeps running.
7. The server rebuilds automatically and the viewer refreshes without a manual reload or separate build command.

In this loop, source files are the durable content model and the browser is the durable layout editor. Use the AI agent for titles, body text, relationships, node types, and styling config; use the local viewer for spatial review and layout adjustments.

```
AI edits graph/Markdown/CSV/config ──► serve rebuilds ──► local Excalidraw viewer
          ▲                                               │
          │                                               ▼
          └──────────── positions.json ◄── layout saves from viewer
```

## Serve Mode

`serve` runs the normal sync-then-build flow once, starts a local HTTP server, and watches the diagram folder for changes. The viewer uses the official `@excalidraw/excalidraw` React component, loads the generated `output.excalidraw`, and refreshes the scene after rebuilds without a manual browser reload.

```bash
uv run excali-builder serve path/to/your-diagram-folder
uv run excali-builder serve path/to/your-diagram-folder --port 0 --no-open
```

Watched files are top-level `*.md`, `*.csv`, `graph.json`, `config.json`, `node_config.json`, `edge_config.json`, and `output.excalidraw`. For dbt diagrams, configured manifest and overlay files are watched too, even when manifests live outside the visualization folder. Source and config edits rebuild the diagram. External saves to `output.excalidraw` sync layout into `positions.json` without triggering a rebuild loop.

Dragging or resizing generated nodes in the viewer is saved back to `positions.json` automatically. The server persists only layout fields for elements with `customData.node_id`; source files remain authoritative for titles, body text, relationships, and styles.

Layout saves also regenerate `output.excalidraw`, but they do not replace the scene already open in the browser. Source/config changes and external `output.excalidraw` saves still refresh the browser immediately. This keeps the live source-sync loop while avoiding a redundant full-scene reload after each drag or resize.

The viewer is served locally by the Python server and does not iframe `excalidraw.com`. To keep this Python package small and avoid committing a generated JavaScript bundle, the static page imports pinned browser ESM builds of React and `@excalidraw/excalidraw` from public CDNs on first page load.

## One-Shot Build Commands

The original commands still work for scripts or one-off export workflows:

```bash
# Build a diagram from a folder
uv run excali-builder path/to/your-diagram-folder

# Rebuild layout from scratch but keep saved node sizes
uv run excali-builder --full-refresh path/to/your-diagram-folder
```

A normal one-shot build syncs layout from any existing `output.excalidraw`, then regenerates the diagram. `serve` uses the same sync/build contract but keeps it running continuously.

## Input Formats

### Direct Free-form Graph

```text
your-diagram/
├── graph.json          # Versioned nodes and edges
├── node_config.json    # Styling per node type
├── edge_config.json    # Styling per edge type
├── config.json         # {"parser_type": "graph"}
├── positions.json      # Generated and manually edited node geometry
└── output.excalidraw   # Generated output
```

The direct graph format makes no hierarchy, sequence, lineage, root, or acyclicity assumptions. Every edge has a stable ID and can connect any two declared nodes, including itself. See the [Free-form Graph Guide](docs/freeform-graph-guide.md).

### CSV Format

```
your-diagram/
├── node.csv            # node_id, node_type, node_title, node_text
├── edge.csv            # from, to, edge_type, label
├── node_config.json    # Styling per node type
├── edge_config.json    # Styling per edge type
├── config.json         # {"parser_type": "csv", "layout": {...}}
└── output.excalidraw   # Generated output
```

See [CSV Parser Guide](docs/csv-parser-guide.md) for details.

### Markdown Format

```
your-diagram/
├── *.md                # Markdown files with ## Heading {#node-id} anchors
├── node_config.json    # Styling per node type
├── edge_config.json    # Styling per edge type
├── config.json         # {"parser_type": "md", "layout": {...}}
└── output.excalidraw   # Generated output
```

See [Markdown Parser Guide](docs/md-parser-guide.md) for details.
Use [Markdown Flow Guide](docs/markdown-flow-guide.md) when you want arbitrary workflows by connecting multiple H1 nodes with explicit Markdown edge directives.

### dbt Manifest Format

```
your-lineage-diagram/
├── config.json          # {"parser_type": "dbt", "parser_options": {...}}
├── dbt_overlay.json     # Optional human-authored graph annotations
├── node_config.json     # Styling per node type
├── edge_config.json     # Styling per edge type
└── output.excalidraw    # Generated output
```

The dbt parser reads one or more `manifest.json` files, merges included resources into one lineage graph, and uses `dbt_overlay.json` for groupings, additional node descriptions, comments, and local media. Tests are excluded by default.

See [dbt Parser Guide](docs/dbt-parser-guide.md) for details.

Example Markdown:

```markdown
## Review Pane {#review-pane}
> type: concept
> edge.related: review-pane-mirrors-git
> edge.contrasts: ide-approval-loop

The review pane reflects the state of the repository.
```

Ordered procedures can live alongside normal children:

```markdown
## Release Management {#release-management}

### Monitoring {#monitoring}
> type: concept

### Deploy Service {#deploy-service}
> type: procedure

#### Check Secrets {#deploy-check-secrets}
> type: step
> edge.next: deploy-build-image

#### Build Image {#deploy-build-image}
> type: step
```

Markdown images can stay standard and still become attachments in Excalidraw:

```markdown
## Deployment Notes {#deployment-notes}

The current flow uses this diagram ![Flow](media/flow.png) during rollouts.
```

## Layout And Edges

Used node and edge types are always made explicit in config files. If a build encounters a missing type such as `image`, `attachment`, `comment`, or `next`, it adds a starter entry to `node_config.json` or `edge_config.json` and then reloads config from disk before layout and export. That means the folder config becomes the visible source of truth for rendering.

Tree layout is the default for existing formats. Direct graphs default to free-form placement. In Markdown, heading hierarchy is always structural even when a built-in child node uses a different rendered edge type:

- In Markdown, normal nested nodes get an inferred `parent_child` edge from heading nesting.
- Nested `type: link` nodes keep the same placement but use the built-in `link` edge style unless you declare explicit `link:` edges.
- Nested `type: comment` nodes keep the same placement but use the built-in `comment` edge style.
- Markdown images inside a node body become implicit `image` child nodes that use the built-in `attachment` edge style.
- Nested `type: step` nodes under a `type: procedure` parent keep the same structural placement, but their inferred hierarchy edge uses the built-in `procedure_step` style and optional `next` edges control step order.
- In CSV, use `edge_type: parent_child` for edges that should define the tree.

`connection_type` changes how an edge is represented:

- **Line** (`connection_type: "line"`): Draws arrows/lines between nodes.
- **Group** (`connection_type: "group"`): No arrow is drawn. Parent and children are grouped in Excalidraw.
- **Enclosing group** (`connection_type: "enclosing_group"`): No arrow is drawn. Parent and children are grouped in Excalidraw, and the parent node is resized to enclose its children.

Non-empty labels on line edges are rendered by default. Edge types can set `show_label`, `label_color`, and `label_font_size`. Group and enclosing-group relationships do not render labels.

Line edge types can also define `max_length`. When a positioned line would be longer than that center-to-center distance, the arrow is omitted and the builder adds two generated `link` nodes, one near each endpoint. Those generated nodes have stable IDs, so moving them in Excalidraw is preserved through `positions.json`.

In Markdown, there are also built-in `link` and `comment` node types:

- a `link` node has one `target`
- `target: https://...` creates an external link
- `target: node-id` or `target: #node-id` creates an internal Excalidraw jump
- a Markdown image such as `![Flow](media/flow.png)` becomes an attached Excalidraw image element
- image paths must point to local files inside the diagram folder
- initial image size comes from the source file dimensions; later resizes are preserved in `positions.json`
- if a nested `link` node does not declare an explicit `link:` edge, the builder automatically connects it to its parent with the built-in `link` edge style
- a nested `comment` node is still laid out as a child, but its inferred edge uses the built-in `comment` edge style instead of `parent_child`
- a `procedure` node can be a normal child in the hierarchy
- nested `step` nodes under a `procedure` get an inferred `procedure_step` edge, which defaults to `group`
- `edge.next:` connects one step to the next and is used to order steps inside a procedure

Example `edge_config.json`:

```json
{
  "parent_child": {
    "connection_type": "line",
    "arrow_end": "arrow"
  },
  "depends_on": {
    "connection_type": "line",
    "color": "#DC2626",
    "stroke_width": 2,
    "arrow_end": "arrow",
    "max_length": 1600
  }
}
```

Example `config.json`:

```json
{
  "parser_type": "md",
  "layout": {
    "algorithm": "tree",
    "direction": "left-right",
    "level_spacing": 180,
    "sibling_spacing": 40
  }
}
```

## Documentation

- [Free-form Graph Guide](docs/freeform-graph-guide.md) — How to define unrestricted nodes and edges in `graph.json`
- [CSV Parser Guide](docs/csv-parser-guide.md) — How to use CSV files
- [Markdown Parser Guide](docs/md-parser-guide.md) — How to use Markdown files
- [Markdown Flow Guide](docs/markdown-flow-guide.md) — How to create arbitrary workflows with multiple H1 nodes and explicit edges
- [dbt Parser Guide](docs/dbt-parser-guide.md) — How to visualize dbt manifest lineage with overlays
- [Development Guide](docs/development-guide.md) — For contributors: architecture, adding parsers, etc.

## Requirements

- Python 3.8+
- pydantic >= 2.0

## License

MIT License — see [LICENSE](LICENSE)
