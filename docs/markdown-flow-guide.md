# Markdown Flow Guide

This guide explains how to create workflow or flowchart-style diagrams with the existing Markdown parser. It does not require a separate parser or new syntax.

## Core Idea

Use multiple H1 headings as first-class flow nodes, then connect those nodes manually with explicit edge directives.

- `# Heading {#id}` creates a top-level flow node.
- `> edge.<type>:` creates directed connections from the current node to one or more target nodes.
- H2 and deeper headings under an H1 remain normal local child nodes.
- The global flow is defined by explicit edges, not by source order.
- Flow edges can model long chains, fan-out, fan-in, branches, retries, and cycles.

This gives you two layers in one Markdown file:

- The H1 layer is the arbitrary workflow graph.
- The nested heading layer is the local detail tree attached to each flow node.

## Minimal Example

```markdown
# Receive Request {#receive-request}
> type: flow_step
> edge.flow: validate-request, reject-request

Receives the inbound API request.

# Validate Request {#validate-request}
> type: flow_step
> edge.flow: persist-request
> edge.failure: reject-request

# Persist Request {#persist-request}
> type: flow_step
> edge.flow: complete-request

# Reject Request {#reject-request}
> type: flow_step
> edge.retry: receive-request

# Complete Request {#complete-request}
> type: flow_step
```

This creates:

- `receive-request -> validate-request`
- `receive-request -> reject-request`
- `validate-request -> persist-request`
- `validate-request -> reject-request`
- `persist-request -> complete-request`
- `reject-request -> receive-request`

The retry edge creates a cycle. This is allowed when you use normal custom edge types such as `flow`, `failure`, or `retry`.

## Add Local Details Under A Flow Node

Use nested headings when a flow node needs comments, examples, code notes, links, images, or branches that belong visually under that node.

````markdown
# Receive Request {#receive-request}
> type: flow_step
> edge.flow: validate-request

Receives the inbound API request.

## Example Payload {#receive-request-payload}
> type: example

```json
{ "user_id": "123", "action": "create" }
```

## Reviewer Note {#receive-request-note}
> type: comment

This node can branch based on request shape.

# Validate Request {#validate-request}
> type: flow_step
````

Here, `receive-request-payload` and `receive-request-note` are local child nodes of `receive-request`. They are connected by the parser's automatic `parent_child` or built-in child edge behavior, while `edge.flow` controls the global workflow.

## Recommended Edge Types

Choose edge type names that describe the meaning of the transition.

| Edge type | Use for |
| --- | --- |
| `flow` | Normal next transition |
| `success` | Successful path |
| `failure` | Error or rejection path |
| `retry` | Loop back to an earlier node |
| `async` | Asynchronous handoff |
| `depends_on` | Dependency rather than execution flow |

Avoid `edge.next` for arbitrary workflows. The current Markdown parser treats `next` as a built-in procedure-step edge and validates it as a single ordered chain under a `procedure` node.

## Suggested Config

The builder will create missing config entries automatically, but explicit styling makes flow diagrams easier to read.

`node_config.json`:

```json
{
  "flow_step": {
    "color": "#1F2937",
    "backgroundColor": "#EFF6FF",
    "shape": "rectangle",
    "font_size": 15,
    "font_family": "Arial",
    "padding": 12,
    "borderRadius": 12
  },
  "example": {
    "color": "#374151",
    "backgroundColor": "#F9FAFB",
    "shape": "rectangle",
    "font_size": 13,
    "font_family": "Arial",
    "padding": 10,
    "borderRadius": 8
  },
  "comment": {
    "color": "#57534E",
    "backgroundColor": "#FAF7F2",
    "shape": "rectangle",
    "font_size": 13,
    "font_family": "Arial",
    "padding": 10,
    "borderRadius": 12
  }
}
```

`edge_config.json`:

```json
{
  "parent_child": {
    "connection_type": "line",
    "color": "#9CA3AF",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow"
  },
  "flow": {
    "connection_type": "line",
    "color": "#2563EB",
    "stroke_width": 2,
    "stroke_style": "solid",
    "arrow_start": null,
    "arrow_end": "arrow"
  },
  "failure": {
    "connection_type": "line",
    "color": "#DC2626",
    "stroke_width": 2,
    "stroke_style": "dashed",
    "arrow_start": null,
    "arrow_end": "arrow"
  },
  "retry": {
    "connection_type": "line",
    "color": "#F59E0B",
    "stroke_width": 2,
    "stroke_style": "dotted",
    "arrow_start": null,
    "arrow_end": "arrow"
  },
  "comment": {
    "connection_type": "line",
    "color": "#78716C",
    "stroke_width": 2,
    "stroke_style": "dashed",
    "arrow_start": null,
    "arrow_end": null
  }
}
```

`config.json`:

```json
{
  "parser_type": "md",
  "layout": {
    "direction": "left-right",
    "level_spacing": 180,
    "sibling_spacing": 40,
    "root_spacing": 120
  }
}
```

## Layout Behavior

The current layout is still a tree layout.

- Multiple H1 flow nodes are treated as separate top-level roots for initial placement.
- Explicit flow edges draw arrows between those roots, but they do not control initial placement.
- H2 and deeper headings are laid out as local children of their parent heading.
- After the first build, reposition the flow nodes in the Excalidraw viewer. Saved positions in `positions.json` are preserved across rebuilds.

This means the current setup can represent arbitrary flows, but it does not automatically produce a flow-aware initial layout.

## Rules And Caveats

- Every flow node needs a stable heading anchor such as `{#receive-request}`.
- Target IDs in `edge.*` directives must match another heading anchor.
- Edges to missing target nodes are removed during parsing.
- Use custom edge types for arbitrary flows; avoid `edge.next` unless you are using the built-in `procedure` and `step` model.
- Self-loops are not currently created from Markdown edge directives because the parser skips edges from a node to itself.
- Source order is for readability and first-pass placement only. Explicit edges define the actual workflow.

