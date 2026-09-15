"""Translate the neutral layout contract to the optional local ELK runtime."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from .base import Box, LayoutEngine, LayoutRequest, LayoutResult, Route

RUNTIME = Path(__file__).parent / "runtime"


class ElkEngine(LayoutEngine):
    def layout(self, request: LayoutRequest) -> LayoutResult:
        node = shutil.which("node")
        if not node or not (RUNTIME / "node_modules/elkjs/lib/elk.bundled.js").exists():
            raise RuntimeError(
                "The ELK engine needs Node.js and its optional local dependency. "
                f"Install Node.js, then run: npm ci --prefix '{RUNTIME}' --ignore-scripts"
            )
        try:
            completed = subprocess.run(
                [node, str(RUNTIME / "elk.cjs")],
                input=json.dumps(self._to_elk(request)),
                text=True,
                capture_output=True,
                timeout=request.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("ELK layout exceeded the configured time budget") from exc
        if completed.returncode:
            raise RuntimeError(f"ELK layout failed: {completed.stderr.strip()[:1500]}")
        return self._from_elk(json.loads(completed.stdout))

    def _to_elk(self, request: LayoutRequest) -> Dict[str, Any]:
        directions = {
            "left-right": "RIGHT",
            "right-left": "LEFT",
            "top-down": "DOWN",
            "bottom-up": "UP",
        }
        root = {
            "id": "__layout_root__",
            "layoutOptions": {
                "elk.algorithm": "layered",
                "elk.direction": directions.get(request.direction, "RIGHT"),
                "elk.edgeRouting": "ORTHOGONAL",
                "elk.hierarchyHandling": "INCLUDE_CHILDREN",
                "elk.randomSeed": str(request.seed),
                "elk.spacing.nodeNode": str(request.node_spacing),
                "elk.layered.spacing.nodeNodeBetweenLayers": str(request.layer_spacing),
                "elk.spacing.edgeEdge": str(request.wire_spacing),
                "elk.layered.spacing.edgeEdgeBetweenLayers": str(request.wire_spacing),
                "elk.spacing.edgeNode": str(request.wire_spacing),
                "elk.spacing.portPort": str(request.port_spacing),
                "elk.layered.spacing.edgeNodeBetweenLayers": str(request.wire_spacing),
                "elk.layered.mergeEdges": "false",
                "elk.layered.mergeHierarchyEdges": "false",
                "elk.layered.thoroughness": "12",
                "elk.layered.crossingMinimization.greedySwitch.type": "TWO_SIDED",
                "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
                "elk.padding": f"[top={request.padding},left={request.padding},"
                f"bottom={request.padding},right={request.padding}]",
                **{key: str(value) for key, value in request.engine_options.items()},
            },
            "children": [],
            "edges": [],
        }
        specs = {n.id: n for n in request.nodes}
        objects = {}
        for n in request.nodes:
            obj = {"id": n.id, "width": n.width, "height": n.height}
            if n.is_port:
                side = n.side or "WEST"
                depth = n.width if side in {"WEST", "EAST"} else n.height
                obj["layoutOptions"] = {
                    "elk.port.side": side,
                    "elk.port.borderOffset": str(-depth - request.padding),
                }
                siblings = [p for p in request.nodes if p.parent_id == n.parent_id and p.is_port]
                if any(p.order is not None for p in siblings):
                    index = (
                        n.order if n.order is not None else len(request.nodes) + siblings.index(n)
                    )
                    obj["layoutOptions"]["elk.port.index"] = str(
                        2 * len(request.nodes) - index if side == "WEST" else index
                    )
            else:
                ports = [p for p in request.nodes if p.parent_id == n.id and p.is_port]
                obj.update({"children": [], "ports": []})
                obj["layoutOptions"] = {
                    "elk.portConstraints": "FIXED_ORDER"
                    if any(p.order is not None for p in ports)
                    else "FIXED_SIDE",
                    "elk.nodeSize.constraints": "[]" if n.size_locked else "[PORTS,MINIMUM_SIZE]",
                    "elk.nodeSize.minimum": f"({n.width},{n.height})",
                    "elk.spacing.portPort": str(request.port_spacing),
                    "elk.spacing.individual": f"spacing.portPort:{request.port_spacing};,;"
                    f"spacing.portsSurrounding:[top={n.header_height + request.padding},"
                    f"left={request.padding},bottom={request.padding},right={request.padding}]",
                    "elk.padding": (
                        f"[top={n.header_height + request.padding},left={request.padding},"
                        f"bottom={request.padding},right={request.padding}]"
                    ),
                }
            objects[n.id] = obj
        for n in request.nodes:
            parent = objects.get(n.parent_id, root)
            parent.setdefault("ports" if n.is_port else "children", []).append(objects[n.id])

        def ancestors(node_id):
            result = []
            parent = specs[node_id].parent_id
            # Ports and children share the enclosing node as their coordinate system.
            while parent:
                result.append(parent)
                parent = specs[parent].parent_id
            return result

        for edge in request.edges:
            obj = {
                "id": edge.id,
                "sources": [edge.source],
                "targets": [edge.target],
                "layoutOptions": {
                    "elk.layered.priority.direction": "10" if edge.role == "flow" else "0",
                },
            }
            if edge.label_width:
                obj["labels"] = [
                    {
                        "id": edge.id + ".label",
                        "text": " ",
                        "width": edge.label_width,
                        "height": edge.label_height,
                        "layoutOptions": {"elk.edgeLabels.placement": "CENTER"},
                    }
                ]
            source_ancestors = ancestors(edge.source)
            target_ancestors = set(ancestors(edge.target))
            owner = next((p for p in source_ancestors if p in target_ancestors), None)
            objects.get(owner, root).setdefault("edges", []).append(obj)
        return root

    def _from_elk(self, root: Dict[str, Any]) -> LayoutResult:
        result = LayoutResult({}, {})
        offsets = {}
        edges = []

        def visit(obj, offset_x, offset_y, is_root=False):
            x, y = offset_x + obj.get("x", 0), offset_y + obj.get("y", 0)
            offsets[obj["id"]] = (x, y)
            if not is_root:
                result.boxes[obj["id"]] = Box(x, y, obj["width"], obj["height"])
            for port in obj.get("ports", []):
                result.boxes[port["id"]] = Box(
                    x + port["x"],
                    y + port["y"],
                    port["width"],
                    port["height"],
                )
                result.port_sides[port["id"]] = port["layoutOptions"]["elk.port.side"]
            for child in obj.get("children", []):
                visit(child, x, y)
            for edge in obj.get("edges", []):
                edges.append((edge, obj["id"]))

        visit(root, 0, 0, True)
        for edge, owner in edges:
            x, y = offsets[edge.get("container", owner)]
            sections = edge.get("sections", [])
            if len(sections) != 1:
                raise ValueError(f"ELK returned an unsupported route for {edge['id']}")
            section = sections[0]
            points = [section["startPoint"], *section.get("bendPoints", []), section["endPoint"]]
            labels = edge.get("labels", [])
            label = labels[0] if labels else None
            result.routes[edge["id"]] = Route(
                [(x + p["x"], y + p["y"]) for p in points],
                Box(x + label["x"], y + label["y"], label["width"], label["height"])
                if label
                else None,
            )
        return result
