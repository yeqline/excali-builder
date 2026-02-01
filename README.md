# Excali-Builder

A Python tool that generates [Excalidraw](https://excalidraw.com/) diagrams from structured data (CSV or Markdown files) with persistent layout.

## Why?

- **Version control your diagrams**: Keep diagram content in text files (CSV/Markdown), track changes with git
- **Preserve manual layouts**: Edit positions in Excalidraw, and they persist across rebuilds
- **Type-based styling**: Define visual styles per node/edge type in config files
- **Two connection types**: Model both hierarchical grouping (containers) and relationships (arrows)

## Quick Start

```bash
# Install
pip install -e .

# Build a diagram from a folder
excali-builder path/to/your-diagram-folder
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
├── edge_config.json    # Styling and behavior per edge type
├── config.json         # {"parser_type": "csv"}
└── output.excalidraw   # Generated output
```

See [CSV Parser Guide](docs/csv-parser-guide.md) for details.

### Markdown Format

```
your-diagram/
├── *.md                # Markdown files with ## Heading {#node-id} anchors
├── node_config.json    # Styling per node type
├── edge_config.json    # Styling and behavior per edge type
├── config.json         # {"parser_type": "md"}
└── output.excalidraw   # Generated output
```

See [Markdown Parser Guide](docs/md-parser-guide.md) for details.

## Connection Types

Edges can be one of two types (defined in `edge_config.json`):

- **Container** (`connection_type: "container"`): Groups child nodes with parent. No arrows, just visual proximity.
- **Line** (`connection_type: "line"`): Draws arrows/lines between nodes.

Example `edge_config.json`:

```json
{
  "parent_child": {
    "connection_type": "container",
    "placement": "outside",
    "direction": "bottom",
    "child_offset": 30
  },
  "depends_on": {
    "connection_type": "line",
    "color": "#DC2626",
    "stroke_width": 2,
    "arrow_end": "arrow"
  }
}
```

## Documentation

- [CSV Parser Guide](docs/csv-parser-guide.md) — How to use CSV files
- [Markdown Parser Guide](docs/md-parser-guide.md) — How to use Markdown files
- [Development Guide](docs/DEVELOPMENT.md) — For contributors: architecture, adding parsers, etc.

## Requirements

- Python 3.8+
- pydantic >= 2.0

## License

MIT License — see [LICENSE](LICENSE)
