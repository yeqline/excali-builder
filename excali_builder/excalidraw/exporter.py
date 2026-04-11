"""Exporter: Convert Graph to Excalidraw JSON format."""

import hashlib
import json
import textwrap
from typing import Dict, Any, List, Optional, Tuple
from ..core.graph import Graph
from ..core.edge import ConnectionType
from ..config.schema import GlobalConfig, NodeTypeConfig, LineConnectionConfig
from ..config.loader import ConfigLoader


class ExcalidrawExporter:
    """Exports Graph to Excalidraw JSON format."""

    MAX_INITIAL_NODE_WIDTH = 420
    MAX_INITIAL_NODE_HEIGHT = 220
    BOUND_TEXT_VERTICAL_PADDING = 5
    FONT_FAMILY_MAP = {
        "virgil": 1,
        "helvetica": 2,
        "arial": 2,
        "sans": 2,
        "sans-serif": 2,
        "cascadia": 3,
        "cascadia code": 3,
        "monospace": 3,
        "mono": 3,
        "excalidraw": 5,
        "hand-drawn": 5,
        "handdrawn": 5,
    }

    def get_node_body_text(self, node) -> str:
        """Return the body text that should be rendered for a node."""
        if not node.metadata:
            return ""
        return (node.metadata.get("text") or node.metadata.get("content") or "").strip()

    def get_node_full_text(self, node) -> str:
        """Return the display text used for the node's bound text element."""
        node_text = self.get_node_body_text(node)
        if node_text:
            return f"{node.label}\n{node_text}"
        return node.label

    def measure_node(self, node, node_config: NodeTypeConfig) -> Tuple[float, float]:
        """Estimate the node size from the text that will be rendered."""
        full_text = self.get_node_full_text(node)
        return (
            self._calculate_text_width(full_text, node_config),
            self._calculate_text_height(full_text, node_config),
        )

    def export(
        self, graph: Graph, config: GlobalConfig, output_path: str
    ) -> None:
        """Export graph to Excalidraw JSON file."""
        elements: List[Dict[str, Any]] = []

        # Export nodes as rectangles/ellipses with text labels
        node_element_map: Dict[str, str] = {}  # Maps node_id to element_id for binding
        element_index_map: Dict[str, int] = {}  # Maps element_id to index in elements list

        for node in graph.nodes.values():
            node_config = ConfigLoader.get_node_config(config, node.type)
            shape_element_id = self._get_shape_element_id(node.id)
            text_element_id = self._get_text_element_id(node.id)

            original_text = self.get_node_full_text(node)
            
            # Calculate default size if not set (accounting for multi-line text)
            measured_width, measured_height = self.measure_node(node, node_config)
            width = node.width or measured_width
            height = node.height or measured_height
            saved_wrapped_text = (
                node.metadata.get("saved_wrapped_text") if node.metadata else None
            )
            saved_wrapped_original_text = (
                node.metadata.get("saved_wrapped_original_text")
                if node.metadata
                else None
            )
            should_reuse_saved_wrap = (
                isinstance(saved_wrapped_text, str)
                and saved_wrapped_original_text == original_text
            )
            display_text = (
                saved_wrapped_text
                if should_reuse_saved_wrap
                else self._wrap_text_to_width(original_text, node_config, width)
            )

            x = node.x or 0
            y = node.y or 0

            # Create element based on shape
            if node_config.shape == "ellipse":
                element = self._create_ellipse(
                    x, y, width, height, node, node_config, shape_element_id
                )
            elif node_config.shape == "diamond":
                element = self._create_diamond(
                    x, y, width, height, node, node_config, shape_element_id
                )
            else:  # rectangle
                element = self._create_rectangle(
                    x, y, width, height, node, node_config, shape_element_id
                )

            # Store stable node_id in customData for sync
            element["customData"] = {"node_id": node.id}
            element_id = element["id"]
            node_element_map[node.id] = element_id
            element_index_map[element_id] = len(elements)

            elements.append(element)

            # Create text element with title and text (if available)
            # Store text_element_id before creating so we can add it to rectangle's boundElements
            # Get saved text alignment and geometry from node metadata if available
            saved_text_align = node.metadata.get("text_align") if node.metadata else None
            saved_vertical_align = node.metadata.get("vertical_align") if node.metadata else None
            saved_text_x = (
                node.metadata.get("text_x")
                if node.metadata and should_reuse_saved_wrap
                else None
            )
            saved_text_y = (
                node.metadata.get("text_y")
                if node.metadata and should_reuse_saved_wrap
                else None
            )
            saved_text_width = (
                node.metadata.get("text_width")
                if node.metadata and should_reuse_saved_wrap
                else None
            )
            saved_text_height = (
                node.metadata.get("text_height")
                if node.metadata and should_reuse_saved_wrap
                else None
            )
            text_element = self._create_text(
                x, y, width, height, display_text, node_config, element_id,
                text_align=saved_text_align, vertical_align=saved_vertical_align,
                text_x=saved_text_x, text_y=saved_text_y,
                text_width=saved_text_width, text_height=saved_text_height,
                original_text=original_text,
                element_id=text_element_id,
            )
            text_element["customData"] = {"node_id": node.id}  # Also store node_id in text for sync
            text_element_id = text_element["id"]
            elements.append(text_element)
            
            # Add reverse binding: add text element to rectangle's boundElements
            # This creates a bidirectional relationship (text has containerId, container has text in boundElements)
            if "boundElements" not in element:
                element["boundElements"] = []
            element["boundElements"].append({"type": "text", "id": text_element_id})

        for node in graph.nodes.values():
            element_id = node_element_map.get(node.id)
            if not element_id:
                continue

            link_value = self._resolve_node_link(node, node_element_map)
            if link_value:
                elements[element_index_map[element_id]]["link"] = link_value

        # Export line-based edges as arrows
        for edge in graph.edges:
            if edge.connection_type == ConnectionType.LINE:
                line_config = ConfigLoader.get_line_config(config, edge.edge_type)
                source_node = graph.nodes.get(edge.source_id)
                target_node = graph.nodes.get(edge.target_id)

                if source_node and target_node:
                    source_element_id = node_element_map.get(edge.source_id)
                    target_element_id = node_element_map.get(edge.target_id)
                    arrow = self._create_arrow(
                        source_node,
                        target_node,
                        edge,
                        line_config,
                        source_element_id,
                        target_element_id,
                    )
                    arrow_id = arrow["id"]
                    elements.append(arrow)

                    # Add arrow to boundElements of source and target shapes
                    if source_element_id and source_element_id in element_index_map:
                        source_element = elements[element_index_map[source_element_id]]
                        if "boundElements" not in source_element:
                            source_element["boundElements"] = []
                        source_element["boundElements"].append(
                            {"id": arrow_id, "type": "arrow"}
                        )

                    if target_element_id and target_element_id in element_index_map:
                        target_element = elements[element_index_map[target_element_id]]
                        if "boundElements" not in target_element:
                            target_element["boundElements"] = []
                        target_element["boundElements"].append(
                            {"id": arrow_id, "type": "arrow"}
                        )

        # Create groups for container connections
        # Group children with their parent nodes
        for node in graph.nodes.values():
            container_children = graph.get_container_children(node.id)
            if container_children:
                # Create a group ID for this parent and its children
                group_id = self._generate_element_id()
                parent_element_id = node_element_map.get(node.id)
                
                # Add parent to group
                if parent_element_id and parent_element_id in element_index_map:
                    parent_element = elements[element_index_map[parent_element_id]]
                    if "groupIds" not in parent_element:
                        parent_element["groupIds"] = []
                    parent_element["groupIds"].append(group_id)
                    
                    # Also add parent's text to the group
                    for text_elem in elements:
                        if text_elem.get("type") == "text" and text_elem.get("containerId") == parent_element_id:
                            if "groupIds" not in text_elem:
                                text_elem["groupIds"] = []
                            text_elem["groupIds"].append(group_id)
                
                # Add all children to the same group
                for child_node in container_children:
                    child_element_id = node_element_map.get(child_node.id)
                    if child_element_id and child_element_id in element_index_map:
                        child_element = elements[element_index_map[child_element_id]]
                        if "groupIds" not in child_element:
                            child_element["groupIds"] = []
                        child_element["groupIds"].append(group_id)
                        
                        # Also add child's text to the group
                        for text_elem in elements:
                            if text_elem.get("type") == "text" and text_elem.get("containerId") == child_element_id:
                                if "groupIds" not in text_elem:
                                    text_elem["groupIds"] = []
                                text_elem["groupIds"].append(group_id)

        # Create Excalidraw JSON structure
        excalidraw_data = {
            "type": "excalidraw",
            "version": 2,
            "source": "excali-builder",
            "elements": elements,
            "appState": {
                "gridSize": None,
                "viewBackgroundColor": "#ffffff",
            },
            "files": {},
        }

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(excalidraw_data, f, indent=2)

    def _create_rectangle(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        node,
        node_config: NodeTypeConfig,
        element_id: str,
    ) -> Dict[str, Any]:
        """Create a rectangle element."""
        return {
            "type": "rectangle",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": element_id,
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "x": x,
            "y": y,
            "strokeColor": node_config.color,
            "backgroundColor": node_config.backgroundColor,
            "width": width,
            "height": height,
            "seed": self._generate_seed(),
            "groupIds": [],
            "frameId": None,
            "roundness": {"type": 3, "value": node_config.borderRadius},
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
        }

    def _create_ellipse(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        node,
        node_config: NodeTypeConfig,
        element_id: str,
    ) -> Dict[str, Any]:
        """Create an ellipse element."""
        return {
            "type": "ellipse",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": element_id,
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "x": x,
            "y": y,
            "strokeColor": node_config.color,
            "backgroundColor": node_config.backgroundColor,
            "width": width,
            "height": height,
            "seed": self._generate_seed(),
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
        }

    def _create_diamond(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        node,
        node_config: NodeTypeConfig,
        element_id: str,
    ) -> Dict[str, Any]:
        """Create a diamond element using a polygon."""
        center_x = x + width / 2
        center_y = y + height / 2
        # Points relative to x, y (top-left corner)
        points = [
            [width / 2, 0],  # top
            [width, height / 2],  # right
            [width / 2, height],  # bottom
            [0, height / 2],  # left
        ]
        return {
            "type": "diamond",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": element_id,
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "x": x,
            "y": y,
            "strokeColor": node_config.color,
            "backgroundColor": node_config.backgroundColor,
            "width": width,
            "height": height,
            "seed": self._generate_seed(),
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
            "points": points,
        }

    def _create_text(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        text: str,
        node_config: NodeTypeConfig,
        container_id: str,
        text_align: Optional[str] = None,
        vertical_align: Optional[str] = None,
        text_x: Optional[float] = None,
        text_y: Optional[float] = None,
        text_width: Optional[float] = None,
        text_height: Optional[float] = None,
        original_text: Optional[str] = None,
        element_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a text element bound to a container.
        
        When containerId is set, Excalidraw handles positioning based on alignment.
        We only need to provide minimal dimensions and alignment settings.
        """
        # Calculate text dimensions for multi-line text (for width/height estimation)
        lines = text.split("\n")
        line_count = len(lines)
        line_height = node_config.font_size * 1.25
        measured_text_height = line_height * line_count
        
        max_line_width = max(len(line) for line in lines) if lines else len(text)
        available_text_width = max(
            min(width, self.MAX_INITIAL_NODE_WIDTH) - node_config.padding * 2,
            1,
        )
        measured_text_width = max(
            max_line_width * node_config.font_size * 0.6,
            available_text_width,
        )
        text_w = text_width if text_width is not None else measured_text_width
        text_h = text_height if text_height is not None else measured_text_height
        alignment = text_align or "center"
        vertical_alignment = vertical_align or "top"
        text_x_pos = text_x if text_x is not None else self._get_default_text_x(
            x,
            width,
            text_w,
            node_config.padding,
            alignment,
        )
        text_y_pos = text_y if text_y is not None else self._get_default_text_y(
            y,
            height,
            text_h,
            vertical_alignment,
        )
        
        return {
            "type": "text",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": element_id or self._generate_element_id(),
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "x": text_x_pos,  # Use saved text position or container x
            "y": text_y_pos,  # Use saved text position or container y
            "strokeColor": node_config.color,
            "backgroundColor": "transparent",
            "width": text_w,  # Use saved text width or container width
            "height": text_h,  # Use saved text height or container height
            "seed": self._generate_seed(),
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "boundElements": [],  # Text elements don't need boundElements - the container has the reverse binding
            "updated": 1,
            "link": None,
            "locked": False,
            "text": text,
            "fontSize": node_config.font_size,
            "fontFamily": self._get_excalidraw_font_family(node_config.font_family),
            "textAlign": alignment,  # Use saved alignment or default to center
            "verticalAlign": vertical_alignment,  # Use saved alignment or default to top
            "baseline": line_height,
            "containerId": container_id,  # This tells Excalidraw to position relative to container
            "originalText": original_text or text,
            "lineHeight": 1.25,
            "autoResize": True,  # Enable auto-resize for text elements
        }

    def _create_arrow(
        self,
        source_node,
        target_node,
        edge,
        line_config: LineConnectionConfig,
        source_element_id: Optional[str] = None,
        target_element_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an arrow/line element connecting two nodes."""
        # Calculate shape centers
        source_center_x = (source_node.x or 0) + (source_node.width or 100) / 2
        source_center_y = (source_node.y or 0) + (source_node.height or 50) / 2
        target_center_x = (target_node.x or 0) + (target_node.width or 100) / 2
        target_center_y = (target_node.y or 0) + (target_node.height or 50) / 2

        # Calculate direction vector
        dx = target_center_x - source_center_x
        dy = target_center_y - source_center_y
        distance = (dx**2 + dy**2) ** 0.5
        if distance == 0:
            distance = 1

        # Normalize direction
        dx_norm = dx / distance
        dy_norm = dy / distance

        # Calculate edge connection points (on the shape boundaries)
        # Use proper rectangle-line intersection algorithm
        source_half_width = (source_node.width or 100) / 2
        source_half_height = (source_node.height or 50) / 2
        target_half_width = (target_node.width or 100) / 2
        target_half_height = (target_node.height or 50) / 2

        # Calculate intersection with source rectangle edge
        # Find which edge the line from center hits first
        if abs(dx_norm) < 1e-10:
            # Vertical line (or nearly vertical)
            source_edge_x = source_center_x
            source_edge_y = source_center_y + (source_half_height if dy_norm > 0 else -source_half_height)
        elif abs(dy_norm) < 1e-10:
            # Horizontal line (or nearly horizontal)
            # Exit from the side facing the target
            source_edge_x = source_center_x + (source_half_width if dx_norm > 0 else -source_half_width)
            source_edge_y = source_center_y
        else:
            # Diagonal line - find which edge we hit first
            t_x = source_half_width / abs(dx_norm)
            t_y = source_half_height / abs(dy_norm)
            t = min(t_x, t_y)
            source_edge_x = source_center_x + dx_norm * t
            source_edge_y = source_center_y + dy_norm * t

        # Calculate intersection with target rectangle edge (from opposite direction)
        if abs(dx_norm) < 1e-10:
            # Vertical line (or nearly vertical)
            target_edge_x = target_center_x
            target_edge_y = target_center_y + (-target_half_height if dy_norm > 0 else target_half_height)
        elif abs(dy_norm) < 1e-10:
            # Horizontal line (or nearly horizontal)
            # Enter from the side facing the source
            target_edge_x = target_center_x + (-target_half_width if dx_norm > 0 else target_half_width)
            target_edge_y = target_center_y
        else:
            # Diagonal line - find which edge we hit first
            t_x = target_half_width / abs(dx_norm)
            t_y = target_half_height / abs(dy_norm)
            t = min(t_x, t_y)
            target_edge_x = target_center_x - dx_norm * t
            target_edge_y = target_center_y - dy_norm * t

        # Arrow starts at source edge, ends at target edge
        source_x = source_edge_x
        source_y = source_edge_y
        target_x = target_edge_x
        target_y = target_edge_y

        # Ensure minimum arrow length (if nodes are touching or very close)
        arrow_length = ((target_x - source_x) ** 2 + (target_y - source_y) ** 2) ** 0.5
        min_length = 10  # Minimum visible arrow length
        if arrow_length < min_length:
            # If arrows are too short, extend them slightly
            if abs(dx_norm) > abs(dy_norm):
                # More horizontal - extend horizontally
                if dx_norm > 0:
                    source_x -= min_length / 2
                    target_x += min_length / 2
                else:
                    source_x += min_length / 2
                    target_x -= min_length / 2
            else:
                # More vertical - extend vertically
                if dy_norm > 0:
                    source_y -= min_length / 2
                    target_y += min_length / 2
                else:
                    source_y += min_length / 2
                    target_y -= min_length / 2

        # Map stroke style
        stroke_style_map = {
            "solid": "solid",
            "dashed": "dashed",
            "dotted": "dotted",
        }
        stroke_style = stroke_style_map.get(line_config.stroke_style, "solid")

        # Create bindings if element IDs are available
        start_binding = (
            {"elementId": source_element_id, "focus": 0, "gap": 1}
            if source_element_id
            else None
        )
        end_binding = (
            {"elementId": target_element_id, "focus": 0, "gap": 1}
            if target_element_id
            else None
        )

        arrow = {
            "type": "arrow",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": self._generate_element_id(),
            "fillStyle": "solid",
            "strokeWidth": line_config.stroke_width,
            "strokeStyle": stroke_style,
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "x": source_x,
            "y": source_y,
            "strokeColor": line_config.color,
            "backgroundColor": "transparent",
            "seed": self._generate_seed(),
            "groupIds": [],
            "frameId": None,
            "roundness": {"type": 2},
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
            "points": [[0, 0], [target_x - source_x, target_y - source_y]],
            "lastCommittedPoint": None,
            "startBinding": start_binding,
            "endBinding": end_binding,
            "startArrowhead": line_config.arrow_start,  # Can be None, "arrow", "circle", etc.
            "endArrowhead": line_config.arrow_end,  # Can be None, "arrow", "circle", etc.
        }

        return arrow

    def _calculate_text_width(self, text: str, node_config: NodeTypeConfig) -> float:
        """Estimate text width (rough approximation)."""
        lines = self._wrap_text_to_max_width(text, node_config)
        longest_line = max((len(line) for line in lines), default=0)
        char_width = node_config.font_size * 0.6
        return min(
            self.MAX_INITIAL_NODE_WIDTH,
            max(100, longest_line * char_width + node_config.padding * 2),
        )

    def _calculate_text_height(self, text: str, node_config: NodeTypeConfig) -> float:
        """Estimate text height for single or multi-line text."""
        line_count = len(self._wrap_text_to_max_width(text, node_config))
        line_height = node_config.font_size * 1.25
        return min(
            self.MAX_INITIAL_NODE_HEIGHT,
            max(30, line_height * line_count + node_config.padding * 2),
        )

    def _wrap_text_to_max_width(self, text: str, node_config: NodeTypeConfig) -> List[str]:
        """Approximate wrapped lines using the initial max node width."""
        return self._wrap_text_to_width(
            text,
            node_config,
            self.MAX_INITIAL_NODE_WIDTH,
        ).split("\n")

    def _wrap_text_to_width(
        self,
        text: str,
        node_config: NodeTypeConfig,
        max_width: float,
    ) -> str:
        """Approximate wrapped text for a target container width."""
        char_width = max(node_config.font_size * 0.6, 1)
        available_width = max(max_width - node_config.padding * 2, char_width)
        max_chars_per_line = max(1, int(available_width // char_width))

        wrapped_lines: List[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                wrapped_lines.append("")
                continue
            wrapped_lines.extend(
                textwrap.wrap(
                    stripped,
                    width=max_chars_per_line,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
                or [stripped]
            )

        return "\n".join(wrapped_lines or [""])

    def _get_default_text_x(
        self,
        x: float,
        width: float,
        text_width: float,
        padding: float,
        alignment: str,
    ) -> float:
        """Return the default bound-text x position for a fresh export."""
        if alignment == "left":
            return x + padding
        if alignment == "right":
            return x + max(width - padding - text_width, 0)
        return x + max((width - text_width) / 2, 0)

    def _get_default_text_y(
        self,
        y: float,
        height: float,
        text_height: float,
        vertical_alignment: str,
    ) -> float:
        """Return the default bound-text y position for a fresh export."""
        available_space = max(height - text_height, 0)
        if vertical_alignment == "bottom":
            return y + max(available_space - self.BOUND_TEXT_VERTICAL_PADDING, 0)
        if vertical_alignment == "middle":
            return y + available_space / 2
        return y + min(self.BOUND_TEXT_VERTICAL_PADDING, available_space)

    def _resolve_node_link(
        self,
        node,
        node_element_map: Dict[str, str],
    ) -> Optional[str]:
        """Resolve a built-in link node target to an Excalidraw link string."""
        if node.type != "link" or not node.metadata:
            return None

        target = (node.metadata.get("target") or "").strip()
        if not target:
            return None

        if target.startswith("#"):
            target_node_id = target[1:]
            target_element_id = node_element_map.get(target_node_id)
            if not target_element_id:
                return None
            return f"https://excalidraw.com/?element={target_element_id}"

        return target

    def _get_excalidraw_font_family(self, font_family: Any) -> int:
        """Map a user-friendly font name to Excalidraw's numeric font family."""
        if isinstance(font_family, int):
            return font_family

        normalized = str(font_family or "").strip().lower()
        return self.FONT_FAMILY_MAP.get(normalized, 2)

    def _get_shape_element_id(self, node_id: str) -> str:
        """Return a deterministic shape element ID for a node."""
        return f"node-{self._stable_id_suffix(node_id)}"

    def _get_text_element_id(self, node_id: str) -> str:
        """Return a deterministic text element ID for a node."""
        return f"text-{self._stable_id_suffix(node_id)}"

    def _stable_id_suffix(self, value: str) -> str:
        """Create a short deterministic suffix for Excalidraw element IDs."""
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]

    def _generate_nonce(self) -> int:
        """Generate a random nonce."""
        import random
        return random.randint(1000000000, 9999999999)

    def _generate_element_id(self) -> str:
        """Generate a random element ID."""
        import random
        import string
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    def _generate_seed(self) -> int:
        """Generate a random seed."""
        import random
        return random.randint(1, 1000000)
