import json
import tempfile
import unittest
from pathlib import Path

from excali_builder.builder import ExcaliBuilder
from excali_builder.config.schema import GlobalConfig, LayoutConfig
from excali_builder.core.edge import ConnectionType, Edge
from excali_builder.core.graph import Graph
from excali_builder.core.node import Node
from excali_builder.parsers.dbt import DbtManifestParser
from excali_builder.serve.watcher import FolderWatchState


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _model(project: str, name: str, depends_on=None, description: str = "") -> dict:
    return {
        "unique_id": f"model.{project}.{name}",
        "resource_type": "model",
        "package_name": project,
        "name": name,
        "schema": "mart",
        "database": "warehouse",
        "description": description,
        "config": {"materialized": "table"},
        "depends_on": {"nodes": depends_on or []},
    }


def _source(project: str, source_name: str, table_name: str) -> dict:
    return {
        "unique_id": f"source.{project}.{source_name}.{table_name}",
        "resource_type": "source",
        "package_name": project,
        "source_name": source_name,
        "name": table_name,
        "schema": "raw",
        "database": "warehouse",
        "description": "",
    }


class DbtParserTests(unittest.TestCase):
    def test_builder_passes_dbt_parser_options_from_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo = root / "repo"
            folder = root / "local-notes" / "lineage"
            folder.mkdir(parents=True)

            manifest = {
                "nodes": {"model.finance.fct_orders": _model("finance", "fct_orders")},
                "parent_map": {},
            }
            _write_manifest(repo / "finance" / "target" / "manifest.json", manifest)
            (folder / "config.json").write_text(
                json.dumps(
                    {
                        "parser_type": "dbt",
                        "parser_options": {
                            "dbt_project_root": str(repo),
                            "manifest_paths": ["finance/target/manifest.json"],
                        },
                        "layout": {"algorithm": "dag"},
                    }
                ),
                encoding="utf-8",
            )

            output_path = ExcaliBuilder().build_from_folder(str(folder))
            self.assertTrue(Path(output_path).exists())

    def test_dbt_parser_merges_manifests_and_applies_overlay(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo = root / "repo"
            folder = root / "local-notes" / "lineage"
            folder.mkdir(parents=True)

            finance_manifest = {
                "nodes": {
                    "model.finance.stg_orders": _model(
                        "finance",
                        "stg_orders",
                        depends_on=["source.finance.raw.orders"],
                    ),
                    "model.finance.fct_orders": _model(
                        "finance",
                        "fct_orders",
                        depends_on=[
                            "model.finance.stg_orders",
                            "model.marketing.dim_customers",
                        ],
                        description="Manifest description.",
                    ),
                    "test.finance.unique_fct_orders_order_id": {
                        "unique_id": "test.finance.unique_fct_orders_order_id",
                        "resource_type": "test",
                        "package_name": "finance",
                        "name": "unique_fct_orders_order_id",
                        "depends_on": {"nodes": ["model.finance.fct_orders"]},
                    },
                },
                "sources": {
                    "source.finance.raw.orders": _source("finance", "raw", "orders"),
                },
                "parent_map": {
                    "model.finance.stg_orders": ["source.finance.raw.orders"],
                    "model.finance.fct_orders": [
                        "model.finance.stg_orders",
                        "model.marketing.dim_customers",
                    ],
                    "test.finance.unique_fct_orders_order_id": ["model.finance.fct_orders"],
                },
            }
            marketing_manifest = {
                "nodes": {
                    "model.marketing.dim_customers": _model("marketing", "dim_customers"),
                },
                "parent_map": {},
            }
            _write_manifest(repo / "finance" / "target" / "manifest.json", finance_manifest)
            _write_manifest(repo / "marketing" / "target" / "manifest.json", marketing_manifest)

            (folder / "dbt_overlay.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "groups": {
                            "Finance": {
                                "Staging": ["stg_orders"],
                                "Marts": ["finance.fct_orders"],
                            }
                        },
                        "nodes": {
                            "finance.fct_orders": {
                                "description": "Overlay detail.",
                                "comments": [
                                    {
                                        "id": "grain",
                                        "title": "Grain",
                                        "text": "One row per order.",
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            graph = DbtManifestParser().parse(
                folder,
                {
                    "dbt_project_root": str(repo),
                    "manifest_paths": [
                        "finance/target/manifest.json",
                        "marketing/target/manifest.json",
                    ],
                },
            )

            edge_pairs = {
                (edge.edge_type, edge.source_id, edge.target_id, edge.connection_type)
                for edge in graph.edges
            }

            self.assertIn("model.finance.fct_orders", graph.nodes)
            self.assertIn("model.marketing.dim_customers", graph.nodes)
            self.assertNotIn("test.finance.unique_fct_orders_order_id", graph.nodes)
            self.assertIn(
                (
                    "lineage",
                    "source.finance.raw.orders",
                    "model.finance.stg_orders",
                    ConnectionType.LINE,
                ),
                edge_pairs,
            )
            self.assertIn(
                (
                    "lineage",
                    "model.marketing.dim_customers",
                    "model.finance.fct_orders",
                    ConnectionType.LINE,
                ),
                edge_pairs,
            )
            self.assertIn("overlay.group.finance", graph.nodes)
            self.assertIn("overlay.group.finance-staging", graph.nodes)
            self.assertIn(
                (
                    "group_member",
                    "overlay.group.finance-staging",
                    "model.finance.stg_orders",
                    ConnectionType.CONTAINER,
                ),
                edge_pairs,
            )
            self.assertIn("model.finance.fct_orders--comment--grain", graph.nodes)
            self.assertIn(
                "Overlay detail.",
                graph.nodes["model.finance.fct_orders"].metadata["text"],
            )
            self.assertTrue((folder / "dbt_node_index.json").exists())

    def test_dbt_overlay_rejects_ambiguous_bare_references(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            manifest = {
                "nodes": {
                    "model.project_a.shared_model": _model("project_a", "shared_model"),
                    "model.project_b.shared_model": _model("project_b", "shared_model"),
                },
                "parent_map": {},
            }
            _write_manifest(folder / "target" / "manifest.json", manifest)
            (folder / "dbt_overlay.json").write_text(
                json.dumps({"nodes": {"shared_model": {"description": "Ambiguous."}}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                DbtManifestParser().parse(folder, {})

    def test_dbt_overlay_validates_media_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            manifest = {
                "nodes": {"model.finance.fct_orders": _model("finance", "fct_orders")},
                "parent_map": {},
            }
            _write_manifest(folder / "target" / "manifest.json", manifest)
            (folder / "dbt_overlay.json").write_text(
                json.dumps({"nodes": {"fct_orders": {"media": ["media/missing.png"]}}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "does not exist"):
                DbtManifestParser().parse(folder, {})


class DbtDagLayoutTests(unittest.TestCase):
    def test_builder_uses_dag_layout_when_configured(self):
        graph = Graph()
        source = Node(id="source", label="Source", width=100, height=50)
        staging = Node(id="staging", label="Staging", width=100, height=50)
        mart = Node(id="mart", label="Mart", width=100, height=50)
        for node in [source, staging, mart]:
            graph.add_node(node)
        graph.add_edge(
            Edge(
                source_id="source",
                target_id="staging",
                connection_type=ConnectionType.LINE,
                edge_type="lineage",
            )
        )
        graph.add_edge(
            Edge(
                source_id="staging",
                target_id="mart",
                connection_type=ConnectionType.LINE,
                edge_type="lineage",
            )
        )

        config = GlobalConfig(
            layout=LayoutConfig(
                algorithm="dag",
                direction="left-right",
                level_spacing=100,
                sibling_spacing=20,
                start_x=10,
                start_y=30,
            )
        )
        ExcaliBuilder()._apply_layout_to_new_nodes(graph, config)

        self.assertLess(source.x, staging.x)
        self.assertLess(staging.x, mart.x)
        self.assertEqual(source.y, 30)


class DbtWatcherTests(unittest.TestCase):
    def test_watcher_tracks_external_manifest_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder = root / "local-notes"
            manifest_path = root / "repo" / "target" / "manifest.json"
            folder.mkdir()
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text("initial", encoding="utf-8")

            watch_state = FolderWatchState(folder, extra_paths=[manifest_path])
            manifest_path.write_text("changed", encoding="utf-8")
            changes = watch_state.collect_changes()

        self.assertIn(manifest_path.resolve(), [path.resolve() for path in changes.source_paths])


if __name__ == "__main__":
    unittest.main()
