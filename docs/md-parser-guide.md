# Markdown Parser User Guide

This guide explains how to use the Markdown parser to create Excalidraw diagrams from Markdown files.

## Overview

The Markdown parser reads one or more `.md` files in a folder and converts them into Excalidraw diagrams. The parser follows a convention where:

- **Headings with anchors** become nodes (e.g., `## Topic {#my-topic}`)
- **Heading hierarchy** creates structural parent-child relationships (H2 → H3 → H4)
- **Directive lines** define node type, tags, targets, and explicit edges
- **Inline links** create implicit related edges
- **Markdown images** become attached image nodes in the Excalidraw output

This format keeps your Markdown files readable in any editor while enabling structured diagram generation.

For workflow diagrams, the same parser can also use multiple H1 headings as first-class flow nodes connected by explicit edges. See [Markdown Flow Guide](markdown-flow-guide.md) for the current recommended pattern.

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

If a used node type or edge type is missing from `node_config.json` or `edge_config.json`, the build adds a starter entry automatically before layout and export continue.

## Mental Model

- A **node** is a box in the diagram. In Markdown, a node comes from a heading with an anchor such as `## Topic {#topic}`. The heading text becomes the node title, and the body under that heading becomes the node text.
- An **edge** is a relationship between two nodes. In Markdown, some edges are created by you in `edges` blocks such as `prereqs` or `related`, and one structural relationship is created automatically by the builder from heading nesting.
- **Node types are user-defined labels** such as `category`, `concept`, `detail`, or `principle`. You assign them with directive lines such as `> type: ...`, and `node_config.json` looks up how that type should look. These names are not built into the builder. If you omit `type`, Markdown defaults to `concept`.
- **Edge types are also user-defined names** such as `prereqs`, `related`, and `contrasts`. You define their meaning in `edge_config.json`. Markdown also has built-in hierarchy-related edge types such as `parent_child`, `link`, and `comment` that can be inferred from heading nesting.
- **Standard Markdown images stay standard in source.** A body image such as `![Flow](media/flow.png)` still renders in Markdown preview, and the builder converts it into an attached Excalidraw image.
- **Markdown has built-in special node types such as `link`, `comment`, `procedure`, and `step`.** These built-ins come with default node and edge behavior, so the minimum Markdown works without adding them to config. You only need to add them if you want to override the defaults styling.
- **Markdown also has built-in `procedure` and `step` node types.** A `procedure` is a normal structural node that can live beside any other children. Nested `step` nodes stay structurally grouped under the procedure, and `next` edges can order them as a linear flow.
- **`node_config.json` is styling only.** It answers: what should a node of type `concept` or `category` look like? This includes things like shape, colors, font size, padding, and border radius.
- **Layout is built into the builder design.** Fresh builds always use the same tree layout. In Markdown, the layout follows heading hierarchy even when a nested built-in node renders with a different edge type such as `comment` or `link`.
- **`parent_child` is the normal inferred hierarchy edge type in Markdown.** It comes from heading nesting and defines the default rendered hierarchy edge, but built-in child node types can swap that rendered edge type without changing tree placement.
- **`edge_config.json` is mostly visual behavior.** It answers: should this edge draw an arrow, behave like a visual group, or resize a parent around children? For line-like edges, it also controls color, thickness, stroke style, arrowheads, and optional long-line replacement.
- **`connection_type` is part of the builder design, not a user-invented concept.** Every edge type resolves to one of three built-in rendering modes:
  - `line`: draw a visible line or arrow between nodes
  - `group`: do not draw an arrow; group related nodes in Excalidraw
  - `enclosing_group`: do not draw an arrow; group related nodes in Excalidraw and resize the parent node around its children
- **`group` is not a node type and it does not drive Markdown tree layout.** It is a rendering choice. If you switch `parent_child` between `line` and `group`, the tree layout stays the same; only the visible arrow/group behavior changes.
- **Rendering reads config from disk only.** When the builder encounters a used type missing from config, it writes a starter config entry, reloads config from disk, and then uses that config for layout and export. The code does not keep hidden built-in rendering overrides after that bootstrap step.

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

### Node Directives (Type, Tags, Target)

Right under the heading, add blockquote directive lines to define node type, tags, targets, and edges.

**Syntax:**

```markdown
## My Concept {#my-concept}

> type: concept
> tags: database, sql
```

Explicit edges use the same directive style:

```markdown
## Review Pane {#review-pane}
> type: concept
> edge.related: review-pane-mirrors-git
> edge.contrasts: ide-approval-loop
```

**Directive Rules:**

- Directives must appear immediately under the heading, before normal body text starts
- Each directive line must start with `> ` followed by `key: value`
- `edge.<type>:` creates one or more explicit edges of that type

**Node Fields:**

- `type`: Node type for styling lookup in `node_config.json`
  - Common types: `concept`, `example`, `code`, `table`
  - Defaults to `concept` if not specified
- `target`: Used by built-in `link` nodes only
  - `https://...` opens an external URL
  - `node-id` or `#node-id` jumps to another node in the same Excalidraw canvas
- `tags`: Comma-separated list of tags (stored in metadata, can be used for filtering)

Built-in node types:

- `image`: implicit attachment node created from Markdown image syntax
- `link`: clickable node with a required `target`
- `comment`: annotation node; when nested, it keeps child placement but uses the built-in `comment` edge style
- `procedure`: workflow node for an ordered set of steps
- `step`: workflow step node, usually nested under a `procedure`

**Example:**

```markdown
## User Authentication {#user-auth}

> type: module
> tags: security, backend
```

### Edge Directives (Explicit Relationships)

Use `> edge.<type>:` directive lines to declare explicit relationships between nodes.

**Syntax:**

```markdown
## My Concept {#my-concept}

> edge.prereqs: other-concept-id
> edge.related: concept-a, concept-b
> edge.contrasts: alternative-concept
```

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
- Edge directives are optional

### Inline Links (Implicit Related Edges)

Standard markdown links to anchors automatically become `related` edges:

```markdown
See also [SQL Basics](#sql-basics) for an introduction.
```

This creates a `related` edge from the current node to `sql-basics`.

### Inline Images (Implicit Attachment Nodes)

Standard Markdown images inside a node body become attached image nodes in the Excalidraw output.

```markdown
## Deployment Notes {#deployment-notes}

The current flow uses this diagram ![Flow](media/flow.png) during rollouts.
```

Rules:

- Any Markdown image `![alt](path)` in body text becomes an attached image node for the current heading node.
- Image paths must reference local files inside the diagram folder.
- Paths are resolved relative to the Markdown file that contains the image.
- The builder removes the Markdown image token from the node's rendered text in Excalidraw, so the text box does not show raw `![...]`.
- Initial image size comes from the source file dimensions and is capped to a reasonable first-pass size.
- After you resize or reposition the image in Excalidraw, that geometry is preserved in `positions.json` like any other node.
- The built-in inferred edge type for these image children is `attachment`, which defaults to `group`.

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

If a nested node is `type: comment`, it still participates in the same hierarchy and layout, but its inferred edge renders as `comment` instead of `parent_child`.

If a nested node is `type: step` and its parent is `type: procedure`, it still participates in the same hierarchy and layout, but its inferred edge renders as `procedure_step` instead of `parent_child`. The built-in `procedure_step` edge defaults to `group`, so you usually see the explicit `next` arrows rather than duplicate hierarchy arrows.

### Built-in Procedure Nodes

Use `type: procedure` when you want a node to own an ordered set of steps without turning each step into a deeper heading level.

```markdown
## Release Management {#release-management}

### Monitoring {#monitoring}
> type: concept

### Deploy Service {#deploy-service}
> type: procedure

#### Check Secrets {#deploy-check-secrets}
> type: step
> edge.next: deploy-build-image

#### Build Image {#deploy-build-image}
> type: step
> edge.next: deploy-push-image

#### Push Image {#deploy-push-image}
> type: step
```

Rules:

- A `procedure` node is just another structural child. It can live beside normal children under the same parent.
- Nested `step` nodes under the same `procedure` are the members of that procedure.
- If no `next` edges are declared, steps are laid out in source order.
- If any `next` edges are declared for a procedure, they must form one complete chain across all of that procedure's step children.
- `next` edges must connect `step` nodes within the same `procedure`.

### Built-in Link Nodes

Use `type: link` when you want a node to be clickable rather than explanatory.

```markdown
### Snowflake Docs {#snowflake-docs}

> type: link
> target: https://docs.snowflake.com/
```

Or for an internal jump:

```markdown
### Jump To Workflow {#jump-to-workflow}

> type: link
> target: #practical-workflow
```

Rules:

- A `link` node must have exactly one `target`.
- `target` is inferred automatically:
  - matches a node id or starts with `#` → internal node jump
  - anything else → external URL/string link
- If a nested `link` node does not declare an explicit `link:` edge, the builder automatically creates a built-in `link` edge from its parent to the link node.
- If you do declare explicit `edge.link:` directives, those explicit edges are used instead of the default parent link edge.

### Built-in Comment Nodes

Use `type: comment` when you want a child node to behave like an annotation while still staying in the tree layout.

```markdown
### Review Pane Is Git {#review-pane-mirrors-git}

#### Comment: Includes your own changes too {#review-pane-note}

> type: comment

The review pane reflects the whole repo state, not just Codex edits.
```

Rules:

- A nested `comment` node is still a structural child for layout.
- Its inferred parent edge uses the built-in `comment` edge style instead of `parent_child`.
- You can override the node or edge visuals by adding `comment` to `node_config.json` or `edge_config.json`.

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
  "layout": {
    "direction": "left-right",
    "level_spacing": 180,
    "sibling_spacing": 40,
    "root_spacing": 100,
    "start_x": 120,
    "start_y": 120
  }
}
```

**Options:**

- `parser_type`: Must be `"md"` or `"markdown"` for Markdown parser
- `layout.direction`: Tree direction. One of `"left-right"`, `"right-left"`, `"top-down"`, `"bottom-up"`
- `layout.level_spacing`: Gap between parent and child levels
- `layout.sibling_spacing`: Gap between sibling subtrees
- `layout.root_spacing`: Gap between separate top-level trees
- `layout.start_x`, `layout.start_y`: Starting position for the initial layout

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
    "connection_type": "line",
    "arrow_end": "arrow"
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
- `attachment`: Built-in edge type used by Markdown image attachments
- `comment`: Built-in edge type used by nested `comment` nodes
- `link`: Built-in edge type used by `link` nodes
- `prereqs`: From edge directives (directed dependency)
- `related`: From edge directives or inline links (association)
- `contrasts`: From edge directives (opposition)

**Important:**

- Heading hierarchy always defines the tree layout in Markdown.
- Set `parent_child.connection_type` to `"line"` if you want visible hierarchy arrows.
- Set `parent_child.connection_type` to `"group"` if you want the same layout without arrows, plus Excalidraw grouping.
- `comment` nodes are Markdown-only and use the built-in `comment` edge style by default when nested.
- Markdown images are Markdown-only attachments and use the built-in `attachment` edge style by default.
- `link` nodes are Markdown-only and use the built-in `link` edge style by default.

**Line Styling Options:**

- `connection_type`: Must be `"line"` for arrows
- `color`: Line color (hex)
- `stroke_width`: Line thickness
- `stroke_style`: `"solid"`, `"dashed"`, `"dotted"`
- `arrow_start`: `null`, `"arrow"`, `"circle"`
- `arrow_end`: `null`, `"arrow"`, `"circle"`
- `max_length`: Optional center-to-center maximum length in pixels. Longer positioned lines are replaced with two generated internal-link nodes whose positions are saved like normal nodes.
- `show_label`: Whether non-empty line-edge labels are rendered. Defaults to `true`.
- `label_color`: Label color. Defaults to the line color when omitted or `null`.
- `label_font_size`: Label font size. Defaults to `14`.

## Workflow

### 1. Create Your Markdown Files

1. Create a folder for your diagram
2. Add one or more `.md` files with your content
3. Use `{#id}` anchors on headings you want as nodes
4. Add `> type:` or other node directives
5. Add `> edge.<type>:` directives for explicit relationships
6. Create configuration files (`config.json`, `node_config.json`, `edge_config.json`)

### 2. Build the Diagram

Run the build command:

```bash
uv run excali-builder your-diagram-folder
```

To discard the current saved layout and generate a fresh first-pass layout while preserving saved node sizes:

```bash
uv run excali-builder --full-refresh your-diagram-folder
```

This will:

1. Sync positions from any existing `output.excalidraw` file (if present)
2. Parse all `.md` files in the folder
3. Apply saved positions from `positions.json` (if present)
4. Layout new nodes using the configured tree settings
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

> type: concept

> edge.prereqs: sql-basics
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
    "connection_type": "group"
  }
}
```

This creates the same tree layout, but hides the parent-child arrows and groups the related nodes in Excalidraw.

### Example 2: Learning Path with Prerequisites

**learning.md:**

````markdown
## Fundamentals {#fundamentals}

> type: concept

Basic building blocks.

## Intermediate {#intermediate}

> type: concept

> edge.prereqs: fundamentals

Builds on fundamentals.

## Advanced {#advanced}

> type: concept

> edge.prereqs: intermediate
> edge.related: fundamentals

Advanced topics with deep connections.
````

### Example 3: Resource Link Node

```markdown
## Query Profiling {#query-profiling}

Core notes about reading Snowflake query performance.

### Snowflake Docs {#snowflake-docs}

> type: link
> target: https://docs.snowflake.com/
```

This creates a clickable link node. Because it is nested under `query-profiling`, the builder automatically adds the built-in `link` edge if you do not explicitly define one.

### Example 4: Nested Comment Node

```markdown
## Review Pane {#review-pane}

The review pane shows the repo state.

### Note About Mixed Diffs {#review-pane-note}

> type: comment

This can include your own local edits, not only Codex edits.
```

This creates a normal child in the tree layout, but its inferred edge to `review-pane` uses the built-in `comment` style instead of `parent_child`.

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

### Example 5: Contrasting Concepts

````markdown
## SQL Databases {#sql-db}

> type: concept
> tags: database

> edge.contrasts: nosql-db

Relational databases with structured schemas.

## NoSQL Databases {#nosql-db}

> type: concept
> tags: database

> edge.contrasts: sql-db

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
