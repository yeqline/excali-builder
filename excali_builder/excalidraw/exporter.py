"""Exporter: Convert Graph to Excalidraw JSON format."""

import json
from typing import Dict, Any, List, Optional
from ..core.graph import Graph
from ..core.edge import ConnectionType
from ..config.schema import GlobalConfig, NodeTypeConfig, LineConnectionConfig
from ..config.loader import ConfigLoader


class ExcalidrawExporter:
    """Exports Graph to Excalidraw JSON format."""

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

            # Get node text from metadata if available
            node_text = node.metadata.get("text", "").strip() if node.metadata else ""
            
            # Calculate text content (title + text if available)
            if node_text:
                full_text = f"{node.label}\n{node_text}"
            else:
                full_text = node.label
            
            # Calculate default size if not set (accounting for multi-line text)
            width = node.width or self._calculate_text_width(full_text, node_config)
            height = node.height or self._calculate_text_height(full_text, node_config)

            x = node.x or 0
            y = node.y or 0

            # Create element based on shape
            if node_config.shape == "ellipse":
                element = self._create_ellipse(
                    x, y, width, height, node, node_config
                )
            elif node_config.shape == "diamond":
                element = self._create_diamond(
                    x, y, width, height, node, node_config
                )
            else:  # rectangle
                element = self._create_rectangle(
                    x, y, width, height, node, node_config
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
            saved_text_x = node.metadata.get("text_x") if node.metadata else None
            saved_text_y = node.metadata.get("text_y") if node.metadata else None
            saved_text_width = node.metadata.get("text_width") if node.metadata else None
            saved_text_height = node.metadata.get("text_height") if node.metadata else None
            text_element = self._create_text(
                x, y, width, height, full_text, node_config, element_id,
                text_align=saved_text_align, vertical_align=saved_vertical_align,
                text_x=saved_text_x, text_y=saved_text_y,
                text_width=saved_text_width, text_height=saved_text_height
            )
            text_element["customData"] = {"node_id": node.id}  # Also store node_id in text for sync
            text_element_id = text_element["id"]
            elements.append(text_element)
            
            # Add reverse binding: add text element to rectangle's boundElements
            # This creates a bidirectional relationship (text has containerId, container has text in boundElements)
            if "boundElements" not in element:
                element["boundElements"] = []
            element["boundElements"].append({"type": "text", "id": text_element_id})

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
        self, x: float, y: float, width: float, height: float, node, node_config: NodeTypeConfig
    ) -> Dict[str, Any]:
        """Create a rectangle element."""
        return {
            "type": "rectangle",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": self._generate_element_id(),
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
        self, x: float, y: float, width: float, height: float, node, node_config: NodeTypeConfig
    ) -> Dict[str, Any]:
        """Create an ellipse element."""
        return {
            "type": "ellipse",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": self._generate_element_id(),
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
        self, x: float, y: float, width: float, height: float, node, node_config: NodeTypeConfig
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
            "id": self._generate_element_id(),
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
    ) -> Dict[str, Any]:
        """Create a text element bound to a container.
        
        When containerId is set, Excalidraw handles positioning based on alignment.
        We only need to provide minimal dimensions and alignment settings.
        """
        # Calculate text dimensions for multi-line text (for width/height estimation)
        lines = text.split("\n")
        line_count = len(lines)
        line_height = node_config.font_size * 1.25
        text_height = line_height * line_count
        
        # Estimate text width (Excalidraw will adjust this)
        max_line_width = max(len(line) for line in lines) if lines else len(text)
        text_width = max(self._calculate_text_width(text, node_config), max_line_width * node_config.font_size * 0.6)
        
        # When containerId is set, Excalidraw recalculates text position/size based on alignment.
        # We should NOT use saved text geometry because it will conflict with Excalidraw's calculation.
        # Instead, use container bounds - Excalidraw will recalculate based on textAlign/verticalAlign.
        # Only use saved geometry if containerId is NOT set (free text elements).
        # For now, always use container bounds when containerId is present (which is always in our case).
        text_x_pos = x
        text_y_pos = y
        text_w = width
        text_h = height
        
        return {
            "type": "text",
            "version": 1,
            "versionNonce": self._generate_nonce(),
            "isDeleted": False,
            "id": self._generate_element_id(),
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
            "fontFamily": node_config.font_family,
            "textAlign": text_align or "center",  # Use saved alignment or default to center
            "verticalAlign": vertical_align or "top",  # Use saved alignment or default to top
            "baseline": line_height,
            "containerId": container_id,  # This tells Excalidraw to position relative to container
            "originalText": text,
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
        # Rough estimate: ~8 pixels per character for Arial 14pt
        char_width = node_config.font_size * 0.6
        return max(100, len(text) * char_width + node_config.padding * 2)

    def _calculate_text_height(self, text: str, node_config: NodeTypeConfig) -> float:
        """Estimate text height for single or multi-line text."""
        # Count lines
        line_count = len(text.split("\n"))
        line_height = node_config.font_size * 1.25
        # Rough estimate: line_height * line_count + padding
        return max(30, line_height * line_count + node_config.padding * 2)

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

