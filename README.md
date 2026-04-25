# Excali-Builder

A Python tool that generates [Excalidraw](https://excalidraw.com/) diagrams from structured data (CSV or Markdown files) with persistent layout.

## Why?

- **Version control your diagrams**: Keep diagram content in text files (CSV/Markdown), track changes with git
- **Preserve manual layouts**: Edit positions in Excalidraw, and they persist across rebuilds
- **Type-based styling**: Define visual styles per node/edge type in config files
- **Simple initial layout**: Fresh builds always start from the same tree layout
- **Two rendering modes for edges**: Hide hierarchy arrows with `container` or draw them with `line`
- **Built-in Markdown link/comment nodes**: Create clickable resource nodes or annotation nodes with default styling
- **Markdown image attachments**: Keep standard `![alt](path)` images in `.md` previews and render them as attached Excalidraw images
- **Built-in procedures and ordered steps**: Model long step-by-step flows without abusing heading depth
- **Configs become explicit**: When a build encounters a used node or edge type missing from config, it writes that type into the config file and then renders from config only

## Quick Start

Run the CLI directly with `uv`. No separate install step is required for normal local use.

```bash
# Build a diagram from a folder
uv run excali-builder path/to/your-diagram-folder

# Rebuild layout from scratch but keep saved node sizes
uv run excali-builder --full-refresh path/to/your-diagram-folder
```

## How It Works

1. **Define content** in source files (CSV or Markdown)
2. **Run excali-builder** to generate `output.excalidraw`
3. **Open in Excalidraw**, arrange nodes as you like, save
4. **Re-run excali-builder** — your layout is preserved, content updates from source

```
Source Files (CSV/MD) ──► Build ──► output.excalidraw
                              ▲           │
                              │           ▼
                        positions.json ◄──┘ (sync on next build)
```

## Input Formats

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

Initial layout is always a tree. In Markdown, heading hierarchy is always structural even when a built-in child node uses a different rendered edge type:

- In Markdown, normal nested nodes get an inferred `parent_child` edge from heading nesting.
- Nested `type: link` nodes keep the same placement but use the built-in `link` edge style unless you declare explicit `link:` edges.
- Nested `type: comment` nodes keep the same placement but use the built-in `comment` edge style.
- Markdown images inside a node body become implicit `image` child nodes that use the built-in `attachment` edge style.
- Nested `type: step` nodes under a `type: procedure` parent keep the same structural placement, but their inferred hierarchy edge uses the built-in `procedure_step` style and optional `next` edges control step order.
- In CSV, use `edge_type: parent_child` for edges that should define the tree.

`connection_type` only changes how an edge is rendered:

- **Container** (`connection_type: "container"`): No arrow is drawn. Parent and children are grouped in Excalidraw.
- **Line** (`connection_type: "line"`): Draws arrows/lines between nodes.

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
- nested `step` nodes under a `procedure` get an inferred `procedure_step` edge, which defaults to `container`
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
    "arrow_end": "arrow"
  }
}
```

Example `config.json`:

```json
{
  "parser_type": "md",
  "layout": {
    "direction": "left-right",
    "level_spacing": 180,
    "sibling_spacing": 40
  }
}
```

## Documentation

- [CSV Parser Guide](docs/csv-parser-guide.md) — How to use CSV files
- [Markdown Parser Guide](docs/md-parser-guide.md) — How to use Markdown files
- [Development Guide](docs/development-guide.md) — For contributors: architecture, adding parsers, etc.

## Requirements

- Python 3.8+
- pydantic >= 2.0

## License

MIT License — see [LICENSE](LICENSE)
