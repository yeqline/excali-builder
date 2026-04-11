"""Markdown parser for loading graph data from markdown files with heading anchors."""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from ..core.graph import Graph
from ..core.node import Node
from ..core.edge import Edge, ConnectionType
from ..config.loader import ConfigLoader
from .base import BaseParser


# Regex patterns for parsing markdown
HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.+?)\s*\{#([\w-]+)\}\s*$')
DIRECTIVE_LINE_PATTERN = re.compile(r'^>\s*([A-Za-z_][\w.-]*):\s*(.*)$')
INLINE_LINK_PATTERN = re.compile(r'\[[^\]]+\]\(#([\w-]+)\)')
YAML_FRONT_MATTER_START = re.compile(r'^---\s*$')

BUILTIN_CHILD_EDGE_TYPES = {
    "comment": "comment",
    "link": "link",
}


class MarkdownParser(BaseParser):
    """Parser for Markdown-based graph data with heading anchors.
    
    Parses markdown files following these conventions:
    - Nodes: Headings with {#id} anchors (e.g., ## Title {#my-node})
    - Directives: > key: value lines directly below the heading
    - Edge directives: > edge.related: other-node
    - Inline links: [text](#id) become related edges
    - Parent-child: Inferred from heading hierarchy
    - Built-in child node types can swap the rendered hierarchy edge type
    """

    def parse(self, path: Path, options: Dict[str, Any]) -> Graph:
        """Parse markdown files in the given folder and return a Graph."""
        graph = Graph()
        
        # Load config to look up connection_type from edge_type
        config = ConfigLoader.load_from_folder(path)
        
        # Find all markdown files in the folder
        md_files = sorted(path.glob("*.md"))
        
        for md_file in md_files:
            self._parse_file(md_file, graph, config)
        
        # Remove edges with missing targets (cross-file links to non-existent nodes)
        graph.edges = [
            e for e in graph.edges 
            if e.source_id in graph.nodes and e.target_id in graph.nodes
        ]
        self._validate_link_targets(graph)
        
        return graph

    def _parse_file(self, file_path: Path, graph: Graph, config) -> None:
        """Parse a single markdown file and add nodes/edges to the graph."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        
        # Track parsing state
        current_node: Optional[Node] = None
        parent_stack: List[Tuple[int, str]] = []  # (level, node_id)
        in_yaml_front_matter = False
        in_directive_zone = False
        content_lines: List[str] = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip YAML front matter
            if i == 0 and YAML_FRONT_MATTER_START.match(line):
                in_yaml_front_matter = True
                i += 1
                continue
            
            if in_yaml_front_matter:
                if YAML_FRONT_MATTER_START.match(line):
                    in_yaml_front_matter = False
                i += 1
                continue
            
            # Check for heading with ID
            heading_match = HEADING_PATTERN.match(line)
            if heading_match:
                # Save previous node's content
                if current_node:
                    self._finalize_node(graph, current_node, content_lines, config)
                    content_lines = []
                
                # Parse heading
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                node_id = heading_match.group(3)
                
                # Skip duplicate IDs (first one wins)
                if node_id in graph.nodes:
                    i += 1
                    continue
                
                # Determine parent from heading hierarchy
                parent_id = None
                while parent_stack and parent_stack[-1][0] >= level:
                    parent_stack.pop()
                if parent_stack:
                    parent_id = parent_stack[-1][1]
                
                # Create node with default type
                current_node = Node(
                    id=node_id,
                    label=title,
                    type="concept",  # Default type
                    metadata={
                        "level": level,
                        "source_file": str(file_path.name),
                        "hierarchy_parent_id": parent_id,
                        "has_explicit_link_edge": False,
                    },
                )
                graph.add_node(current_node)
                in_directive_zone = True
                
                # Add to parent stack
                parent_stack.append((level, node_id))
                
                i += 1
                continue
            
            if current_node and in_directive_zone:
                directive_match = DIRECTIVE_LINE_PATTERN.match(line)
                if directive_match:
                    key = directive_match.group(1).strip()
                    value = directive_match.group(2).strip()
                    self._apply_directive(graph, current_node, key, value, config)
                    i += 1
                    continue

                if not line.strip():
                    i += 1
                    continue

                in_directive_zone = False
            
            # Collect content for current node and extract inline links
            if current_node:
                # Extract inline links as related edges
                for link_match in INLINE_LINK_PATTERN.finditer(line):
                    target_id = link_match.group(1)
                    # Avoid duplicate edges and self-links
                    if target_id != current_node.id:
                        connection_type_str = ConfigLoader.get_connection_type(config, "related")
                        connection_type = ConnectionType.CONTAINER if connection_type_str == "container" else ConnectionType.LINE
                        
                        graph.add_edge(Edge(
                            source_id=current_node.id,
                            target_id=target_id,
                            connection_type=connection_type,
                            edge_type="related",
                            metadata={"is_inline_link": True},
                        ))
                
                content_lines.append(line)
            
            i += 1
        
        # Save last node's content
        if current_node:
            self._finalize_node(graph, current_node, content_lines, config)

    def _finalize_node(self, graph: Graph, node: Node, content_lines: List[str], config) -> None:
        """Store content and create any inferred structural edges."""
        self._store_node_content(node, content_lines)
        self._add_default_hierarchy_edge(graph, node, config)

    def _add_default_hierarchy_edge(self, graph: Graph, node: Node, config) -> None:
        """Add the inferred edge from heading hierarchy unless explicitly overridden."""
        parent_id = node.metadata.get("hierarchy_parent_id") if node.metadata else None
        if not parent_id:
            return

        if any(
            edge.source_id == parent_id and edge.target_id == node.id
            for edge in graph.edges
        ):
            return

        edge_type = self._get_default_hierarchy_edge_type(node)
        connection_type_str = ConfigLoader.get_connection_type(config, edge_type)

        connection_type = (
            ConnectionType.CONTAINER
            if connection_type_str == "container"
            else ConnectionType.LINE
        )
        graph.add_edge(
            Edge(
                source_id=parent_id,
                target_id=node.id,
                connection_type=connection_type,
                edge_type=edge_type,
            )
        )

    def _store_node_content(self, node: Node, content_lines: List[str]) -> None:
        """Store markdown body text in both raw and rendered metadata fields."""
        content = "\n".join(content_lines).strip()
        node.metadata["content"] = content
        if content:
            node.metadata["text"] = content

    def _get_default_hierarchy_edge_type(self, node: Node) -> str:
        """Return the built-in edge type used for inferred heading hierarchy."""
        if node.type == "link" and node.metadata.get("has_explicit_link_edge"):
            return "parent_child"
        return BUILTIN_CHILD_EDGE_TYPES.get(node.type, "parent_child")

    def _apply_directive(
        self,
        graph: Graph,
        node: Node,
        key: str,
        value: str,
        config,
    ) -> None:
        """Apply a simplified blockquote directive to the current node."""
        if key.startswith("edge."):
            edge_type = key.split(".", 1)[1].strip()
            if edge_type:
                self._add_edges(graph, node.id, edge_type, value, config)
            return

        self._apply_meta(node, key, value)

    def _apply_meta(self, node: Node, key: str, value: str) -> None:
        """Apply a meta field to a node."""
        if key == "type":
            # Map type value to node type
            node.type = value
        elif key == "tags":
            tags = [t.strip() for t in value.split(',') if t.strip()]
            node.metadata["tags"] = tags
        else:
            # Store other meta fields in metadata
            node.metadata[key] = value

    def _add_edges(
        self,
        graph: Graph,
        source_id: str,
        edge_type: str,
        targets_str: str,
        config,
    ) -> None:
        """Add one or more edges of the same type from a comma-separated target list."""
        connection_type_str = ConfigLoader.get_connection_type(config, edge_type)
        connection_type = (
            ConnectionType.CONTAINER
            if connection_type_str == "container"
            else ConnectionType.LINE
        )

        targets = [t.strip() for t in targets_str.split(',') if t.strip()]
        for target_id in targets:
            target_id = target_id.strip().lstrip('- ')
            if target_id and target_id != source_id:
                if edge_type == "link" and source_id in graph.nodes:
                    graph.nodes[source_id].metadata["has_explicit_link_edge"] = True
                graph.add_edge(
                    Edge(
                        source_id=source_id,
                        target_id=target_id,
                        connection_type=connection_type,
                        edge_type=edge_type,
                    )
                )

    def _validate_link_targets(self, graph: Graph) -> None:
        """Validate built-in link node targets after all files are parsed."""
        for node in graph.nodes.values():
            if node.type != "link":
                continue

            target = (node.metadata.get("target") or "").strip()
            if not target:
                raise ValueError(f"Link node '{node.id}' is missing required meta field 'target'")

            target_node_id = self._get_internal_link_target_node_id(target, graph)
            if target_node_id and target_node_id not in graph.nodes:
                raise ValueError(
                    f"Link node '{node.id}' references missing target node '{target}'"
                )

    def _get_internal_link_target_node_id(self, target: str, graph: Graph) -> Optional[str]:
        """Return the internal target node id when a link target points at this graph."""
        if target.startswith("#"):
            return target[1:] or None
        if target in graph.nodes:
            return target
        return None

    def get_supported_formats(self) -> List[str]:
        """Return list of supported file extensions."""
        return ["md", "markdown"]
