# AI Agent Guide: Markdown Format for excali-builder

This document is the technical reference for writing Markdown input that excali-builder can parse into an Excalidraw diagram.
It covers syntax, parser behavior, config files, and build-facing validation only.

It does not define what makes a good mind map, how deeply branches should be decomposed, or which concepts deserve nodes.
Those editorial and semantic rules belong in the content repository that owns the diagrams.

## Your Task

When creating a Markdown diagram folder for excali-builder, include:

1. One or more `.md` files containing the diagram nodes
2. `config.json`
3. `node_config.json`
4. `edge_config.json`

Run `excali-builder <folder>` to generate the Excalidraw diagram.

---

## Markdown Syntax Rules (MUST follow exactly)

### Nodes = Headings with `{#id}` anchors

Every diagram node MUST be a Markdown heading with a `{#id}` anchor:

```markdown
## Node Title {#node-id}
```

**Rules:**

- Only headings with `{#id}` become nodes. Headings without anchors are ignored by the parser.
- IDs must be globally unique across ALL `.md` files in the folder.
- IDs must be kebab-case, using only `[a-z0-9-]` characters. The regex is `[\w-]+`.
- Use heading levels to express hierarchy:
  - `##` (H2) for a top-level node
  - `###` (H3) for a child of the nearest preceding H2
  - `####` (H4) for a child of the nearest preceding H3, and so on
- H1 (`#`) headings with `{#id}` are valid nodes too, but typically reserved for a single root/overview node per file.
- A heading without `{#id}` is NOT a node — it's just formatting text within the parent node's content.

### Parent-Child Hierarchy (Automatic)

Parent-child relationships are inferred from heading levels. You do NOT declare them manually.

```markdown
## Parent Node {#parent-node}

### First Child {#first-child}

#### Nested Child {#nested-child}

### Second Child {#second-child}
```

This automatically creates:
- `parent-node` -> `first-child` (parent_child)
- `first-child` -> `nested-child` (parent_child)
- `parent-node` -> `second-child` (parent_child)

**Important**: The parent is determined by the nearest preceding heading with a LOWER level number (fewer `#`). If you write two `##` headings in sequence, the second one is NOT a child of the first — they are siblings.

**Special case**: If a nested node uses `> type: comment`, it still stays in the same hierarchy and layout, but the inferred edge to its parent uses the built-in `comment` style instead of `parent_child`.

### Node Directives (Optional, immediately after heading)

To set the node type or tags, add directive lines immediately after the heading:

```markdown
## My Node {#my-node}

> type: box
> tags: tag-a, tag-b
```

**Rules:**

- Each directive line must start with `> ` followed by `key: value`.
- Directives must appear before normal body text starts.
- If no `type` directive is present, the node type defaults to `concept`.

**Supported directive fields:**

- `type`: Node type key. For normal nodes this must match a key in `node_config.json`; if omitted, the type defaults to `concept`.
- `target`: Required for `type: link`.
- `tags`: Comma-separated list of tags for filtering/categorization.

`comment` and `link` are built-in node types with special edge behavior when nested, described below.

### Edge Directives (Optional, after node directives)

To declare explicit relationships between nodes, add `edge.<type>` directive lines:

```markdown
## My Node {#my-node}

> type: box

> edge.prereqs: other-id-a, other-id-b
> edge.related: other-id-c
> edge.contrasts: other-id-d
```

**Edge types you can use:**

| Type | Parser behavior |
|------|-----------------|
| `prereqs` | Creates explicit directed edges to the listed targets, styled by `edge_config.json` |
| `related` | Creates explicit undirected edges to the listed targets, styled by `edge_config.json` |
| `contrasts` | Creates explicit undirected edges to the listed targets, styled by `edge_config.json` |

**Rules:**

- Each line is `edge.<type>: id1, id2, id3` (comma-separated target IDs).
- Target IDs must match `{#id}` anchors on other headings.
- Edges to non-existent IDs are silently dropped (no error, but the edge won't appear).
- Do NOT declare `parent_child` edges here — those are automatic from heading hierarchy.
- `prereqs` is directional. `related` and `contrasts` are non-directional.

### Inline Links (Optional, creates implicit related edges)

Inside the body text of any node, standard Markdown links to anchors create `related` edges:

```markdown
## Source Node {#source-node}

This body text links to [Target Node](#target-node).
```

This creates a `related` edge from `source-node` to `target-node`.

**Rules:**

- The syntax is `[Any Display Text](#target-id)`.
- Only links starting with `#` are parsed as edges. External URLs are ignored.
- These always create `related` edges. If you need `prereqs` or `contrasts`, use edge directives.

### Node Content (Optional, for context)

Any text between a heading and the next heading, excluding directive lines, is stored as the node's body content metadata.

```markdown
## Node With Body {#node-with-body}

> type: box

This text is stored as node body content.
```

---

## File Organization

### When to use one file vs multiple files

Markdown diagrams can use one `.md` file or multiple `.md` files.

**Cross-file references**: IDs are global. A node in `file-a.md` can reference a node in `file-b.md` by ID in edge directives and inline links.

### File ordering

Files are parsed alphabetically. If two files define the same `{#id}`, the first file wins. Avoid duplicate IDs.

---

## Config Files (ALWAYS include these three)

### config.json

Minimal example:

```json
{
  "parser_type": "md",
  "layout": {
    "direction": "left-right",
    "level_spacing": 180,
    "sibling_spacing": 40
  }
}
```

### node_config.json

Define a style for each node type used by the Markdown files.
The keys are examples only; choose the node type keys required by the content repository.
If a node omits `type`, configure the default `concept` type.

```json
{
  "box": {
    "color": "#1a1a2e",
    "backgroundColor": "#e2e8f0",
    "shape": "rectangle",
    "font_size": 18,
    "padding": 16,
    "borderRadius": 12
  },
  "link": {
    "color": "#1E40AF",
    "backgroundColor": "#EFF6FF",
    "shape": "rectangle",
    "font_size": 14,
    "padding": 12,
    "borderRadius": 8
  }
}
```

### edge_config.json

Minimal example:

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

### Built-in link nodes

Use `type: link` when you want a clickable link node:

```markdown
### External Link {#external-link}

> type: link
> target: https://example.com/
```

or:

```markdown
### Internal Link {#internal-link}

> type: link
> target: #target-node
```

If a nested link node does not declare an explicit `link:` edge, the builder automatically adds the built-in `link` edge to its parent.

### Built-in comment nodes

Use `type: comment` when you want a nested comment node that still participates in hierarchy and layout:

```markdown
### Parent Node {#comment-parent-node}

#### Comment Node {#comment-node}

> type: comment

Comment body text.
```

If a nested comment node does not declare anything special, the builder automatically adds the built-in `comment` edge to its parent while keeping the normal child placement in the tree.

---

## Complete Syntax Example

This example demonstrates syntax, directives, cross-links, and required files.
It is not a recommendation about content scope, node semantics, branch depth, or map design.

### diagram.md

````markdown
## Root Node {#root-node}

> type: box

Body content is stored as metadata on the node.

### Child Node {#child-node}

> type: box

This child is connected to the root by an inferred `parent_child` edge.

### Explicit Edge Node {#explicit-edge-node}

> type: box

> edge.related: child-node

This node has an explicit `related` edge to `child-node`.

#### Nested Node {#nested-node}

> type: box

This node is connected to `explicit-edge-node` by an inferred `parent_child` edge.

### Link Node {#link-node}

> type: link
> target: https://example.com/

Nested `type: link` nodes use the built-in link edge behavior.
````

### config.json

```json
{
  "parser_type": "md",
  "layout": {
    "direction": "left-right",
    "level_spacing": 180,
    "sibling_spacing": 40
  }
}
```

### node_config.json

```json
{
  "box": {
    "color": "#1a1a2e",
    "backgroundColor": "#e2e8f0",
    "shape": "rectangle",
    "font_size": 18,
    "padding": 16,
    "borderRadius": 12
  },
  "link": {
    "color": "#1E40AF",
    "backgroundColor": "#EFF6FF",
    "shape": "rectangle",
    "font_size": 14,
    "padding": 12,
    "borderRadius": 8
  }
}
```

### edge_config.json

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

---

## Checklist Before Submitting

Before you output your files, verify:

- [ ] Every heading that should be a node has a `{#kebab-case-id}` anchor
- [ ] All IDs are unique across all files
- [ ] IDs contain only `[a-zA-Z0-9_-]` characters (regex: `[\w-]+`)
- [ ] Edge targets reference IDs that exist somewhere in the files
- [ ] Directional edge types such as `prereqs` point from the intended source node to the intended target node
- [ ] Node directives use `> key: value` immediately under the heading
- [ ] Explicit relationships use `> edge.<type>: target-id` syntax
- [ ] No duplicate edges (same source → target with same type)
- [ ] Node types match keys in `node_config.json`
- [ ] Any built-in node types used by the diagram have the required directives, such as `target` for `type: link`
- [ ] All three config files are included

---

## Output Format

When asked to provide a Markdown diagram folder in chat, output each file with its filename as a header:

```
### filename.md
<file content>

### config.json
<file content>

### node_config.json
<file content>

### edge_config.json
<file content>
```

Save these files into a folder and run `excali-builder <folder>` to generate the diagram.
