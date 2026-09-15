# Wiring layout

The `wiring` layout arranges devices, their contained ports, and routed connections together. It compares deterministic candidates using box obstructions, label collisions, wire crossings, shared segments, aspect ratio, bends, and wire length. It is a readability heuristic, not a guarantee of a globally optimal drawing.

## Install the optional ELK engine

Install Node.js, then run this from the repository root:

```sh
npm ci --prefix excali_builder/layout/engines/runtime --ignore-scripts
```

Python package installations also include the runtime manifest and runner. Find that installation's runtime directory with:

```sh
python -c 'from excali_builder.layout.engines.elk import RUNTIME; print(RUNTIME)'
```

Run `npm ci --prefix <runtime-directory> --ignore-scripts` there. The dependency is pinned in `package-lock.json`. Layout runs locally; it requires no external layout service. Other layouts do not require Node.js or ELK.

## Initial layout and manual optimization

For an initial wiring layout, set these fields in the diagram's `config.json`:

```json
{
  "parser_type": "csv",
  "layout": {
    "algorithm": "wiring",
    "engine": "elk",
    "direction": "left-right",
    "level_spacing": 160,
    "wiring": {
      "candidates": 4,
      "timeout_seconds": 40,
      "node_spacing": 90,
      "wire_spacing": 18,
      "port_spacing": 16,
      "padding": 24,
      "label_max_width": 220,
      "edge_roles": {
        "annotation": "annotation",
        "earth": "distribution",
        "neutral": "distribution",
        "dc_return": "distribution"
      }
    }
  }
}
```

Use your diagram's edge type names in `edge_roles`. Undeclared types default to `flow`. Distribution relationships remain visible and preserve their endpoints; their directions have less influence on reading order. Annotation edges also remain visible. Neither `from`/`to` nor an orientation used while searching for a compact layout changes the exported electrical connections or arrowheads.

Build normally with `excali-builder <diagram-folder>`. Existing positions remain authoritative on subsequent builds. New devices are placed near their neighbors in free space. New nested devices and other non-port content keep an interior position inside their owner. New ports use the west/east banks inside their owner, expanding it when possible. When a fixed size or surrounding devices prevent that expansion, the build reports that a full optimization is needed rather than overlapping existing devices.

The viewer's **Optimize wiring layout** control is shown for CSV diagrams and for diagrams already using `layout.algorithm: "wiring"`. Other parsers keep their existing layout unless that algorithm is already selected.

To rearrange an existing diagram, use the viewer's **Optimize wiring layout** button or:

```sh
excali-builder optimize <diagram-folder> --engine elk
```

Optimization updates `config.json` to select the wiring layout and chosen engine. It computes the result in a temporary copy before publishing it. Device containers can shrink or grow to fit their ports and headings; ordinary saved node sizes are retained. Containers render as rectangles so their bounds match the routing obstacles. All node and wire IDs, source text, colors, and electrical endpoints are retained.

Restore the preceding layout with the viewer's **Restore previous layout** button or:

```sh
excali-builder restore-layout <diagram-folder>
```

One preceding layout is saved in `layout-backup.json`, including the previous layout configuration. Restoration is refused if the source graph or source configuration has changed in the meantime. A failed optimization leaves the existing diagram intact.

## Ports and dimensions

Containment comes from edges configured as `connection_type: "enclosing_group"`. Leaf nodes with a type listed in `layout.wiring.port_types` (default `["port"]`) are treated as ports. Other contained nodes remain nested devices or ordinary content. A node can have only one enclosing parent, and containment must be acyclic.

Port boxes are arranged in west/east banks inside their device, with the complete device heading above them. The optimizer chooses sides and orders using connectivity, then tries refinements that face connected neighbors. Explicit side and order constraints are useful when the drawing must preserve a connector's terminal sequence:

```json
{
  "port_sides": {"controller_in": "WEST", "controller_out": "EAST"},
  "port_order": {"controller": ["controller_in", "controller_out"]},
  "fixed_sizes": {"controller": [600, 400]}
}
```

These fields belong under `layout.wiring`. `port_order` is a top-to-bottom order within each side; unlisted ports follow the listed ports. `fixed_sizes` contains exact `[width, height]` pairs. Constraints that cannot contain the ports are rejected. Explicit port sides currently support `WEST` and `EAST`; the overall diagram direction can also be vertical.

Wire labels wrap at `label_max_width`. Orthogonal routes avoid unrelated devices and ports. A common segment is distinguished in the quality report from an overlap between wires that do not share a terminal. No electrical nets are inferred from colors or edge type names.

`positions.json` stores editable node geometry. `wiring-layout.json` stores engine-neutral routes, label rectangles, port sides, and quality measurements. Normal rebuilds reuse unaffected routes; moving a device reroutes affected connections without running a global placement. Keep both files when sharing a diagram whose layout must survive rebuilds.

## Use another engine

`layout.algorithm: "wiring"` selects the common wiring pipeline. `layout.engine` selects its placement adapter. The exporter, CLI, viewer, saved geometry, and scoring do not consume ELK JSON.

Implement `LayoutEngine.layout(request) -> LayoutResult` from `excali_builder.layout.engines.base`. The neutral request describes nodes, containment, port sizes/sides/order, edge endpoints and label dimensions, spacing, direction, a deterministic seed, and a timeout. The result contains:

- `boxes`: absolute scene coordinates for every requested node, including ports;
- `routes`: source-to-target absolute polylines and optional label rectangles, keyed by the original edge IDs;
- `port_sides`: the chosen side for each port.

The common validator checks IDs, finite geometry, containment, overlaps, endpoint attachment, and fixed sizes/sides. The common pipeline handles candidate generation, route scoring, label placement, persistence, and updates around fixed user geometry. The adapter must respect its timeout and must not modify source data or write diagram files.

Register a factory in a Python application:

```python
from excali_builder.layout.engines import register_engine
from my_layout_package import MyEngine

register_engine("my-engine", MyEngine)
```

For discovery by the standalone CLI and viewer, publish a Python entry point:

```toml
[project.entry-points."excali_builder.layout_engines"]
my-engine = "my_layout_package:MyEngine"
```

Once installed in the same Python environment, the engine appears in the viewer's selector and accepts `excali-builder optimize <diagram-folder> --engine my-engine`. No changes to the builder, exporter, CLI, or viewer are needed.

Adapter-specific settings can be passed through `layout.wiring.engine_options`. Only the adapter interprets them. ELK accepts its documented option identifiers there; the common wiring rules do not depend on those identifiers.

## Validation

Run `python -m unittest discover -s tests`. Tests cover an independent replacement engine, initial layout, cached rebuilds, movement routing, nested containment, port constraints, optimization rollback, restoration, and rejection of stale viewer saves. ELK-specific integration tests run when its optional local runtime is installed.
