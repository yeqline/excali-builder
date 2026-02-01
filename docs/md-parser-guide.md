# Markdown Parser User Guide

This guide explains how to use the Markdown parser to create Excalidraw diagrams from Markdown files.

## Overview

The Markdown parser reads one or more `.md` files in a folder and converts them into Excalidraw diagrams. The parser follows a convention where:

- **Headings with anchors** become nodes (e.g., `## Topic {#my-topic}`)
- **Heading hierarchy** creates parent-child relationships (H2 → H3 → H4)
- **Meta blocks** define node type and tags
- **Edges blocks** declare explicit relationships (prereqs, related, contrasts)
- **Inline links** create implicit related edges

This format keeps your Markdown files readable in any editor while enabling structured diagram generation.

## Project Structure

A diagram project folder should contain:

```
your-diagram/
├── *.md                  # One or more Markdown files
├── node_config.json      # Node styling configuration
├── edge_config.json      # Edge styling configuration
├── config.json           # General configuration (parser_type: "md")
├── positions.json        # Layout positions (auto-generated after sync)
└── output.excalidraw     # Generated Excalidraw file
```

## Markdown Format

### Nodes (Headings with Anchors)

Every concept you want as a box on the canvas is a Markdown heading with a stable ID anchor.

**Syntax:**

```markdown
## Heading Title {#node-id}
```

**Rules:**

- Use H1-H6 for different levels of hierarchy
- The `{#node-id}` anchor provides a stable, unique ID for the node
- IDs should be unique across all files in the folder
- IDs should be kebab-case (e.g., `my-concept`, `database-layer`)

**Example:**

```markdown
## SQL Joins {#sql-joins}

### Inner Join {#inner-join}

### Outer Join {#outer-join}
```

This creates three nodes: `sql-joins` (parent) with two children: `inner-join` and `outer-join`.

### Meta Block (Node Type and Tags)

Right under the heading, add a blockquote with `[!meta]` to define node type and tags.

**Syntax:**

```markdown
## My Concept {#my-concept}

> [!meta]
> type: concept
> tags: database, sql
```

**Meta Fields:**

- `type`: Node type for styling lookup in `node_config.json`
  - Common types: `concept`, `example`, `code`, `table`
  - Defaults to `concept` if not specified
- `tags`: Comma-separated list of tags (stored in metadata, can be used for filtering)

**Example:**

```markdown
## User Authentication {#user-auth}

> [!meta]
> type: module
> tags: security, backend
```

### Edges Block (Explicit Relationships)

Use a code fence named `edges` to declare explicit relationships between nodes.

**Syntax:**

````markdown
## My Concept {#my-concept}

```edges
prereqs: other-concept-id
related: concept-a, concept-b
contrasts: alternative-concept
```
````

**Edge Types:**

| Type        | Description                                    |
| ----------- | ---------------------------------------------- |
| `prereqs`   | Learning dependencies. Directed: source → target |
| `related`   | Lateral associations. Typically undirected     |
| `contrasts` | Opposing/alternative ideas                     |

**Rules:**

- Use comma-separated IDs on one line
- IDs reference the `{#id}` anchors of other nodes
- Edges to non-existent nodes are automatically removed
- The `edges` block is optional

### Inline Links (Implicit Related Edges)

Standard markdown links to anchors automatically become `related` edges:

```markdown
See also [SQL Basics](#sql-basics) for an introduction.
```

This creates a `related` edge from the current node to `sql-basics`.

### Parent-Child Relationships

Parent-child relationships are automatically inferred from heading hierarchy:

```markdown
## Parent Node {#parent}

### Child A {#child-a}

### Child B {#child-b}

#### Grandchild {#grandchild}
```

This creates:
- `parent` → `child-a` (parent_child edge)
- `parent` → `child-b` (parent_child edge)
- `child-b` → `grandchild` (parent_child edge)

### YAML Front Matter (Optional)

YAML front matter at the beginning of files is ignored by the parser:

```markdown
---
title: My Document
author: John
---

## First Concept {#first-concept}
```

## Configuration Files

### config.json

General configuration for the diagram project.

```json
{
  "parser_type": "md",
  "default_layout": "radial"
}
```

**Options:**

- `parser_type`: Must be `"md"` or `"markdown"` for Markdown parser
- `default_layout`: Default layout algorithm for nodes without positions
  - `"radial"`: Circular hierarchical layout (default)
  - `"tree"`: Traditional tree layout

### node_config.json

Defines styling for different node types. Each node type can have its own visual style.

```json
{
  "concept": {
    "color": "#1E40AF",
    "backgroundColor": "#EFF6FF",
    "shape": "rectangle",
    "font_size": 14,
    "padding": 12,
    "borderRadius": 8
  },
  "example": {
    "color": "#065F46",
    "backgroundColor": "#D1FAE5",
    "shape": "rectangle",
    "font_size": 12,
    "padding": 10,
    "borderRadius": 4
  },
  "code": {
    "color": "#1F2937",
    "backgroundColor": "#F3F4F6",
    "shape": "rectangle",
    "font_size": 12,
    "padding": 8,
    "borderRadius": 0
  }
}
```

**Node Type Configuration Options:**

- `color`: Text color (hex color code)
- `backgroundColor`: Background color of the node
- `shape`: Node shape (`"rectangle"`, `"ellipse"`, `"diamond"`)
- `font_size`: Font size in pixels
- `padding`: Internal padding around text
- `borderRadius`: Corner radius for rectangles

### edge_config.json

Defines styling and behavior for different edge types.

```json
{
  "parent_child": {
    "connection_type": "container",
    "placement": "outside",
    "direction": "bottom",
    "child_offset": 30,
    "group_padding": 20
  },
  "prereqs": {
    "connection_type": "line",
    "color": "#DC2626",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow"
  },
  "related": {
    "connection_type": "line",
    "color": "#6B7280",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": null
  },
  "contrasts": {
    "connection_type": "line",
    "color": "#F59E0B",
    "stroke_width": 2,
    "stroke_style": "dashed",
    "arrow_start": null,
    "arrow_end": null
  }
}
```

**Edge Types from Markdown:**

- `parent_child`: Auto-generated from heading hierarchy
- `prereqs`: From edges block (directed dependency)
- `related`: From edges block or inline links (association)
- `contrasts`: From edges block (opposition)

**Container Connection Options:**

- `connection_type`: Must be `"container"` for grouping
- `placement`: `"inside"` or `"outside"` - child positioning
- `direction`: `"top"`, `"bottom"`, `"left"`, `"right"`, `"radial"`
- `child_offset`: Spacing between parent and children
- `group_padding`: Padding around grouped children

**Line Connection Options:**

- `connection_type`: Must be `"line"` for arrows
- `color`: Line color (hex)
- `stroke_width`: Line thickness
- `stroke_style`: `"solid"`, `"dashed"`, `"dotted"`
- `arrow_start`: `null`, `"arrow"`, `"circle"`
- `arrow_end`: `null`, `"arrow"`, `"circle"`

## Workflow

### 1. Create Your Markdown Files

1. Create a folder for your diagram
2. Add one or more `.md` files with your content
3. Use `{#id}` anchors on headings you want as nodes
4. Add meta blocks for node types
5. Add edges blocks for explicit relationships
6. Create configuration files (`config.json`, `node_config.json`, `edge_config.json`)

### 2. Build the Diagram

Run the build command:

```bash
uv run excali-builder your-diagram-folder
```

This will:

1. Sync positions from any existing `output.excalidraw` file (if present)
2. Parse all `.md` files in the folder
3. Apply saved positions from `positions.json` (if present)
4. Layout new nodes using the configured layout algorithm
5. Generate `output.excalidraw`

### 3. Edit in Excalidraw

1. Open `output.excalidraw` in Excalidraw
2. Move nodes to desired positions
3. Resize nodes if needed
4. Save the file

### 4. Sync Positions

The next time you run the build command, it will automatically:

1. Read the `output.excalidraw` file
2. Extract node positions and sizes
3. Save them to `positions.json`
4. Use these positions when rebuilding

**Note**: Only node positions and sizes are synced. Content (titles, relationships) always comes from your Markdown files.

## Multi-File Support

The Markdown parser supports multiple `.md` files in a folder:

```
my-knowledge-base/
├── databases.md          # Contains database-related concepts
├── authentication.md     # Contains auth-related concepts
├── architecture.md       # Contains architecture concepts
├── node_config.json
├── edge_config.json
├── config.json
└── output.excalidraw
```

**Cross-file linking:**

```markdown
<!-- In databases.md -->
## SQL Basics {#sql-basics}

This is the foundation for [Query Optimization](#query-optimization).
```

```markdown
<!-- In architecture.md -->
## Query Optimization {#query-optimization}

> [!meta]
> type: concept

```edges
prereqs: sql-basics
```
```

The parser will:
- Parse all `.md` files alphabetically
- Resolve cross-file references by node ID
- Remove edges to non-existent nodes

## Examples

### Example 1: Simple Hierarchy

**content.md:**

```markdown
# My Knowledge Base

## Root Topic {#root}

> [!meta]
> type: concept

Main entry point for the topic.

### Subtopic A {#subtopic-a}

Details about subtopic A.

### Subtopic B {#subtopic-b}

Details about subtopic B.
```

**edge_config.json:**

```json
{
  "parent_child": {
    "connection_type": "container",
    "placement": "outside",
    "direction": "bottom",
    "child_offset": 30,
    "group_padding": 20
  }
}
```

This creates a hierarchy where `subtopic-a` and `subtopic-b` are grouped with `root` and arranged below it.

### Example 2: Learning Path with Prerequisites

**learning.md:**

````markdown
## Fundamentals {#fundamentals}

> [!meta]
> type: concept

Basic building blocks.

## Intermediate {#intermediate}

> [!meta]
> type: concept

```edges
prereqs: fundamentals
```

Builds on fundamentals.

## Advanced {#advanced}

> [!meta]
> type: concept

```edges
prereqs: intermediate
related: fundamentals
```

Advanced topics with deep connections.
````

**edge_config.json:**

```json
{
  "prereqs": {
    "connection_type": "line",
    "color": "#DC2626",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow"
  },
  "related": {
    "connection_type": "line",
    "color": "#6B7280",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": null
  }
}
```

This creates a directed learning path: `fundamentals` → `intermediate` → `advanced`, with a related link back from `advanced` to `fundamentals`.

### Example 3: Contrasting Concepts

````markdown
## SQL Databases {#sql-db}

> [!meta]
> type: concept
> tags: database

```edges
contrasts: nosql-db
```

Relational databases with structured schemas.

## NoSQL Databases {#nosql-db}

> [!meta]
> type: concept
> tags: database

```edges
contrasts: sql-db
```

Schema-flexible databases for varied data.
````

This creates two nodes connected with a dashed line (no arrow) indicating contrast.

## Tips and Best Practices

1. **Stable Node IDs**: Use stable, meaningful IDs in `{#id}` anchors. Changing IDs will lose saved positions.

2. **Single Source of Truth**: Keep your content in Markdown files. The Excalidraw file is regenerated from source.

3. **Meaningful Edge Types**: Use appropriate edge types:
   - `prereqs`: For directed dependencies
   - `related`: For lateral associations
   - `contrasts`: For opposing alternatives
   - `parent_child`: Auto-generated from heading hierarchy

4. **File Organization**: For large knowledge bases, split content across multiple files by topic or domain.

5. **Position Persistence**: After editing positions in Excalidraw, run the build command to sync positions. They'll be preserved in future builds.

6. **Consistent IDs**: Use a naming convention for IDs (e.g., `domain-concept` like `db-normalization`, `auth-oauth`).

## Troubleshooting

### Nodes not appearing

- Check that the heading has a valid `{#id}` anchor
- Ensure the ID is unique across all files
- Verify the Markdown syntax is correct

### Edges not showing

- Verify that both source and target node IDs exist
- Check that edge types are defined in `edge_config.json`
- Ensure the `edges` block uses correct syntax

### Parent-child relationships not working

- Verify heading levels are correct (H2 → H3 → H4)
- Check that `parent_child` edge type is defined in `edge_config.json`
- Ensure headings have valid `{#id}` anchors

### Positions not persisting

- Make sure you save the `output.excalidraw` file in Excalidraw
- Run the build command after saving to sync positions
- Check that `positions.json` is being created/updated

### Cross-file links not working

- Ensure the target node ID exists in one of the `.md` files
- Verify the ID matches exactly (IDs are case-sensitive)
- Check that all `.md` files are in the same folder

