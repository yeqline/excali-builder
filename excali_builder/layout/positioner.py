"""Positioner for container-based node placement with edge_config.json settings."""

import math
from typing import Dict, List, Optional, Tuple
from ..core.graph import Graph
from ..core.node import Node
from ..core.edge import Edge, ConnectionType
from ..config.schema import ContainerConnectionConfig


class Positioner:
    """Handles container-based positioning using edge_config.json settings."""

    def __init__(self, config: Dict[str, ContainerConnectionConfig]):
        """Initialize with container connection configurations."""
        self.config = config

    def position_container_children(
        self, graph: Graph, parent: Node, edge_type: str = "container", parent_node_config = None
    ) -> None:
        """Position children of a container node based on edge_config settings.
        
        Args:
            graph: The graph containing nodes and edges
            parent: The parent container node
            edge_type: The edge type for container connection
            parent_node_config: Optional node config for the parent (for text height calculation)
        """
        children = graph.get_container_children(parent.id)
        if not children:
            return

        # Get configuration for this edge type
        container_config = self.config.get(edge_type, ContainerConnectionConfig())

        placement = container_config.placement
        direction = container_config.direction
        child_offset = container_config.child_offset
        group_padding = container_config.group_padding

        parent_x = parent.x or 0
        parent_y = parent.y or 0
        parent_width = parent.width or 100
        parent_height = parent.height or 50

        if placement == "inside":
            # For inside placement, always recalculate parent size and children positions
            # regardless of saved positions, to ensure proper alignment and sizing
            
            # Calculate required parent size and always use it (override saved size)
            required_width, required_height = self._calculate_required_parent_size(
                children, direction, group_padding, parent, parent_node_config
            )
            parent.width = required_width
            parent.height = required_height
            parent_width = required_width
            parent_height = required_height
            
            # Clear children positions so they get repositioned
            for child in children:
                child.x = None
                child.y = None
            
            self._position_inside(
                children, parent_x, parent_y, parent_width, parent_height, direction, group_padding
            )
        else:  # outside
            self._position_outside(
                children,
                parent_x,
                parent_y,
                parent_width,
                parent_height,
                direction,
                child_offset,
            )

    def _calculate_required_parent_size(
        self,
        children: List[Node],
        direction: str,
        padding: int,
        parent: Node = None,
        parent_node_config = None,
    ) -> Tuple[float, float]:
        """Calculate minimum parent size needed to contain all children.
        
        Args:
            children: List of child nodes
            direction: Direction for child placement
            padding: Padding around children
            parent: Optional parent node (for text height calculation)
            parent_node_config: Optional node config for parent (for font size)
        """
        if not children:
            # Even with no children, account for parent text (at least 2 lines)
            text_height = 0
            if parent_node_config and parent:
                # Calculate text height for title + text (at least 2 lines)
                line_height = parent_node_config.font_size * 1.25
                text_height = line_height * 2  # At least 2 lines
            return (100.0, max(50.0, text_height + 2 * padding))
        
        # Get child dimensions (with defaults)
        child_widths = [(c.width or 100) for c in children]
        child_heights = [(c.height or 50) for c in children]
        
        max_child_width = max(child_widths) if child_widths else 100
        max_child_height = max(child_heights) if child_heights else 50
        total_child_width = sum(child_widths) if child_widths else 100
        total_child_height = sum(child_heights) if child_heights else 50
        
        # Calculate spacing between children (minimum 10px)
        min_spacing = 10
        num_children = len(children)
        
        # Calculate text height needed for parent (title + text = at least 2 lines)
        text_height = 0
        if parent_node_config and parent:
            line_height = parent_node_config.font_size * 1.25
            # Check if parent has text in metadata
            has_text = parent.metadata and parent.metadata.get("text", "").strip()
            if has_text:
                # Title + text = 2 lines minimum
                text_height = line_height * 2
            else:
                # Just title = 1 line, but we want space for potential text
                text_height = line_height * 2
        else:
            # Default: assume at least 2 lines of text (estimate with default font size)
            default_font_size = 14
            line_height = default_font_size * 1.25
            text_height = line_height * 2
        
        if direction == "top" or direction == "bottom" or direction == "center_h":
            # Horizontal alignment: need width for all children + spacing
            required_width = total_child_width + (num_children - 1) * min_spacing + 2 * padding
            # Height: depends on direction
            # For bottom direction: text_height (top) + max_child_height (bottom) + padding
            # For top direction: max_child_height (top) + text_height (bottom) + padding
            # For center_h: text_height + max_child_height + padding (children in middle, text can be anywhere)
            if direction == "bottom":
                required_height = text_height + max_child_height + 2 * padding
            elif direction == "top":
                required_height = max_child_height + text_height + 2 * padding
            else:  # center_h
                required_height = max(text_height + max_child_height + 2 * padding, max_child_height + 2 * padding)
        elif direction == "left" or direction == "right" or direction == "center_v":
            # Vertical alignment: need height for all children + spacing
            required_width = max(max_child_width + 2 * padding, text_height + 2 * padding)
            required_height = total_child_height + (num_children - 1) * min_spacing + 2 * padding
        else:  # radial
            # Circular arrangement: need space for diameter
            max_dimension = max(max_child_width, max_child_height)
            radius = max_dimension * num_children / 2 if num_children > 1 else max_dimension
            required_width = 2 * radius + 2 * padding
            required_height = 2 * radius + 2 * padding
            # Add text height to radial as well
            required_height = max(required_height, text_height + 2 * padding)
        
        return (required_width, required_height)

    def _position_inside(
        self,
        children: List[Node],
        parent_x: float,
        parent_y: float,
        parent_width: float,
        parent_height: float,
        direction: str,
        padding: int,
    ):
        """Position children inside parent bounds, aligned along the specified edge."""
        if not children:
            return

        # Calculate available space
        available_width = parent_width - 2 * padding
        available_height = parent_height - 2 * padding

        if direction == "bottom":
            # Align children horizontally at the bottom edge
            # Calculate total width needed for all children
            child_widths = [(c.width or 100) for c in children]
            total_children_width = sum(child_widths)
            max_child_height = max((c.height or 50) for c in children)
            
            # Calculate spacing to distribute children evenly
            if len(children) > 1:
                spacing = (available_width - total_children_width) / (len(children) - 1)
            else:
                spacing = 0
            
            # Start from left edge with padding
            x_current = parent_x + padding
            
            # Position each child at the bottom
            y_bottom = parent_y + parent_height - padding - max_child_height
            
            for i, child in enumerate(children):
                child.x = x_current
                child.y = y_bottom
                x_current += child.width or 100
                x_current += spacing
                    
        elif direction == "top":
            # Align children horizontally at the top edge
            child_widths = [(c.width or 100) for c in children]
            total_children_width = sum(child_widths)
            
            if len(children) > 1:
                spacing = (available_width - total_children_width) / (len(children) - 1)
            else:
                spacing = 0
            
            x_current = parent_x + padding
            y_top = parent_y + padding
            
            for i, child in enumerate(children):
                child.x = x_current
                child.y = y_top
                x_current += child.width or 100
                x_current += spacing
                    
        elif direction == "right":
            # Align children vertically on the right edge
            child_heights = [(c.height or 50) for c in children]
            total_children_height = sum(child_heights)
            max_child_width = max((c.width or 100) for c in children)
            
            if len(children) > 1:
                spacing = (available_height - total_children_height) / (len(children) - 1)
            else:
                spacing = 0
            
            y_current = parent_y + padding
            x_right = parent_x + parent_width - padding - max_child_width
            
            for i, child in enumerate(children):
                child.x = x_right
                child.y = y_current
                y_current += child.height or 50
                y_current += spacing
                    
        elif direction == "left":
            # Align children vertically on the left edge
            child_heights = [(c.height or 50) for c in children]
            total_children_height = sum(child_heights)
            
            if len(children) > 1:
                spacing = (available_height - total_children_height) / (len(children) - 1)
            else:
                spacing = 0
            
            y_current = parent_y + padding
            x_left = parent_x + padding
            
            for i, child in enumerate(children):
                child.x = x_left
                child.y = y_current
                y_current += child.height or 50
                y_current += spacing
                    
        elif direction == "center_h":
            # Align children horizontally at the center height (middle of container)
            child_widths = [(c.width or 100) for c in children]
            total_children_width = sum(child_widths)
            max_child_height = max((c.height or 50) for c in children)
            
            if len(children) > 1:
                spacing = (available_width - total_children_width) / (len(children) - 1)
            else:
                spacing = 0
            
            # Start from left edge with padding
            x_current = parent_x + padding
            
            # Position at vertical center (middle of container height)
            y_center = parent_y + parent_height / 2 - max_child_height / 2
            
            for i, child in enumerate(children):
                child.x = x_current
                child.y = y_center
                x_current += child.width or 100
                x_current += spacing
                    
        elif direction == "center_v":
            # Align children vertically at the center width (middle of container)
            child_heights = [(c.height or 50) for c in children]
            total_children_height = sum(child_heights)
            max_child_width = max((c.width or 100) for c in children)
            
            if len(children) > 1:
                spacing = (available_height - total_children_height) / (len(children) - 1)
            else:
                spacing = 0
            
            # Start from top with padding
            y_current = parent_y + padding
            
            # Position at horizontal center (middle of container width)
            x_center = parent_x + parent_width / 2 - max_child_width / 2
            
            for i, child in enumerate(children):
                child.x = x_center
                child.y = y_current
                y_current += child.height or 50
                y_current += spacing
                    
        else:  # radial or default
            # Arrange in grid or radial pattern inside
            center_x = parent_x + parent_width / 2
            center_y = parent_y + parent_height / 2
            radius = min(available_width, available_height) / 3
            angle_step = 360 / len(children) if children else 0
            for i, child in enumerate(children):
                angle = math.radians(i * angle_step)
                child_width = child.width or 100
                child_height = child.height or 50
                child.x = center_x + radius * math.cos(angle) - child_width / 2
                child.y = center_y + radius * math.sin(angle) - child_height / 2

    def _position_outside(
        self,
        children: List[Node],
        parent_x: float,
        parent_y: float,
        parent_width: float,
        parent_height: float,
        direction: str,
        offset: int,
    ):
        """Position children outside parent bounds."""
        if not children:
            return

        center_x = parent_x + parent_width / 2
        center_y = parent_y + parent_height / 2
        base_radius = max(parent_width, parent_height) / 2 + offset

        # Estimate child dimensions for spacing
        avg_child_width = sum((c.width or 100) for c in children) / len(children) if children else 100
        avg_child_height = sum((c.height or 50) for c in children) / len(children) if children else 50
        spacing_x = max(avg_child_width + 20, 100)
        spacing_y = max(avg_child_height + 20, 100)

        if direction == "top":
            # Arrange above parent
            y_base = parent_y - offset - (avg_child_height or 50)
            total_width = (len(children) - 1) * spacing_x
            x_start = center_x - total_width / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = x_start + i * spacing_x - (child.width or 100) / 2
                    child.y = y_base
        elif direction == "bottom":
            # Arrange below parent
            y_base = parent_y + parent_height + offset
            total_width = (len(children) - 1) * spacing_x
            x_start = center_x - total_width / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = x_start + i * spacing_x - (child.width or 100) / 2
                    child.y = y_base
        elif direction == "left":
            # Arrange to the left
            x_base = parent_x - offset - (avg_child_width or 100)
            total_height = (len(children) - 1) * spacing_y
            y_start = center_y - total_height / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = x_base
                    child.y = y_start + i * spacing_y - (child.height or 50) / 2
        elif direction == "right":
            # Arrange to the right
            x_base = parent_x + parent_width + offset
            total_height = (len(children) - 1) * spacing_y
            y_start = center_y - total_height / 2
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    child.x = x_base
                    child.y = y_start + i * spacing_y - (child.height or 50) / 2
        else:  # radial or default
            # Arrange in circle around parent
            angle_step = 360 / len(children) if children else 0
            for i, child in enumerate(children):
                if child.x is None or child.y is None:
                    angle = math.radians(i * angle_step)
                    # Center the child on the circle
                    child.x = center_x + base_radius * math.cos(angle) - (child.width or 100) / 2
                    child.y = center_y + base_radius * math.sin(angle) - (child.height or 50) / 2

