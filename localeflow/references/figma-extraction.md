# Figma Extraction Reference

Use this reference when running the extraction step with Figma MCP `use_figma`.

## Scope

Default behavior:

- If nodes are selected, extract from selected nodes.
- If nothing is selected, extract from the current page.
- Extract from all pages only when explicitly requested.
- Traverse nested children recursively.
- Include visible text from frames, sections, groups, components, component sets, and instances.
- Ignore hidden nodes unless the user requested hidden text.
- Treat text node names beginning with `nt_` as non-translatable.
- Export displayed text after Figma text casing is applied.
- Sort records within page/frame by visual order: top-to-bottom, then left-to-right.

## Plugin API Code

Pass code like this to `use_figma`. Adjust `includeHidden` only from user input.

```javascript
const includeHidden = false;
const includeComponentMasterText = true;
const includeInstanceOverrideText = true;
const extractAllPages = false;
const nonTranslatablePrefix = "nt_";

function nodeVisible(node) {
  let current = node;
  while (current) {
    if ("visible" in current && current.visible === false) return false;
    current = current.parent;
  }
  return true;
}

function inferRole(node) {
  const text = (node.characters || "").trim();
  const name = (node.name || "").toLowerCase();
  const parentName = node.parent ? (node.parent.name || "").toLowerCase() : "";
  const combined = `${name} ${parentName}`;

  if (/error|invalid|required|failed|failure/.test(combined)) return "error";
  if (/toast|snackbar|notification/.test(combined)) return "toast";
  if (/empty|blank state|zero state/.test(combined)) return "empty_state";
  if (/tooltip|tip/.test(combined)) return "tooltip";
  if (/nav|navigation|menu|breadcrumb/.test(combined)) return "navigation";
  if (/a11y|accessibility|aria|alt text|screen reader/.test(combined)) return "accessibility_label";
  if (/button|btn|cta/.test(combined)) return "button";
  if (/tab/.test(combined)) return "tab";
  if (/placeholder|input|field|search/.test(combined)) return "placeholder";
  if (/label|caption/.test(combined)) return "label";
  if (/title|heading|header|h1|h2/.test(combined)) return "title";
  if (/subtitle|subhead|description|body/.test(combined)) return "subtitle";
  if (text.length <= 18 && node.fontSize && node.fontSize >= 18) return "title";
  if (text.length <= 24) return "label";
  return "text";
}

function nearestAncestorName(node, types) {
  let current = node.parent;
  while (current) {
    if (types.includes(current.type)) return current.name || "";
    current = current.parent;
  }
  return "";
}

function hierarchyPath(node) {
  const parts = [];
  let current = node;
  while (current && current.type !== "DOCUMENT") {
    if (current.name) parts.unshift(current.name);
    current = current.parent;
  }
  return parts.join(" / ");
}

function hasAncestorType(node, type) {
  let current = node.parent;
  while (current) {
    if (current.type === type) return true;
    current = current.parent;
  }
  return false;
}

function displayedText(node) {
  let text = node.characters || "";
  switch (node.textCase) {
    case "UPPER":
      return text.toUpperCase();
    case "LOWER":
      return text.toLowerCase();
    case "TITLE":
      return text.replace(/\w\S*/g, (value) => value.charAt(0).toUpperCase() + value.slice(1).toLowerCase());
    default:
      return text;
  }
}

function absolutePosition(node) {
  const transform = node.absoluteTransform;
  if (transform) return { x: transform[0][2], y: transform[1][2] };
  return { x: "x" in node ? node.x : 0, y: "y" in node ? node.y : 0 };
}

let roots;
let scope;
if (extractAllPages) {
  await figma.loadAllPagesAsync();
  roots = figma.root.children.filter((node) => node.type === "PAGE");
  scope = "All pages";
} else if (figma.currentPage.selection.length > 0) {
  roots = figma.currentPage.selection;
  scope = "Selected nodes";
} else {
  roots = [figma.currentPage];
  scope = "Current page";
}

const records = [];

function visit(node) {
  const visible = nodeVisible(node);
  if (!includeHidden && !visible) return;
  if (!includeComponentMasterText && (node.type === "COMPONENT" || node.type === "COMPONENT_SET")) return;
  if (!includeInstanceOverrideText && node.type === "INSTANCE") return;

  if (node.type === "TEXT") {
    const raw = displayedText(node);
    if (raw.trim()) {
      const position = absolutePosition(node);
      records.push({
        raw_text: raw,
        original_text: node.characters || "",
        text_case: node.textCase || "ORIGINAL",
        node_id: node.id,
        node_name: node.name || "",
        page: nearestAncestorName(node, ["PAGE"]) || figma.currentPage.name || "",
        frame: nearestAncestorName(node, ["FRAME", "SECTION", "COMPONENT", "INSTANCE"]),
        component: nearestAncestorName(node, ["COMPONENT", "COMPONENT_SET", "INSTANCE"]),
        figma_path: hierarchyPath(node),
        ui_role: inferRole(node),
        visible,
        node_kind: node.type,
        x: "x" in node ? node.x : 0,
        y: "y" in node ? node.y : 0,
        absolute_x: position.x,
        absolute_y: position.y,
        width: "width" in node ? node.width : 0,
        height: "height" in node ? node.height : 0,
        non_translatable: (node.name || "").startsWith(nonTranslatablePrefix),
        non_translatable_reason: (node.name || "").startsWith(nonTranslatablePrefix)
          ? `Node name starts with ${nonTranslatablePrefix}`
          : "",
        inside_instance: hasAncestorType(node, "INSTANCE"),
        inside_component: hasAncestorType(node, "COMPONENT") || hasAncestorType(node, "COMPONENT_SET")
      });
    }
  }

  if ("children" in node) {
    for (const child of node.children) visit(child);
  }
}

for (const root of roots) visit(root);

records.sort((a, b) => {
  if (a.page !== b.page) return a.page.localeCompare(b.page);
  if (a.frame !== b.frame) return a.frame.localeCompare(b.frame);
  if (a.absolute_y !== b.absolute_y) return a.absolute_y - b.absolute_y;
  if (a.absolute_x !== b.absolute_x) return a.absolute_x - b.absolute_x;
  return a.node_id.localeCompare(b.node_id);
});

return {
  page: figma.currentPage.name,
  scope,
  selection_count: figma.currentPage.selection.length,
  extracted_count: records.length,
  records
};
```

## Raw Input Shape for Processor

Save `records` directly as JSON, or save the whole returned object. The processor recognizes both:

```json
{
  "page": "Home",
  "records": [
    {
      "raw_text": "Welcome back",
      "original_text": "welcome back",
      "text_case": "TITLE",
      "node_id": "123:456",
      "node_name": "Welcome back",
      "page": "Home",
      "frame": "Home Screen",
      "component": "Header",
      "figma_path": "Home / Home Screen / Header / Welcome back",
      "ui_role": "title",
      "visible": true,
      "node_kind": "TEXT",
      "x": 24,
      "y": 80,
      "absolute_x": 24,
      "absolute_y": 80,
      "width": 180,
      "height": 32,
      "non_translatable": false,
      "non_translatable_reason": "",
      "inside_instance": false,
      "inside_component": false
    }
  ]
}
```

## Extraction Notes

- Figma text may be split across multiple visual layers. Do not merge layers automatically unless the user asks; merging is context-sensitive and can corrupt keys.
- Component instances can contain overridden text. Record `inside_instance` so repeated component copy can be reviewed.
- If all pages are requested through `use_figma`, prefer one call per page when possible so each call switches page at most once.
- Keep `nt_` strings in reports and context maps. In production export, preserve them unchanged by default or use the processor's exclude mode when the user does not want them in production files.
- Use the final processor summary to decide whether to rerun extraction with hidden layers or a narrower selection.
