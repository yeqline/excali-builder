# Shared motor and driver port arrangements

This CSV diagram contains two identical motors and two identical drivers. Each
part template defines encoder and phase roles. The optimizer chooses their
shared sides and vertical order using the full diagram's readability score.
All instances of a template retain identical internal geometry.

Install the [local layout runtime](../../docs/wiring-layout-guide.md), then run
from the repository root:

```sh
uv run excali-builder optimize examples/shared-parts-diagram --engine hybrid
uv run excali-builder serve examples/shared-parts-diagram
```

The viewer also offers `elk`. Both engines use the same template constraints.
The chosen arrangements appear in `wiring-layout.json` under
`result.metrics.part_templates` and survive cached rebuilds. Explicit
optimization searches the arrangements again.

`node.csv` declares part identities with `model_number`; existing port titles
identify matching connectors. The optimizer discovers templates and instances automatically.
`edge.csv` defines containment and connections, and `edge_config.json` assigns
connection styles. To add an instance, add its nodes with the same model number
and port titles, and its containment edges. No instance mapping belongs in config.
Optional `layout.wiring.part_templates` constraints are keyed by `model_number`:
add role-based `port_sides` or `port_order`, or use `optimize: false` to retain
the initial shared arrangement.
