# dbt Parser Guide

The dbt parser creates an Excalidraw lineage diagram from one or more dbt `manifest.json` files. It is intended for dbt projects where the manifest is the authoritative source for resources and dependency edges, and a separate local overlay file carries diagram-only annotations.

## Folder Structure

Run `serve` against the visualization folder. The visualization folder owns generated Excalidraw files, style configs, saved positions, local media, and the overlay.

```text
lineage-visualization/
├── config.json
├── dbt_overlay.json
├── node_config.json
├── edge_config.json
├── positions.json
├── output.excalidraw
└── media/
```

The dbt project or dbt mesh repo can live elsewhere. Point to it from `config.json`.

```bash
uv run excali-builder serve path/to/lineage-visualization
```

## config.json

Use `parser_type: "dbt"` and provide one or more manifest paths.

```json
{
  "parser_type": "dbt",
  "parser_options": {
    "dbt_project_root": "../..",
    "manifest_paths": [
      "project_a/target/manifest.json",
      "project_b/target/manifest.json"
    ],
    "overlay_path": "dbt_overlay.json",
    "include_tests": false
  },
  "layout": {
    "algorithm": "dag",
    "direction": "left-right",
    "level_spacing": 240,
    "sibling_spacing": 60,
    "root_spacing": 140
  }
}
```

### Parser Options

| Field | Meaning |
| --- | --- |
| `dbt_project_root` | Base path used to resolve relative manifest paths. Relative values are resolved from the visualization folder. |
| `manifest_paths` | One or more dbt manifest files. Relative paths are resolved from `dbt_project_root`. |
| `manifest_path` | Single-manifest shortcut. |
| `overlay_path` | Overlay file path. Relative paths are resolved from the visualization folder. Defaults to `dbt_overlay.json`. |
| `resource_types` | Included dbt resource types. Defaults to `source`, `model`, `seed`, `snapshot`, and `exposure`. |
| `include_tests` | When `true`, includes dbt test nodes. Defaults to `false`. |

## Manifest Graph

Each included dbt resource becomes a graph node. The node ID is the dbt `unique_id`, which keeps position syncing stable across rebuilds.

The parser creates `lineage` edges from upstream resources to downstream resources using manifest dependency data. Edges to resources outside the included resource set are ignored.

Default node types:

- `dbt_source`
- `dbt_model`
- `dbt_seed`
- `dbt_snapshot`
- `dbt_exposure`
- `dbt_group`

Default edge types:

- `lineage`
- `group_member`
- `comment`
- `attachment`

Missing node and edge config entries are written to `node_config.json` and `edge_config.json` during build, matching the existing config behavior.

## dbt_overlay.json

The overlay is a human-authored JSON file for diagram-only information that is not stored in the dbt manifest.

```json
{
  "version": 1,
  "groups": {
    "Finance": {
      "Staging": [
        "stg_orders",
        "stg_customers"
      ],
      "Marts": [
        "finance.fct_orders"
      ]
    }
  },
  "nodes": {
    "finance.fct_orders": {
      "description": "Business-grain fact table with one row per order.",
      "comments": [
        {
          "id": "grain",
          "title": "Grain",
          "text": "Confirm joins preserve one row per order_id."
        }
      ],
      "media": [
        {
          "id": "lineage-note",
          "title": "Warehouse lineage",
          "path": "media/fct_orders_lineage.png"
        }
      ]
    }
  }
}
```

### Node References

Overlay references can use dbt `unique_id` values or shorter human-friendly names.

Supported string forms:

```json
"fct_orders"
"finance.fct_orders"
"model.finance.fct_orders"
"raw.orders"
"finance.raw.orders"
"source.finance.raw.orders"
```

Supported object forms:

```json
{ "unique_id": "model.finance.fct_orders" }
{ "model": "fct_orders", "project": "finance" }
{ "source": "raw.orders", "project": "finance" }
{ "resource_type": "model", "name": "fct_orders", "project": "finance" }
```

Bare names are valid only when they resolve to exactly one included dbt resource. Ambiguous references fail the build and list matching dbt `unique_id` values.

After a successful parse, the builder writes `dbt_node_index.json` in the visualization folder. This generated helper lists included resources and their supported reference forms.

### Groups

Groups create `dbt_group` nodes and `group_member` container edges. Nested object syntax is concise for human-authored overlays:

```json
{
  "groups": {
    "Finance": {
      "Staging": ["stg_orders"],
      "Marts": ["fct_orders"]
    }
  }
}
```

Group objects can also be explicit:

```json
{
  "groups": [
    {
      "id": "finance",
      "title": "Finance",
      "children": [
        {
          "id": "finance-marts",
          "title": "Marts",
          "members": [
            { "model": "fct_orders", "project": "finance" }
          ]
        }
      ]
    }
  ]
}
```

Explicit group IDs are more stable when group titles change.

### Node Overlays

`nodes` entries augment a dbt node.

- `description` appends visible text to the node.
- `comments` creates child `comment` nodes.
- `media` creates local image attachment nodes.

Media paths must point to local image files inside the visualization folder.

## Validation

The parser validates the overlay before export.

- The overlay must be a JSON object with `version: 1`.
- Unsupported top-level, group, node, comment, media, or reference keys fail the build.
- Every overlay reference must resolve to exactly one included dbt node.
- Ambiguous references fail the build with candidate `unique_id` values.
- Group IDs must be unique and cannot collide with existing graph node IDs.
- Comments and media IDs must be unique under their parent node.
- Media files must exist and stay inside the visualization folder.
- References to excluded dbt resources, including tests when `include_tests` is false, fail as missing references.

## DAG Layout

dbt lineage is a DAG, so dbt diagrams should usually use:

```json
{
  "layout": {
    "algorithm": "dag",
    "direction": "left-right"
  }
}
```

The DAG layout ranks nodes by `lineage` edges, places upstream resources before downstream resources, and preserves saved geometry from `positions.json`. Existing Markdown and CSV diagrams continue to use tree layout unless `layout.algorithm` is set to another value.
