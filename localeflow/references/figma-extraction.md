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
- When a Figma file mixes product screens with specs, notes, and descriptions, use layered filtering: explicit selection first, include/exclude name markers second, and UI-surface heuristics last. Return skipped frames so the user can review what was filtered out.

## Plugin API Code

Pass code like this to `use_figma`. Adjust `includeHidden` only from user input. If the file contains both UI screens and written specs, keep `filterToUiSurfaces` enabled; if the selected nodes are already clean UI frames, it can be disabled.

```javascript
const includeHidden = false;
const includeComponentMasterText = true;
const includeInstanceOverrideText = true;
const extractAllPages = false;
const filterToUiSurfaces = true;
const trustExplicitSelection = true;
const nonTranslatablePrefix = "nt_";
const includeNamePattern = /(^|[\s_-])(lf_include|i18n_include|locale_include|localize|ui_page|ui_screen)([\s_-]|$)/i;
const excludeNamePattern = /(^|[\s_-])(lf_exclude|i18n_exclude|locale_exclude|no_i18n|no_localize)([\s_-]|$)/i;
const minUiFrameWidth = 240;
const minUiFrameHeight = 240;
const maxUiFrameWidth = 4096;
const maxUiFrameHeight = 4096;
const uiSurfaceNamePattern = /(screen|page|view|modal|dialog|drawer|sheet|panel|flow|mobile|desktop|web|app|home|settings|checkout|login|sign.?up|profile|account)/i;
const nonUiSpecNamePattern = /(spec|description|annotation|notes?|docs?|guidelines?|requirements?|comments?|copy\s*deck|ux\s*writing|research|wireframe\s*notes?)/i;

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

function isFrameLike(node) {
  return ["FRAME", "SECTION", "COMPONENT", "COMPONENT_SET", "INSTANCE", "GROUP"].includes(node.type);
}

function nodeName(node) {
  return node.name || "";
}

function hasNameMarker(node, pattern) {
  let current = node;
  while (current && current.type !== "PAGE" && current.type !== "DOCUMENT") {
    if (pattern.test(nodeName(current))) return true;
    current = current.parent;
  }
  return false;
}

function dimensionsLookLikeUiSurface(node) {
  if (!("width" in node) || !("height" in node)) return false;
  return (
    node.width >= minUiFrameWidth &&
    node.height >= minUiFrameHeight &&
    node.width <= maxUiFrameWidth &&
    node.height <= maxUiFrameHeight
  );
}

function looksLikeSpecContainer(node) {
  return nonUiSpecNamePattern.test(nodeName(node));
}

function looksLikeUiSurface(node) {
  if (!isFrameLike(node) || looksLikeSpecContainer(node)) return false;
  return dimensionsLookLikeUiSurface(node) || uiSurfaceNamePattern.test(nodeName(node));
}

function nearestFrameLikeAncestor(node) {
  let current = node.parent;
  while (current && current.type !== "PAGE" && current.type !== "DOCUMENT") {
    if (isFrameLike(current)) return current;
    current = current.parent;
  }
  return null;
}

function hasUiSurfaceAncestor(node) {
  let current = node.parent;
  while (current && current.type !== "PAGE" && current.type !== "DOCUMENT") {
    if (hasNameMarker(current, excludeNamePattern) || looksLikeSpecContainer(current)) return false;
    if (hasNameMarker(current, includeNamePattern)) return true;
    if (looksLikeUiSurface(current)) return true;
    current = current.parent;
  }
  return false;
}

function shouldExtractTextNode(node) {
  if (!filterToUiSurfaces) return true;
  if (trustExplicitSelection && figma.currentPage.selection.length > 0) {
    return !hasNameMarker(node, excludeNamePattern);
  }
  if (hasNameMarker(node, excludeNamePattern)) return false;
  if (hasNameMarker(node, includeNamePattern)) return true;
  return hasUiSurfaceAncestor(node);
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
const skippedFramesById = new Map();

function noteSkippedTextNode(node, reason) {
  const frame = nearestFrameLikeAncestor(node);
  if (!frame) return;
  const position = absolutePosition(frame);
  const item = skippedFramesById.get(frame.id) || {
    node_id: frame.id,
    name: frame.name || "",
    type: frame.type,
    page: nearestAncestorName(frame, ["PAGE"]) || figma.currentPage.name || "",
    figma_path: hierarchyPath(frame),
    reason,
    text_nodes_skipped: 0,
    width: "width" in frame ? frame.width : 0,
    height: "height" in frame ? frame.height : 0,
    absolute_x: position.x,
    absolute_y: position.y
  };
  item.text_nodes_skipped += 1;
  skippedFramesById.set(frame.id, item);
}

function visit(node) {
  const visible = nodeVisible(node);
  if (!includeHidden && !visible) return;
  if (!includeComponentMasterText && (node.type === "COMPONENT" || node.type === "COMPONENT_SET")) return;
  if (!includeInstanceOverrideText && node.type === "INSTANCE") return;

  if (node.type === "TEXT") {
    const shouldExtract = shouldExtractTextNode(node);
    const raw = displayedText(node);
    if (!shouldExtract && raw.trim()) {
      noteSkippedTextNode(node, hasNameMarker(node, excludeNamePattern) ? "Excluded by name marker or spec-like ancestor" : "Outside detected UI surface");
    }
    if (shouldExtract && raw.trim()) {
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
  ui_surface_filter: filterToUiSurfaces,
  filter_strategy: "selection -> include/exclude markers -> UI surface heuristics",
  selection_count: figma.currentPage.selection.length,
  extracted_count: records.length,
  skipped_frame_count: skippedFramesById.size,
  skipped_frames: Array.from(skippedFramesById.values()).sort((a, b) => {
    if (a.page !== b.page) return a.page.localeCompare(b.page);
    if (a.absolute_y !== b.absolute_y) return a.absolute_y - b.absolute_y;
    if (a.absolute_x !== b.absolute_x) return a.absolute_x - b.absolute_x;
    return a.node_id.localeCompare(b.node_id);
  }),
  records
};
```

## Renaming Text Layers With Generated Keys

When you want future exports to detect changed copy even after the source string changes, write the generated localization key back to the Figma text layer name. Do this after reviewing the generated keys. On a first run with no existing strings file or saved rules setting, ask the team whether they want this workflow and log the answer in `localization-rules.md`.

```bash
python3 localeflow/scripts/process_figma_strings.py \
  --input extracted.json \
  --existing strings.csv \
  --output strings \
  --extract-only \
  --layer-key-manifest layer-key-manifest.json
```

Or persist the preference in rules so future runs follow it automatically:

```md
## Figma Layer Key Write Back

- enabled: true
- layer_name_prefix: i18n:
```

When rules enable write-back and `--layer-key-manifest` is omitted, the processor writes `layer-key-manifest.json` beside the production output.

The manifest has this shape:

```json
{
  "layers": [
    {
      "node_id": "123:456",
      "key": "home.title.welcome_back",
      "rename_to": "home.title.welcome_back",
      "source": "Welcome back"
    }
  ]
}
```

Then pass the manifest's `layers` array to `use_figma` with code like this:

```javascript
const layers = [
  // paste layer-key-manifest.json layers here
];

let renamed = 0;
let skipped = [];

for (const item of layers) {
  const node = await figma.getNodeByIdAsync(item.node_id);
  if (!node || node.type !== "TEXT") {
    skipped.push({ node_id: item.node_id, reason: "Text node not found" });
    continue;
  }
  if (item.rename_to && node.name !== item.rename_to) {
    node.name = item.rename_to;
    renamed += 1;
  }
}

return { renamed, skipped };
```

On the next extraction, pass the previous `strings.csv` or `strings.json` with `--existing`. If a text layer name matches an existing key, LocaleFlow reuses that key first; when the layer text changed, the row is classified as `changed` instead of receiving a new generated key.

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
- Prefer explicit selection when heuristics are uncertain. The UI screen-frame filter is a guard against spec copy, not a substitute for a well-scoped selection.
