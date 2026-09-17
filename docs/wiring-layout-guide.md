# Wiring layout

The `wiring` layout arranges devices, their contained ports, and routed connections together. Straight connections are the default. It compares deterministic candidates using the routes that will actually be rendered: box obstructions, label collisions, wire crossings, shared segments, aspect ratio, bends, and wire length. It is a readability heuristic, not a guarantee of a globally optimal drawing.

## Install the optional layout runtime

Install Node.js, then run this from the repository root:

```sh
npm ci --prefix excali_builder/layout/engines/runtime --ignore-scripts
```

Python package installations also include the runtime manifest and runner. Find that installation's runtime directory with:

```sh
python -c 'from excali_builder.layout.engines.elk import RUNTIME; print(RUNTIME)'
```

Run `npm ci --prefix <runtime-directory> --ignore-scripts` there. The dependency is pinned in `package-lock.json`. Layout runs locally; it requires no external layout service. The built-in `elk`, `hybrid`, and `crossing` wiring engines use this runtime. Other layouts do not require Node.js or ELK.

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
      "edge_routing": "straight",
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

The built-in `elk` engine provides ELK's layered placement. The `hybrid` engine
uses the same compound, port-aware ELK seed and then searches port-side and
device-order alternatives with a crossing-aware sifting pass. It is intended
for straight routing, where reducing wire crossings is the primary objective.
Select an engine in the viewer or pass `--engine elk` / `--engine hybrid` to
the CLI. To let the hybrid adapter try more independent ELK seeds, set
`layout.wiring.engine_options.hybrid_candidates` (from 1 to 8); the normal
`wiring.candidates` setting still controls the common outer candidate search.

The `crossing` engine searches device positions in both axes and can replace a
small number of costly wires with paired reference tags. It requires straight
routing. Select `crossing` in the viewer or run:

```sh
excali-builder optimize <diagram-folder> --engine crossing
```

It starts from port-aware ELK placement, then tries translations and exchanges
of entire device subtrees. Every port and nested device moves with its owner;
fixed sizes, terminal constraints, and shared model arrangements remain in
effect. Shrinking search steps refine the placement. The common pipeline also
searches shared port arrangements across all instances of each model.

For each placement, the reference selector scores how many remaining crossings
and obstructions each wire causes. It tries the highest-benefit wires first,
places a pair of reference tags, and accepts a replacement only when the
rendered drawing improves. It recalculates marginal conflicts after each
replacement, then can refine device placement with those references in place.
This is a bounded local-search heuristic, not an exact crossing-number or
minimum-vertex-cover solver. It uses ELK for its compound seed rather than a
point-only force layout. The direction setting guides that seed; final devices
are not restricted to layers.

Configure the engine under `layout.wiring.engine_options`:

```json
{
  "crossing_max_connectors": 3,
  "crossing_max_connectors_per_node": 2,
  "crossing_passes": 6,
  "crossing_protected_edges": [],
  "crossing_edge_costs": {}
}
```

These are the defaults. `crossing_max_connectors` counts replaced **connections**,
each represented by two tags; it is a ceiling, not a target. Set it to `0` to
optimize placement while keeping every wire drawn in full. The per-node limit
applies to electrical endpoints (usually ports). `crossing_passes` bounds the
initial movement passes; after references are selected, up to half as many
additional passes refine the result. Set it to `0` to use the seed positions
with reference selection only. The common `timeout_seconds` budget and
`candidates` settings also apply. Large drawings prioritize the devices with
the most conflicts and limit reference-placement trials per selection step;
they can finish with unresolved crossings.

Use original wire IDs in `crossing_protected_edges` to require complete lines.
`crossing_edge_costs` maps wire IDs to positive costs (default `1`); larger costs
discourage replacing important connections. CSV builds record their stable
wire IDs as keys under `result.routes` in `wiring-layout.json`. Unknown IDs and
invalid option values are rejected. The score charges 10 per crossing, 20 per
obstruction or label collision, one per eight units of unrelated shared wire,
and three times the cost of each replaced connection. Remaining ties prefer
fewer references, a less extreme aspect ratio, and shorter visible wires.

Each tag names the remote device/port hierarchy and unique node ID, includes
the visible wire label, and links to the remote port. Use the tag's link action
in the local viewer to jump there. Wire color, stroke style, original endpoint
arrowheads, and original edge identity are retained on the two short leaders.
Tags are placed outside device boxes, with leaders checked against unrelated
nodes and device headings. A wire stays complete when suitable tags cannot fit.
Tags and leaders participate in quality scoring; the hidden span does not.

References are stored in `wiring-layout.json`, not in source CSVs or as extra
source nodes. Ordinary layout saves keep device positions and the selected
reference connections, refreshing affected leaders and tags. Optimize searches
for a new selection; source or configuration changes also reconsider references
against the current geometry and budget. Tag geometry is generated; manual tag
moves are not saved as independent nodes. Selecting another engine or setting the
budget to zero restores full lines. Optimize/restore includes the paired
references along with the rest of the layout.

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

### Shared arrangements for identical parts

Declare model numbers in `node.csv`. No instance lists
or role-to-node mappings are needed in configuration:

```csv
node_id,node_type,node_title,node_text,model_number
motor_x,motor,X motor,Closed-loop stepper,23HS40-5004D-E1K-1M5
motor_x_encoder,port,ENCODER,Encoder lead,
motor_x_phase,port,A+ A- B+ B-,Motor conductors,
motor_y1,motor,Y1 motor,Closed-loop stepper,23HS40-5004D-E1K-1M5
motor_y1_encoder,port,ENCODER,Encoder lead,
motor_y1_phase,port,A+ A- B+ B-,Motor conductors,
```

`node_id` identifies an instance; `model_number` identifies its physical part.
Corresponding ports are matched by their existing `node_title` values, with
whitespace normalized. Port titles must be unique within a device and match
across all instances of a model; they are case-sensitive. Device titles and
port body text can differ. Containment remains defined by enclosing-group
edges in `edge.csv`. Other source parsers can supply `model_number` in node
metadata and matching port labels. Legacy CSVs without this optional column
remain valid and do not implicitly group devices by node type, title,
descriptive text, or ID suffix.

Templates and instances are discovered automatically from this source data.
Optimization is enabled by default. The common pipeline explores a
shared bank assignment and vertical order, scoring all instances' connections
on the full drawing. It selects the best arrangement found within the time
budget and applies it to every instance. Parts with up to three roles enumerate
all bank/order arrangements for a given device placement; larger parts use
shared port sifting and side switches. Multiple templates are refined together,
and successive placement candidates use the winning arrangements as seeds.
This is a heuristic search, not a guarantee of the global minimum.

Corresponding ports share dimensions and exact offsets from their device's
top-left corner. Device dimensions and heading clearance are standardized to
fit every instance's labels and any candidate bank arrangement. The engine can
move each whole device, but cannot mirror or reorder an individual instance.
The selected arrangements are stored in `wiring-layout.json` under
`result.metrics.part_templates`. Cached rebuilds and new instances reuse them;
an explicit optimization searches again. Moving a port independently is
corrected to its template position on rebuild.

For optional hard restrictions, use `layout.wiring.part_templates`, keyed by
the source `model_number`, with port-title-based `port_sides` and/or `port_order`.
For example, `"part_templates": {"23HS40-5004D-E1K-1M5":
{"port_sides": {"ENCODER": "WEST", "A+ A- B+ B-": "WEST"}}}`
allows optimization of their shared order while keeping both in the west bank.
Set `"optimize": false` to retain the initial shared sides and order; use
`port_order` to specify an explicit order. Per-instance side/order constraints must be compatible
with the whole template. Conflicting fixed dimensions are rejected. Each
identified instance must have unique titles on its contained ports, and all
instances of a model must expose the same port titles. Empty titles, duplicate
titles, and mismatched variants fail with a source-data error. Templates
currently describe containers containing only ports.

These rules apply to all engines selected by `layout.engine`, including `elk`,
`hybrid`, `crossing`, and registered adapters, on the `wiring` pipeline. The independent
tree, DAG, and free-form layouts do not perform compound port optimization.
See [the shared-parts example](../examples/shared-parts-diagram/README.md) for
a runnable diagram.

Wire labels wrap at `label_max_width`. `edge_routing: "straight"` draws each complete connection as one segment and scores layout candidates using those same segments. Reference connections use two short straight leaders and paired tags instead. This favors a visually simple connection model, but a dense or tightly constrained diagram can still force a straight connection across another node. The optimizer reports those cases as obstructions and prefers candidates with fewer of them.

Set `edge_routing: "orthogonal"` when avoiding unrelated devices and ports is more important than minimizing bends. Orthogonal mode routes around obstacles and preserves manually edited right-angle bends. A common segment is distinguished in the quality report from an overlap between wires that do not share a terminal. No electrical nets are inferred from colors or edge type names.

`positions.json` stores editable node geometry. `wiring-layout.json` stores engine-neutral routes, label rectangles, port sides, and quality measurements. Normal rebuilds reuse unaffected routes; moving a device reroutes affected connections without running a global placement. Keep both files when sharing a diagram whose layout must survive rebuilds.

## Use another engine

`layout.algorithm: "wiring"` selects the common wiring pipeline. `layout.engine` selects its placement adapter. The exporter, CLI, viewer, saved geometry, and scoring do not consume ELK JSON.

Implement `LayoutEngine.layout(request) -> LayoutResult` from `excali_builder.layout.engines.base`. The neutral request describes nodes, containment, port sizes/sides/order, edge endpoints and label dimensions, the requested routing mode, spacing, direction, a deterministic seed, and a timeout. The result contains:

- `boxes`: absolute scene coordinates for every requested node, including ports;
- `routes`: source-to-target absolute polylines and optional label rectangles, keyed by the original edge IDs;
- `port_sides`: the chosen side for each port.

The common validator checks IDs, finite geometry, containment, overlaps, endpoint attachment, fixed sizes/sides/orders, and shared part geometry. The common pipeline handles candidate generation, collective template search, route scoring, label placement, persistence, and updates around fixed user geometry. Requests include semantic template groups and relative port positions; ELK uses fixed port positions, and the common pipeline restores template internals for adapters before rerouting and scoring. The adapter must respect its timeout and must not modify source data or write diagram files.

Routes may also carry a `connectors` pair for straight reference connections.
The pair is ordered source then target; each leader runs outward from its local
endpoint to its tag. The logical `points` span remains source-to-target, and
each connector records its remote `target`. Use `route_segments(route)` to
inspect the visible lines. The common validator checks both references and
their attachments, and the exporter preserves the original source/target
arrowhead directions when rendering the leaders.

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

Run `python -m unittest discover -s tests`. Tests cover an independent replacement engine, initial layout, cached rebuilds, movement routing, nested containment, port constraints, optimization rollback, restoration, and rejection of stale viewer saves. Crossing-engine tests also cover movement, reference budgets, protected wires, visible scoring, reference export and persistence, engine switching, and shared part geometry. ELK-backed integration tests run when the optional local runtime is installed.
