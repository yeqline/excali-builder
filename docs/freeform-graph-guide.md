# Free-form Graph Guide

The direct graph parser reads `graph.json` as an unrestricted collection of nodes and edges. It does not infer hierarchy, sequence, lineage, roots, or acyclicity. Markdown, CSV, and dbt inputs produce the same internal graph through their own conventions; `graph.json` exposes that graph directly.

## Folder Structure

```text
your-diagram/
├── graph.json
├── config.json
├── node_config.json
├── edge_config.json
├── positions.json
└── output.excalidraw
```

- `graph.json` owns node and edge content.
- `node_config.json` owns node-type styling.
- `edge_config.json` owns edge-type styling and rendering.
- `positions.json` owns generated and manually edited node geometry.
- `output.excalidraw` is generated output.

## config.json

Select the direct graph parser:

```json
{
  "parser_type": "graph"
}
```

The graph parser uses free-form placement when `layout.algorithm` is omitted. It can also be selected explicitly:

```json
{
  "parser_type": "graph",
  "layout": {
    "algorithm": "freeform",
    "sibling_spacing": 64,
    "start_x": 120,
    "start_y": 120
  }
}
```

## graph.json

```json
{
  "version": 1,
  "nodes": [
    {
      "id": "api",
      "type": "service",
      "label": "API",
      "text": "Public application interface",
      "metadata": {
        "owner": "platform"
      }
    },
    {
      "id": "orders-db",
      "type": "database",
      "label": "Orders Database"
    }
  ],
  "edges": [
    {
      "id": "api-reads-orders",
      "source": "api",
      "target": "orders-db",
      "type": "reads",
      "label": "reads from",
      "metadata": {
        "protocol": "SQL"
      }
    }
  ]
}
```

### Node Fields

- `id`: Required stable node ID, unique within the file.
- `type`: Required node type resolved through `node_config.json`.
- `label`: Optional display title. Defaults to `id`.
- `text`: Optional body text.
- `metadata`: Optional arbitrary source metadata.

### Edge Fields

- `id`: Required stable edge ID, unique within the file.
- `source`: Required source node ID.
- `target`: Required target node ID.
- `type`: Required edge type resolved through `edge_config.json`.
- `label`: Optional relationship label.
- `metadata`: Optional arbitrary source metadata.

Geometry fields are not part of `graph.json`. Positions, sizes, text alignment, and wrapped-text geometry remain in `positions.json`.

## Topology Rules

Every edge endpoint must reference a declared node. Beyond that structural requirement, graph topology is unrestricted:

- cycles are valid;
- self-loops are valid;
- parallel and opposite-direction edges are valid;
- nodes can have any number of incoming or outgoing edges;
- isolated nodes are valid;
- edge type names have no built-in structural meaning.

Self-loops and parallel edges use normal Excalidraw line generation and can overlap. Edge geometry is regenerated during each build; only node geometry is synced to `positions.json`.

## Placement And Position Persistence

The first successful build creates `positions.json`. Later builds preserve every node with saved geometry and place only new nodes.

- A new node connected to positioned nodes is placed near those neighbours.
- A connected set of new nodes expands outward from positioned neighbours.
- In live serve mode, an unconnected node uses a recent canvas pointer or the current viewport center.
- Without live canvas context, an unconnected node uses a deterministic collision-free position near existing content.
- A first build uses deterministic compact placement around the configured starting point.

Run `--full-refresh` to intentionally rebuild all x/y placement while retaining saved node sizes, matching the behavior of other input formats.

## Edge Labels

Non-empty labels on `line` connections render by default. Labels on `group` and `enclosing_group` connections are not rendered because those relationships have no visible connector.

```json
{
  "reads": {
    "connection_type": "line",
    "color": "#2563EB",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow",
    "show_label": true,
    "label_color": "#1E3A8A",
    "label_font_size": 14
  }
}
```

Set `show_label` to `false` to hide labels for an edge type. If `label_color` is `null`, the edge color is used.

## Build And Serve

```bash
uv run excali-builder path/to/your-diagram
uv run excali-builder serve path/to/your-diagram
```

Live serve mode watches `graph.json`, rebuilds after source changes, and preserves node layout through the same viewer workflow used by every other parser.
