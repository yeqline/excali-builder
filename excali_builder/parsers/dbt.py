"""dbt manifest parser for lineage diagrams."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..config.loader import ConfigLoader
from ..core.edge import ConnectionType, Edge
from ..core.graph import Graph
from ..core.node import Node
from ..image_assets import resolve_local_image_asset
from .base import BaseParser


DEFAULT_RESOURCE_TYPES = {"source", "model", "seed", "snapshot", "exposure"}
RESOURCE_COLLECTIONS = (
    "nodes",
    "sources",
    "exposures",
    "metrics",
    "semantic_models",
    "saved_queries",
)
OVERLAY_FILENAME = "dbt_overlay.json"
NODE_INDEX_FILENAME = "dbt_node_index.json"


def get_dbt_input_paths(folder: Path, options: Dict[str, Any]) -> List[Path]:
    """Return dbt files that should trigger rebuilds in serve mode."""
    paths = resolve_manifest_paths(folder, options)
    overlay_path = resolve_overlay_path(folder, options)
    return paths + [overlay_path]


def resolve_manifest_paths(folder: Path, options: Dict[str, Any]) -> List[Path]:
    """Resolve manifest paths from dbt parser options."""
    root = _resolve_dbt_root(folder, options)
    raw_manifest_paths = options.get("manifest_paths")
    if raw_manifest_paths is None:
        raw_manifest_path = options.get("manifest_path")
        raw_manifest_paths = [raw_manifest_path] if raw_manifest_path else ["target/manifest.json"]

    if isinstance(raw_manifest_paths, (str, Path)):
        raw_manifest_paths = [raw_manifest_paths]
    if not isinstance(raw_manifest_paths, list):
        raise ValueError("parser_options.manifest_paths must be a string or array")

    paths = []
    for raw_path in raw_manifest_paths:
        if not isinstance(raw_path, (str, Path)):
            raise ValueError("parser_options.manifest_paths entries must be strings")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = root / path
        paths.append(path.resolve())
    return paths


def resolve_overlay_path(folder: Path, options: Dict[str, Any]) -> Path:
    """Resolve the dbt overlay path from parser options."""
    raw_overlay_path = options.get("overlay_path", OVERLAY_FILENAME)
    if not isinstance(raw_overlay_path, (str, Path)):
        raise ValueError("parser_options.overlay_path must be a string")

    overlay_path = Path(raw_overlay_path).expanduser()
    if not overlay_path.is_absolute():
        overlay_path = folder / overlay_path
    return overlay_path.resolve()


def _resolve_dbt_root(folder: Path, options: Dict[str, Any]) -> Path:
    raw_root = options.get("dbt_project_root", options.get("project_root"))
    if not raw_root:
        return folder.resolve()
    if not isinstance(raw_root, (str, Path)):
        raise ValueError("parser_options.dbt_project_root must be a string")
    root = Path(raw_root).expanduser()
    if not root.is_absolute():
        root = folder / root
    return root.resolve()


class DbtManifestParser(BaseParser):
    """Parser for dbt manifest.json files with a human-authored overlay."""

    def parse(self, path: Path, options: Dict[str, Any]) -> Graph:
        """Parse one or more dbt manifests and return a Graph."""
        options = options or {}
        manifest_paths = resolve_manifest_paths(path, options)
        overlay_path = resolve_overlay_path(path, options)
        resource_types = self._get_resource_types(options)

        resources, parent_maps = self._load_resources(manifest_paths, resource_types)
        graph = Graph()
        resolver = DbtReferenceResolver(resources)

        for resource in sorted(resources.values(), key=self._resource_sort_key):
            graph.add_node(self._create_resource_node(resource, len(graph.nodes)))

        self._add_lineage_edges(graph, resources, parent_maps)

        overlay = self._load_overlay(overlay_path, explicit_overlay="overlay_path" in options)
        self._apply_overlay(graph, overlay, overlay_path, resolver)
        self._write_node_index(path, resolver)

        ConfigLoader.ensure_graph_config(path, graph)
        config = ConfigLoader.load_from_folder(path)
        ConfigLoader.apply_config_to_graph(graph, config)
        return graph

    def get_supported_formats(self) -> List[str]:
        """Return supported parser identifiers."""
        return ["dbt", "manifest"]

    def _get_resource_types(self, options: Dict[str, Any]) -> Set[str]:
        raw_resource_types = options.get("resource_types")
        if raw_resource_types is None:
            resource_types = set(DEFAULT_RESOURCE_TYPES)
        else:
            if not isinstance(raw_resource_types, list):
                raise ValueError("parser_options.resource_types must be an array")
            resource_types = {
                str(value).strip()
                for value in raw_resource_types
                if str(value).strip()
            }

        if options.get("include_tests") is True:
            resource_types.add("test")
        else:
            resource_types.discard("test")
        return resource_types

    def _load_resources(
        self,
        manifest_paths: List[Path],
        resource_types: Set[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, List[str]]]]:
        resources: Dict[str, Dict[str, Any]] = {}
        parent_maps = []

        for manifest_path in manifest_paths:
            manifest = self._load_json_object(manifest_path, "manifest")
            parent_map = manifest.get("parent_map", {})
            if isinstance(parent_map, dict):
                parent_maps.append(parent_map)

            for collection_name in RESOURCE_COLLECTIONS:
                collection = manifest.get(collection_name, {})
                if not isinstance(collection, dict):
                    continue
                for fallback_unique_id, raw_resource in collection.items():
                    if not isinstance(raw_resource, dict):
                        continue
                    resource = self._normalize_resource(
                        fallback_unique_id,
                        raw_resource,
                        manifest_path,
                    )
                    if resource["resource_type"] not in resource_types:
                        continue
                    self._merge_resource(resources, resource)

        if not resources:
            raise ValueError("No dbt resources matched parser_options.resource_types")
        return resources, parent_maps

    def _normalize_resource(
        self,
        fallback_unique_id: str,
        raw_resource: Dict[str, Any],
        manifest_path: Path,
    ) -> Dict[str, Any]:
        unique_id = str(raw_resource.get("unique_id") or fallback_unique_id).strip()
        resource_type = str(raw_resource.get("resource_type") or "").strip()
        package_name = str(raw_resource.get("package_name") or "").strip()
        name = str(raw_resource.get("name") or unique_id).strip()

        if not unique_id or not resource_type:
            raise ValueError(
                f"Manifest resource in {manifest_path} is missing unique_id/resource_type"
            )

        return {
            "unique_id": unique_id,
            "resource_type": resource_type,
            "package_name": package_name,
            "name": name,
            "source_name": str(raw_resource.get("source_name") or "").strip(),
            "schema": str(raw_resource.get("schema") or "").strip(),
            "database": str(raw_resource.get("database") or "").strip(),
            "alias": str(raw_resource.get("alias") or "").strip(),
            "description": str(raw_resource.get("description") or "").strip(),
            "path": str(raw_resource.get("path") or "").strip(),
            "raw": raw_resource,
            "manifest_path": str(manifest_path),
        }

    def _merge_resource(
        self,
        resources: Dict[str, Dict[str, Any]],
        resource: Dict[str, Any],
    ) -> None:
        unique_id = resource["unique_id"]
        if unique_id not in resources:
            resources[unique_id] = resource
            return

        existing = resources[unique_id]
        fields = ("resource_type", "package_name", "name")
        conflicts = [
            field
            for field in fields
            if (existing.get(field) or "") != (resource.get(field) or "")
        ]
        if conflicts:
            raise ValueError(
                f"Conflicting dbt resource definitions for '{unique_id}' across manifests"
            )

        for field in ("source_name", "schema", "database", "alias", "description", "path"):
            if not existing.get(field) and resource.get(field):
                existing[field] = resource[field]
        if (
            not existing.get("raw", {}).get("description")
            and resource.get("raw", {}).get("description")
        ):
            existing["raw"] = resource["raw"]

    def _create_resource_node(self, resource: Dict[str, Any], source_order: int) -> Node:
        resource_type = resource["resource_type"]
        metadata = {
            "dbt_unique_id": resource["unique_id"],
            "dbt_resource_type": resource_type,
            "dbt_project": resource["package_name"],
            "dbt_name": resource["name"],
            "dbt_schema": resource["schema"],
            "dbt_database": resource["database"],
            "dbt_path": resource["path"],
            "source_file": Path(resource["manifest_path"]).name,
            "source_order": source_order,
        }
        description = self._build_resource_text(resource)
        if description:
            metadata["content"] = description
            metadata["text"] = description

        return Node(
            id=resource["unique_id"],
            label=self._resource_label(resource),
            type=f"dbt_{resource_type}",
            metadata=metadata,
        )

    def _resource_label(self, resource: Dict[str, Any]) -> str:
        if resource["resource_type"] == "source":
            source_name = resource.get("source_name") or "source"
            return f"{source_name}.{resource['name']}"
        return resource.get("name") or resource["unique_id"]

    def _build_resource_text(self, resource: Dict[str, Any]) -> str:
        parts = []
        raw_config = resource.get("raw", {}).get("config", {})
        materialized = raw_config.get("materialized") if isinstance(raw_config, dict) else None
        if materialized:
            parts.append(str(materialized))

        location_parts = [
            part
            for part in (resource.get("database"), resource.get("schema"))
            if part
        ]
        if location_parts:
            parts.append(".".join(location_parts))

        if resource.get("description"):
            parts.append(resource["description"])
        return "\n".join(parts)

    def _add_lineage_edges(
        self,
        graph: Graph,
        resources: Dict[str, Dict[str, Any]],
        parent_maps: List[Dict[str, List[str]]],
    ) -> None:
        edge_keys: Set[Tuple[str, str]] = set()

        for parent_map in parent_maps:
            for child_id, parent_ids in parent_map.items():
                if child_id not in graph.nodes or not isinstance(parent_ids, list):
                    continue
                for parent_id in parent_ids:
                    self._add_lineage_edge(graph, edge_keys, str(parent_id), str(child_id))

        for child_id, resource in resources.items():
            depends_on = resource.get("raw", {}).get("depends_on", {})
            if not isinstance(depends_on, dict):
                continue
            for parent_id in depends_on.get("nodes", []) or []:
                self._add_lineage_edge(graph, edge_keys, str(parent_id), child_id)

    def _add_lineage_edge(
        self,
        graph: Graph,
        edge_keys: Set[Tuple[str, str]],
        parent_id: str,
        child_id: str,
    ) -> None:
        if parent_id == child_id:
            return
        if parent_id not in graph.nodes or child_id not in graph.nodes:
            return
        edge_key = (parent_id, child_id)
        if edge_key in edge_keys:
            return
        edge_keys.add(edge_key)
        graph.add_edge(
            Edge(
                source_id=parent_id,
                target_id=child_id,
                connection_type=ConnectionType.LINE,
                edge_type="lineage",
            )
        )

    def _load_overlay(
        self,
        overlay_path: Path,
        explicit_overlay: bool,
    ) -> Dict[str, Any]:
        if not overlay_path.exists():
            if explicit_overlay:
                raise FileNotFoundError(f"dbt overlay file does not exist: {overlay_path}")
            return {}
        return self._load_json_object(overlay_path, "dbt overlay")

    def _apply_overlay(
        self,
        graph: Graph,
        overlay: Dict[str, Any],
        overlay_path: Path,
        resolver: "DbtReferenceResolver",
    ) -> None:
        if not overlay:
            return

        self._validate_allowed_keys(
            overlay,
            {"version", "groups", "nodes"},
            "dbt overlay",
        )
        version = overlay.get("version", 1)
        if version != 1:
            raise ValueError("dbt overlay version must be 1")

        group_specs = self._normalize_group_specs(overlay.get("groups", []), "groups")
        seen_group_ids: Set[str] = set()
        for group_spec in group_specs:
            self._add_group(graph, group_spec, None, [], resolver, seen_group_ids)

        self._apply_node_overlays(graph, overlay.get("nodes", {}), overlay_path, resolver)

    def _normalize_group_specs(self, raw_groups: Any, path: str) -> List[Dict[str, Any]]:
        if raw_groups in (None, []):
            return []
        if isinstance(raw_groups, dict):
            return [
                self._normalize_group_mapping(title, value, f"{path}.{title}")
                for title, value in raw_groups.items()
            ]
        if isinstance(raw_groups, list):
            normalized = []
            for index, raw_group in enumerate(raw_groups):
                item_path = f"{path}[{index}]"
                if not isinstance(raw_group, dict):
                    raise ValueError(f"{item_path} must be an object")
                normalized.append(self._normalize_group_object(raw_group, item_path))
            return normalized
        raise ValueError(f"{path} must be an object or array")

    def _normalize_group_mapping(self, title: str, value: Any, path: str) -> Dict[str, Any]:
        if isinstance(value, list):
            return {"title": str(title), "members": value, "children": []}
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object or array")

        recognized_keys = {"id", "title", "description", "members", "children", "groups"}
        if set(value).intersection(recognized_keys):
            merged = dict(value)
            merged.setdefault("title", str(title))
            return self._normalize_group_object(merged, path)

        return {
            "title": str(title),
            "members": [],
            "children": self._normalize_group_specs(value, path),
        }

    def _normalize_group_object(self, raw_group: Dict[str, Any], path: str) -> Dict[str, Any]:
        self._validate_allowed_keys(
            raw_group,
            {"id", "title", "description", "members", "children", "groups"},
            path,
        )
        title = raw_group.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{path}.title must be a non-empty string")

        members = raw_group.get("members", [])
        if not isinstance(members, list):
            raise ValueError(f"{path}.members must be an array")

        child_groups = raw_group.get("children", raw_group.get("groups", []))
        return {
            "id": raw_group.get("id"),
            "title": title.strip(),
            "description": raw_group.get("description"),
            "members": members,
            "children": self._normalize_group_specs(child_groups, f"{path}.children"),
        }

    def _add_group(
        self,
        graph: Graph,
        group_spec: Dict[str, Any],
        parent_group_id: Optional[str],
        ancestry: List[str],
        resolver: "DbtReferenceResolver",
        seen_group_ids: Set[str],
    ) -> str:
        title = group_spec["title"]
        raw_group_id = group_spec.get("id") or ".".join(ancestry + [title])
        group_id = f"overlay.group.{_slugify(str(raw_group_id))}"
        if group_id in seen_group_ids or group_id in graph.nodes:
            raise ValueError(f"Duplicate dbt overlay group id: {group_id}")
        seen_group_ids.add(group_id)

        metadata = {
            "dbt_overlay_kind": "group",
            "source_order": len(graph.nodes),
        }
        if parent_group_id:
            metadata["hierarchy_parent_id"] = parent_group_id
        description = group_spec.get("description")
        if description is not None:
            if not isinstance(description, str):
                raise ValueError(f"Group '{title}' description must be a string")
            metadata["content"] = description
            metadata["text"] = description

        graph.add_node(Node(id=group_id, label=title, type="dbt_group", metadata=metadata))
        if parent_group_id:
            self._add_group_edge(graph, parent_group_id, group_id)

        for index, member_ref in enumerate(group_spec["members"]):
            member_id = resolver.resolve(member_ref, f"group '{title}' member {index}")
            self._add_group_edge(graph, group_id, member_id)

        for child_group in group_spec["children"]:
            self._add_group(
                graph,
                child_group,
                group_id,
                ancestry + [title],
                resolver,
                seen_group_ids,
            )

        return group_id

    def _add_group_edge(self, graph: Graph, source_id: str, target_id: str) -> None:
        graph.add_edge(
            Edge(
                source_id=source_id,
                target_id=target_id,
                connection_type=ConnectionType.ENCLOSING_GROUP,
                edge_type="group_member",
            )
        )

    def _apply_node_overlays(
        self,
        graph: Graph,
        raw_nodes: Any,
        overlay_path: Path,
        resolver: "DbtReferenceResolver",
    ) -> None:
        if raw_nodes in (None, {}):
            return
        if not isinstance(raw_nodes, dict):
            raise ValueError("dbt overlay nodes must be an object")

        seen_targets: Set[str] = set()
        for ref, overlay in raw_nodes.items():
            if not isinstance(overlay, dict):
                raise ValueError(f"dbt overlay node '{ref}' must be an object")
            self._validate_allowed_keys(
                overlay,
                {"description", "comments", "media"},
                f"dbt overlay node '{ref}'",
            )
            target_id = resolver.resolve(ref, f"node overlay '{ref}'")
            if target_id in seen_targets:
                raise ValueError(f"Multiple dbt overlay node entries resolve to '{target_id}'")
            seen_targets.add(target_id)

            node = graph.nodes[target_id]
            description = overlay.get("description")
            if description is not None:
                if not isinstance(description, str):
                    raise ValueError(f"dbt overlay node '{ref}' description must be a string")
                self._append_node_text(node, description)

            self._add_comment_nodes(
                graph,
                node,
                overlay.get("comments", []),
                f"dbt overlay node '{ref}'.comments",
            )
            self._add_media_nodes(
                graph,
                node,
                overlay.get("media", []),
                overlay_path,
                f"dbt overlay node '{ref}'.media",
            )

    def _add_comment_nodes(
        self,
        graph: Graph,
        parent: Node,
        raw_comments: Any,
        path: str,
    ) -> None:
        if raw_comments in (None, []):
            return
        if not isinstance(raw_comments, list):
            raise ValueError(f"{path} must be an array")

        for index, raw_comment in enumerate(raw_comments):
            comment = self._normalize_comment(raw_comment, f"{path}[{index}]", index)
            node_id = f"{parent.id}--comment--{_slugify(comment['id'])}"
            if node_id in graph.nodes:
                raise ValueError(f"Duplicate comment id under '{parent.id}': {comment['id']}")
            graph.add_node(
                Node(
                    id=node_id,
                    label=comment["title"],
                    type="comment",
                    metadata={
                        "hierarchy_parent_id": parent.id,
                        "source_order": len(graph.nodes),
                        "text": comment["text"],
                        "content": comment["text"],
                    },
                )
            )
            graph.add_edge(
                Edge(
                    source_id=parent.id,
                    target_id=node_id,
                    connection_type=ConnectionType.LINE,
                    edge_type="comment",
                )
            )

    def _normalize_comment(self, raw_comment: Any, path: str, index: int) -> Dict[str, str]:
        if isinstance(raw_comment, str):
            return {"id": str(index + 1), "title": "Comment", "text": raw_comment}
        if not isinstance(raw_comment, dict):
            raise ValueError(f"{path} must be a string or object")
        self._validate_allowed_keys(raw_comment, {"id", "title", "text"}, path)
        text = raw_comment.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{path}.text must be a non-empty string")
        return {
            "id": str(raw_comment.get("id") or index + 1),
            "title": str(raw_comment.get("title") or "Comment"),
            "text": text.strip(),
        }

    def _add_media_nodes(
        self,
        graph: Graph,
        parent: Node,
        raw_media_items: Any,
        overlay_path: Path,
        path: str,
    ) -> None:
        if raw_media_items in (None, []):
            return
        if not isinstance(raw_media_items, list):
            raise ValueError(f"{path} must be an array")

        for index, raw_media in enumerate(raw_media_items):
            media = self._normalize_media(raw_media, f"{path}[{index}]", index)
            asset = resolve_local_image_asset(overlay_path.parent, overlay_path, media["path"])
            node_id = f"{parent.id}--media--{_slugify(media['id'])}"
            if node_id in graph.nodes:
                raise ValueError(f"Duplicate media id under '{parent.id}': {media['id']}")
            graph.add_node(
                Node(
                    id=node_id,
                    label=media["title"] or media["alt"] or Path(asset.relative_path).stem,
                    type="image",
                    metadata={
                        "alt": media["alt"],
                        "hierarchy_parent_id": parent.id,
                        "level": 1,
                        "mime_type": asset.mime_type,
                        "natural_height": asset.height,
                        "natural_width": asset.width,
                        "source_file": overlay_path.name,
                        "source_order": len(graph.nodes),
                        "src": asset.relative_path,
                        "title": media["title"],
                    },
                )
            )
            graph.add_edge(
                Edge(
                    source_id=parent.id,
                    target_id=node_id,
                    connection_type=ConnectionType.GROUP,
                    edge_type="attachment",
                )
            )

    def _normalize_media(self, raw_media: Any, path: str, index: int) -> Dict[str, str]:
        if isinstance(raw_media, str):
            return {
                "id": str(index + 1),
                "title": "",
                "alt": "",
                "path": raw_media,
            }
        if not isinstance(raw_media, dict):
            raise ValueError(f"{path} must be a string or object")
        self._validate_allowed_keys(raw_media, {"id", "title", "alt", "path"}, path)
        media_path = raw_media.get("path")
        if not isinstance(media_path, str) or not media_path.strip():
            raise ValueError(f"{path}.path must be a non-empty string")
        return {
            "id": str(raw_media.get("id") or index + 1),
            "title": str(raw_media.get("title") or ""),
            "alt": str(raw_media.get("alt") or ""),
            "path": media_path.strip(),
        }

    def _append_node_text(self, node: Node, text: str) -> None:
        text = text.strip()
        if not text:
            return
        existing = (node.metadata or {}).get("text") or (node.metadata or {}).get("content") or ""
        combined = f"{existing}\n\n{text}" if existing else text
        node.metadata["text"] = combined
        node.metadata["content"] = combined

    def _write_node_index(self, folder: Path, resolver: "DbtReferenceResolver") -> None:
        index = {
            "nodes": [
                {
                    "unique_id": resource["unique_id"],
                    "resource_type": resource["resource_type"],
                    "project": resource["package_name"],
                    "name": resource["name"],
                    "source_name": resource["source_name"],
                    "schema": resource["schema"],
                    "references": resolver.references_for(resource["unique_id"]),
                }
                for resource in sorted(resolver.resources.values(), key=self._resource_sort_key)
            ]
        }
        with open(folder / NODE_INDEX_FILENAME, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
            f.write("\n")

    def _load_json_object(self, path: Path, label: str) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"{label} file does not exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {label} file: {path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{label} file must contain a JSON object: {path}")
        return data

    def _validate_allowed_keys(
        self,
        data: Dict[str, Any],
        allowed_keys: Set[str],
        path: str,
    ) -> None:
        unknown_keys = sorted(set(data) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"{path} has unsupported keys: {', '.join(unknown_keys)}")

    def _resource_sort_key(self, resource: Dict[str, Any]):
        return (
            str(resource.get("package_name") or ""),
            str(resource.get("resource_type") or ""),
            str(resource.get("schema") or ""),
            str(resource.get("source_name") or ""),
            str(resource.get("name") or ""),
            str(resource.get("unique_id") or ""),
        )


class DbtReferenceResolver:
    """Resolve human-friendly overlay references to dbt unique IDs."""

    def __init__(self, resources: Dict[str, Dict[str, Any]]):
        self.resources = resources
        self._index: Dict[str, List[str]] = defaultdict(list)
        self._references_by_unique_id: Dict[str, Set[str]] = defaultdict(set)
        self._build_index()

    def resolve(self, raw_ref: Any, context: str) -> str:
        """Resolve a string or object reference to one dbt unique ID."""
        if isinstance(raw_ref, str):
            return self._resolve_string(raw_ref, context)
        if isinstance(raw_ref, dict):
            return self._resolve_object(raw_ref, context)
        raise ValueError(f"{context} must be a string or object reference")

    def references_for(self, unique_id: str) -> List[str]:
        """Return usable overlay references for a dbt node."""
        return sorted(self._references_by_unique_id.get(unique_id, {unique_id}))

    def _build_index(self) -> None:
        for unique_id, resource in self.resources.items():
            resource_type = resource["resource_type"]
            project = resource["package_name"]
            name = resource["name"]

            self._add_key(unique_id, unique_id)
            self._add_key(name, unique_id)
            self._add_key(f"{resource_type}.{name}", unique_id)
            if project:
                self._add_key(f"{project}.{name}", unique_id)
                self._add_key(f"{resource_type}.{project}.{name}", unique_id)

            if resource_type == "source":
                source_name = resource.get("source_name") or ""
                if source_name:
                    self._add_key(f"{source_name}.{name}", unique_id)
                    self._add_key(f"source.{source_name}.{name}", unique_id)
                    if project:
                        self._add_key(f"{project}.{source_name}.{name}", unique_id)
                        self._add_key(f"source.{project}.{source_name}.{name}", unique_id)

    def _add_key(self, key: str, unique_id: str) -> None:
        key = str(key or "").strip()
        if not key:
            return
        if unique_id not in self._index[key]:
            self._index[key].append(unique_id)
        self._references_by_unique_id[unique_id].add(key)

    def _resolve_string(self, raw_ref: str, context: str) -> str:
        ref = raw_ref.strip()
        if not ref:
            raise ValueError(f"{context} cannot be an empty reference")
        candidates = self._index.get(ref, [])
        return self._select_candidate(ref, candidates, context)

    def _resolve_object(self, raw_ref: Dict[str, Any], context: str) -> str:
        allowed_keys = {
            "unique_id",
            "ref",
            "model",
            "source",
            "resource_type",
            "name",
            "project",
            "package",
        }
        unknown_keys = sorted(set(raw_ref) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"{context} has unsupported reference keys: {', '.join(unknown_keys)}")

        if "unique_id" in raw_ref:
            return self._resolve_string(str(raw_ref["unique_id"]), context)
        if "ref" in raw_ref:
            return self._resolve_string(str(raw_ref["ref"]), context)

        project = str(raw_ref.get("project") or raw_ref.get("package") or "").strip()
        if "model" in raw_ref:
            return self._resolve_by_fields("model", str(raw_ref["model"]), project, context)
        if "source" in raw_ref:
            source_ref = str(raw_ref["source"]).strip()
            parts = source_ref.split(".")
            if len(parts) != 2:
                raise ValueError(f"{context}.source must use source_name.table_name")
            return self._resolve_by_source(parts[0], parts[1], project, context)

        resource_type = str(raw_ref.get("resource_type") or "").strip()
        name = str(raw_ref.get("name") or "").strip()
        if not resource_type or not name:
            raise ValueError(f"{context} object reference must include resource_type and name")
        return self._resolve_by_fields(resource_type, name, project, context)

    def _resolve_by_fields(
        self,
        resource_type: str,
        name: str,
        project: str,
        context: str,
    ) -> str:
        candidates = [
            resource["unique_id"]
            for resource in self.resources.values()
            if resource["resource_type"] == resource_type
            and resource["name"] == name
            and (not project or resource["package_name"] == project)
        ]
        label = f"{resource_type}.{project + '.' if project else ''}{name}"
        return self._select_candidate(label, candidates, context)

    def _resolve_by_source(
        self,
        source_name: str,
        table_name: str,
        project: str,
        context: str,
    ) -> str:
        candidates = [
            resource["unique_id"]
            for resource in self.resources.values()
            if resource["resource_type"] == "source"
            and resource.get("source_name") == source_name
            and resource["name"] == table_name
            and (not project or resource["package_name"] == project)
        ]
        label = f"source.{project + '.' if project else ''}{source_name}.{table_name}"
        return self._select_candidate(label, candidates, context)

    def _select_candidate(self, ref: str, candidates: List[str], context: str) -> str:
        if not candidates:
            raise ValueError(f"{context} reference '{ref}' did not match any included dbt node")
        unique_candidates = sorted(set(candidates))
        if len(unique_candidates) == 1:
            return unique_candidates[0]
        shown = ", ".join(unique_candidates[:8])
        if len(unique_candidates) > 8:
            shown += ", ..."
        raise ValueError(f"{context} reference '{ref}' is ambiguous: {shown}")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    if slug:
        return slug[:80]
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
