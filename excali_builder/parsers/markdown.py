"""Markdown parser for loading graph data from markdown files with heading anchors."""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from ..core.graph import Graph
from ..core.node import Node
from ..core.edge import Edge, ConnectionType
from ..config.loader import ConfigLoader
from ..image_assets import resolve_local_image_asset
from .base import BaseParser


# Regex patterns for parsing markdown
HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.+?)\s*\{#([\w-]+)\}\s*$')
DIRECTIVE_LINE_PATTERN = re.compile(r'^>\s*([A-Za-z_][\w.-]*):\s*(.*)$')
INLINE_LINK_PATTERN = re.compile(r'(?<!!)\[[^\]]+\]\(#([\w-]+)\)')
MARKDOWN_IMAGE_PATTERN = re.compile(
    r'!\[([^\]]*)\]\((<[^>]+>|[^)\s]+)(?:\s+(?:"([^"]*)"|\'([^\']*)\'|\(([^)]*)\)))?\)'
)
FENCED_CODE_PATTERN = re.compile(r'^\s*(```|~~~)')
YAML_FRONT_MATTER_START = re.compile(r'^---\s*$')

BUILTIN_CHILD_EDGE_TYPES = {
    "image": "attachment",
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

        # Find all markdown files in the folder
        md_files = sorted(path.glob("*.md"))

        for md_file in md_files:
            self._parse_file(md_file, graph, path)

        # Remove edges with missing targets (cross-file links to non-existent nodes)
        graph.edges = [
            e for e in graph.edges 
            if e.source_id in graph.nodes and e.target_id in graph.nodes
        ]
        self._validate_link_targets(graph)
        self._validate_procedure_sequences(graph)

        ConfigLoader.ensure_graph_config(path, graph)
        config = ConfigLoader.load_from_folder(path)
        ConfigLoader.apply_config_to_graph(graph, config)

        return graph

    def _parse_file(self, file_path: Path, graph: Graph, project_path: Path) -> None:
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
                    self._finalize_node(
                        graph,
                        current_node,
                        content_lines,
                        file_path,
                        project_path,
                    )
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
                        "source_order": len(graph.nodes),
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
                    self._apply_directive(graph, current_node, key, value)
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
                        graph.add_edge(Edge(
                            source_id=current_node.id,
                            target_id=target_id,
                            connection_type=ConnectionType.LINE,
                            edge_type="related",
                            metadata={"is_inline_link": True},
                        ))
                
                content_lines.append(line)
            
            i += 1
        
        # Save last node's content
        if current_node:
            self._finalize_node(
                graph,
                current_node,
                content_lines,
                file_path,
                project_path,
            )

    def _finalize_node(
        self,
        graph: Graph,
        node: Node,
        content_lines: List[str],
        file_path: Path,
        project_path: Path,
    ) -> None:
        """Store content and create any inferred structural edges."""
        content_lines = self._extract_image_attachments(
            graph,
            node,
            content_lines,
            file_path,
            project_path,
        )
        self._store_node_content(node, content_lines)
        self._add_default_hierarchy_edge(graph, node)

    def _extract_image_attachments(
        self,
        graph: Graph,
        node: Node,
        content_lines: List[str],
        file_path: Path,
        project_path: Path,
    ) -> List[str]:
        """Convert Markdown images in node content into implicit attachment nodes."""
        if not content_lines:
            return content_lines

        image_occurrence_counts: Dict[str, int] = {}
        processed_lines: List[str] = []
        in_fenced_code = False

        for line in content_lines:
            if FENCED_CODE_PATTERN.match(line):
                in_fenced_code = not in_fenced_code
                processed_lines.append(line)
                continue

            if in_fenced_code:
                processed_lines.append(line)
                continue

            cursor = 0
            line_parts: List[str] = []
            has_image = False

            for match in MARKDOWN_IMAGE_PATTERN.finditer(line):
                raw_src = match.group(2) or ""
                try:
                    asset = resolve_local_image_asset(project_path, file_path, raw_src)
                except ValueError as exc:
                    raise ValueError(
                        f"Node '{node.id}' has an invalid image source '{raw_src}': {exc}"
                    ) from exc

                occurrence = image_occurrence_counts.get(asset.relative_path, 0) + 1
                image_occurrence_counts[asset.relative_path] = occurrence
                image_node = self._create_image_attachment_node(
                    parent_node=node,
                    graph=graph,
                    asset=asset,
                    alt_text=(match.group(1) or "").strip(),
                    title=(match.group(3) or match.group(4) or match.group(5) or "").strip(),
                    occurrence=occurrence,
                    source_file=file_path.name,
                )
                graph.add_node(image_node)
                self._add_default_hierarchy_edge(graph, image_node)

                line_parts.append(line[cursor:match.start()])
                line_parts.append(self._get_image_replacement_text(line, match.start(), match.end()))
                cursor = match.end()
                has_image = True

            if not has_image:
                processed_lines.append(line)
                continue

            line_parts.append(line[cursor:])
            cleaned_line = "".join(line_parts)
            cleaned_line = re.sub(r'(?<=\S)[ \t]{2,}(?=\S)', ' ', cleaned_line)
            processed_lines.append(cleaned_line)

        return processed_lines

    def _create_image_attachment_node(
        self,
        parent_node: Node,
        graph: Graph,
        asset,
        alt_text: str,
        title: str,
        occurrence: int,
        source_file: str,
    ) -> Node:
        """Create an implicit child node for a Markdown image attachment."""
        node_id = self._build_image_attachment_id(parent_node.id, asset.relative_path, occurrence)
        label = alt_text or Path(asset.relative_path).stem or Path(asset.relative_path).name
        return Node(
            id=node_id,
            label=label,
            type="image",
            metadata={
                "alt": alt_text,
                "hierarchy_parent_id": parent_node.id,
                "level": (parent_node.metadata.get("level") or 1) + 1,
                "mime_type": asset.mime_type,
                "natural_height": asset.height,
                "natural_width": asset.width,
                "source_file": source_file,
                "source_order": len(graph.nodes),
                "src": asset.relative_path,
                "title": title,
            },
        )

    def _build_image_attachment_id(
        self,
        parent_node_id: str,
        relative_path: str,
        occurrence: int,
    ) -> str:
        """Build a stable node ID for an implicit image attachment."""
        path_suffix = re.sub(r'[^A-Za-z0-9-]+', '-', relative_path).strip('-').lower()
        path_suffix = path_suffix[:32] or "image"
        return f"{parent_node_id}-image-{path_suffix}-{occurrence}"

    def _get_image_replacement_text(self, line: str, start: int, end: int) -> str:
        """Return separator text when removing an inline Markdown image."""
        previous_char = line[start - 1] if start > 0 else ""
        next_char = line[end] if end < len(line) else ""
        if previous_char and next_char and not previous_char.isspace() and not next_char.isspace():
            return " "
        return ""

    def _add_default_hierarchy_edge(self, graph: Graph, node: Node) -> None:
        """Add the inferred edge from heading hierarchy unless explicitly overridden."""
        parent_id = node.metadata.get("hierarchy_parent_id") if node.metadata else None
        if not parent_id:
            return

        if any(
            edge.source_id == parent_id and edge.target_id == node.id
            for edge in graph.edges
        ):
            return

        edge_type = self._get_default_hierarchy_edge_type(graph, node)
        graph.add_edge(
            Edge(
                source_id=parent_id,
                target_id=node.id,
                connection_type=ConnectionType.LINE,
                edge_type=edge_type,
            )
        )

    def _store_node_content(self, node: Node, content_lines: List[str]) -> None:
        """Store markdown body text in both raw and rendered metadata fields."""
        content = "\n".join(content_lines).strip()
        node.metadata["content"] = content
        if content:
            node.metadata["text"] = content

    def _get_default_hierarchy_edge_type(self, graph: Graph, node: Node) -> str:
        """Return the built-in edge type used for inferred heading hierarchy."""
        parent_id = node.metadata.get("hierarchy_parent_id") if node.metadata else None
        parent = graph.nodes.get(parent_id) if parent_id else None
        if parent and parent.type == "procedure" and node.type == "step":
            return "procedure_step"
        if node.type == "link" and node.metadata.get("has_explicit_link_edge"):
            return "parent_child"
        return BUILTIN_CHILD_EDGE_TYPES.get(node.type, "parent_child")

    def _apply_directive(
        self,
        graph: Graph,
        node: Node,
        key: str,
        value: str,
    ) -> None:
        """Apply a simplified blockquote directive to the current node."""
        if key.startswith("edge."):
            edge_type = key.split(".", 1)[1].strip()
            if edge_type:
                self._add_edges(graph, node.id, edge_type, value)
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
    ) -> None:
        """Add one or more edges of the same type from a comma-separated target list."""
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
                        connection_type=ConnectionType.LINE,
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

    def _validate_procedure_sequences(self, graph: Graph) -> None:
        """Validate built-in procedure sequencing rules."""
        next_edges = [edge for edge in graph.edges if edge.edge_type == "next"]

        for edge in next_edges:
            source = graph.nodes.get(edge.source_id)
            target = graph.nodes.get(edge.target_id)
            if not source or not target:
                continue

            if source.type != "step" or target.type != "step":
                raise ValueError(
                    f"Next edge '{edge.source_id}' -> '{edge.target_id}' must connect step nodes"
                )

            source_parent_id = source.metadata.get("hierarchy_parent_id") if source.metadata else None
            target_parent_id = target.metadata.get("hierarchy_parent_id") if target.metadata else None
            if not source_parent_id or source_parent_id != target_parent_id:
                raise ValueError(
                    f"Next edge '{edge.source_id}' -> '{edge.target_id}' must stay within one procedure"
                )

            parent = graph.nodes.get(source_parent_id)
            if not parent or parent.type != "procedure":
                raise ValueError(
                    f"Next edge '{edge.source_id}' -> '{edge.target_id}' must be nested under a procedure node"
                )

        for node in graph.nodes.values():
            if node.type != "procedure":
                continue

            step_children = [
                child
                for child in graph.get_hierarchy_children(node.id)
                if child.type == "step"
            ]
            if len(step_children) <= 1:
                continue

            step_ids = {child.id for child in step_children}
            procedure_next_edges = [
                edge
                for edge in next_edges
                if edge.source_id in step_ids or edge.target_id in step_ids
            ]
            if not procedure_next_edges:
                continue

            if len(procedure_next_edges) != len(step_children) - 1:
                raise ValueError(
                    f"Procedure '{node.id}' must define a single next chain covering all step children"
                )

            outgoing = {}
            incoming = {}
            for edge in procedure_next_edges:
                if edge.source_id in outgoing:
                    raise ValueError(
                        f"Step node '{edge.source_id}' has multiple outgoing next edges"
                    )
                if edge.target_id in incoming:
                    raise ValueError(
                        f"Step node '{edge.target_id}' has multiple incoming next edges"
                    )
                outgoing[edge.source_id] = edge.target_id
                incoming[edge.target_id] = edge.source_id

            roots = [step_id for step_id in step_ids if step_id not in incoming]
            if len(roots) != 1:
                raise ValueError(
                    f"Procedure '{node.id}' must have exactly one first step in its next chain"
                )

            visited = set()
            current_id = roots[0]
            while current_id is not None:
                if current_id in visited:
                    raise ValueError(f"Procedure '{node.id}' contains a cycle in its next chain")
                visited.add(current_id)
                current_id = outgoing.get(current_id)

            if visited != step_ids:
                raise ValueError(
                    f"Procedure '{node.id}' must define a single next chain covering all step children"
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
