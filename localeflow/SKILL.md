---
name: localeflow
description: Extract localization-ready UI strings from Figma files. Use when a user asks to collect text from the current Figma page, selected frames, sections, components, or instances; compare extracted copy with existing CSV or JSON string files; deduplicate UI copy; generate stable localization keys; classify strings as new, existing, changed, duplicate, or conflict; generate translations; and export clean production-ready CSV or JSON plus report and context-map files for product localization workflows.
---

# LocaleFlow

LocaleFlow turns visible Figma UI text into structured localization entries. It combines Figma MCP extraction with deterministic post-processing so designers and developers get stable keys, generated translations, clean production CSV/JSON, and separate review/context files.

Core principle: production localization files stay clean. Put only `key`, `source`, and target-language values in production CSV/JSON. Put Figma metadata, review status, conflicts, glossary matches, duplicate analysis, and node references into report and context-map files.

## Required Inputs

Ask for missing inputs only when they are necessary to proceed.

- Figma target: current page, selected nodes, or a specific Figma node URL.
- Existing localization file: optional CSV or JSON path/content. Before starting translation, identify whether the user already has one.
- Output format: CSV, JSON, or both. Default to CSV when the user does not specify.
- Source language: infer from extracted Figma strings by default. Only override when the user explicitly provides a source language.
- Target languages: infer from existing localization file columns or rules file `target_languages`. If neither exists, ask: "Which languages does this need to be translated into?"
- Dedupe mode: `context-aware` by default, or `global`.
- Hidden layers: exclude by default unless requested.
- Components and instances: include both by default, recording node type context.
- Key prefix: optional app/product namespace such as `app`, `checkout`, or `jbl_one`.
- Preferred key naming style: optional; default is dot-separated semantic keys.
- Translation rules or glossary: optional; preserve placeholders exactly.
- Generated translations file: optional CSV or JSON when translations are generated before post-processing.

## Workflow

1. Identify whether the user has an existing localization file.
2. Determine target languages from the existing file or rules file. If no target languages are discoverable, ask the user which languages are needed before translating.
3. Extract text nodes from Figma with MCP.
4. Infer the source language from extracted strings.
5. Load optional localization rules, glossary, and translation memory.
6. Normalize source strings and detect placeholders.
7. Compare with any existing CSV or JSON string file.
8. Generate deterministic, human-readable keys from frame/context, UI role, and content.
9. Classify entries as `new`, `existing`, `changed`, `duplicate`, or `conflict`.
10. Generate draft translations for missing target-language values using the current agent/model, then pass them to the processor with `--translations`.
11. Reuse exact translation memory matches, apply full-string glossary matches, validate generated translations, and flag fuzzy matches for review.
12. Export the final merged localization table by default, unless the user explicitly asks for only new or changed strings.
13. Generate Markdown/JSON reports and `context_map.json` for impact, review items, and traceability.

## Figma Extraction

Use `use_figma` for extraction because it can inspect the current selection and traverse nested node trees through the Figma Plugin API. Before calling `use_figma`, follow the Figma skill prerequisite for that tool in the host agent environment.

For extraction code and expected raw JSON shape, read `references/figma-extraction.md`.

Return one raw record per text node with:

- `raw_text`
- `node_id`
- `node_name`
- `page`
- `frame`
- `component`
- `figma_path`
- `ui_role`
- `visible`
- `node_kind`
- `inside_instance`
- `inside_component`

Ignore hidden text by default. If the user asks to include hidden text, include it and set `visible: false`.

## Post-Processing

Use `scripts/process_figma_strings.py` whenever extracted records or existing string files need deterministic comparison, key generation, dedupe, or export.

Example:

```bash
python3 localeflow/scripts/process_figma_strings.py \
  --input extracted.json \
  --existing strings.csv \
  --format both \
  --output strings \
  --target-languages zh-Hans,ja,fr \
  --dedupe-mode context-aware \
  --key-prefix app \
  --rules localization-rules.json \
  --translations generated-translations.json \
  --report-md localization_report.md \
  --report-json localization_report.json \
  --context-map context_map.json \
  --figma-file "Example App" \
  --page "Account" \
  --scope "Selected frames"
```

The script accepts extracted records as either a JSON array or an object with `strings`, `records`, or `items`. Existing files may be CSV or JSON.

If `--target-languages` is omitted, the processor tries `target_languages` from the rules file and then target-language columns from the existing localization file. If no target languages are found, it exits with a clear error so the agent can ask the user.

If `--source-language` is omitted, the processor infers it from extracted strings and writes the inferred value to reports.

Use `--export-mode advanced` only when the user explicitly wants metadata in the exported string file. Production export mode is the default.

## Localization Rules File

Accept a user-provided rules file with `--rules`. Prefer JSON for full configuration; accept CSV for do-not-translate terms, glossary entries, and translation memory.

JSON shape:

```json
{
  "source_language": "en",
  "target_languages": ["zh-Hans", "ja", "fr"],
  "do_not_translate": ["API", "PIN", "URL"],
  "glossary": [
    {
      "source": "pairing",
      "target_language": "zh-Hans",
      "translation": "配对",
      "context": "Account setup",
      "notes": "Approved term."
    }
  ],
  "translation_memory": [
    {
      "source": "Set up your profile",
      "target_language": "zh-Hans",
      "translation": "设置你的个人资料",
      "key": "account_settings.title.set_up_your_profile"
    }
  ],
  "placeholder_patterns": [
    "\\{[a-zA-Z0-9_]+\\}",
    "\\{\\{[a-zA-Z0-9_]+\\}\\}",
    "%@",
    "%d",
    "%s",
    "\\$\\{[a-zA-Z0-9_]+\\}"
  ],
  "style_rules": {
    "global": ["Use concise mobile UI language."],
    "button": ["Keep button labels short."],
    "zh-Hans": ["Use Simplified Chinese UI wording."],
    "ja.button": ["Prefer concise Japanese button labels."],
    "error": ["Make the message clear and actionable."]
  }
}
```

CSV rules columns:

```csv
type,source,target_language,translation,context,notes
do_not_translate,API,,,Technical term,Keep unchanged
glossary,profile,zh-Hans,个人资料,Account settings,Approved term
translation_memory,Set up your profile,zh-Hans,设置你的个人资料,Account settings screen,Approved string
```

When rules are present, follow this priority:

1. Preserve placeholders exactly.
2. Preserve do-not-translate terms exactly.
3. Apply exact translation memory matches.
4. Apply approved glossary terms.
5. Apply UI-role style rules.
6. Apply target-language-specific rules when present.
7. Flag fuzzy translation memory matches for human review.
8. Flag rule conflicts, missing translations, and placeholder errors.

Do not silently resolve rule conflicts. If the processor reports `rule_conflicts`, show them to the user and ask for review before treating translations as approved.

## Key Rules

Generate keys with this preference order:

1. `{prefix.}{screen_or_frame}.{ui_role}.{semantic_name}`
2. `{prefix.}common.{ui_role}.{semantic_name}` when context is missing
3. Add a context suffix when the same text needs separate meanings
4. Add a short hash only when a collision remains

Keep keys lowercase. Use ASCII letters, digits, and underscores within each segment. Use dots between semantic segments.

Examples:

- `home.title.welcome_back`
- `product_card.button.add_to_cart`
- `settings.label.notification`
- `login.error.invalid_password`
- `common.button.cancel`

## Normalization Rules

- Trim leading and trailing whitespace.
- Collapse repeated spaces and tabs.
- Collapse line breaks to spaces unless the line break appears semantically meaningful.
- Preserve placeholders exactly in exported source text.
- For key generation, replace dynamic values with stable placeholder concepts when obvious.
- Treat URLs, email addresses, filenames, trademarks, and product model names as strings that may need translator notes.

Placeholder patterns include `{name}`, `{{count}}`, `%@`, `%d`, `%s`, `$price`, `${price}`, `{device_name}`, `<bold>text</bold>`, `[link]`, numbers, dates, percentages, and currency values. Add custom patterns in the rules file when a product uses project-specific placeholder syntax.

## Dedupe Modes

`context-aware` is the default. Keep identical source strings separate when UI role or major screen/frame context differs.

`global` emits one entry per normalized source string. Preserve all source locations in notes when possible.

## Comparison Rules

- `existing`: normalized source already exists in the existing file.
- `new`: source does not exist in the existing file.
- `changed`: generated key or near context exists, but the source changed.
- `duplicate`: same dedupe identity appears more than once in extracted Figma records.
- `conflict`: same generated key maps to different source strings.

Default export includes `new` and `changed`. Include duplicates and conflicts in the summary even when they are not exported.

## Translation Generation

Before production export, generate translations for each missing target-language cell. Exact translation memory matches and exact full-string glossary matches are applied by the processor, but unmatched content should be translated by the agent/model using:

- source string
- target language
- Figma context, frame, path, and UI role
- do-not-translate terms
- glossary matches
- style rules
- placeholders that must be preserved exactly

Translation-generation rules:

- Preserve placeholders exactly. Do not translate, rename, remove, duplicate, or reorder placeholders unless the target language grammar requires moving the whole unchanged token. Examples: `{name}`, `{{count}}`, `%@`, `%d`, `%s`, `$price`, `${price}`, `<bold>text</bold>`, `[link]`.
- Preserve do-not-translate terms exactly, including technical terms, placeholders, file names, URLs, trademarks, protocol names, and short product-neutral tokens such as `API`, `PIN`, or `URL`.
- Reuse exact translation memory before generating a new translation.
- Apply approved glossary translations consistently. If a glossary term appears inside a longer string, use the approved term naturally in the sentence.
- Use target-language-specific style rules when present. If both global and target-language rules apply, follow both.
- Use UI role to shape wording: keep buttons short and action-oriented, make toast text lightweight and glanceable, make errors clear and actionable, keep labels concise, and avoid full sentences for compact controls.
- Use Figma context to disambiguate short strings such as `Set`, `On`, `Off`, `Open`, `Apply`, `Name`, `Done`, and `Connect`.
- If a short or ambiguous string cannot be translated confidently, still generate the best context-based translation and ensure the report marks it as `needs_review`.
- Avoid marketing-style or overly formal wording unless the source copy is promotional.
- Keep punctuation natural for the target locale while preserving placeholders and do-not-translate terms exactly.
- Do not silently override placeholder, glossary, translation memory, or do-not-translate constraints. If constraints conflict, generate a review item instead.

Write generated translations as CSV or JSON and pass them with `--translations`.

JSON shape:

```json
{
  "translations": [
    {
      "source": "Set up your account",
      "target_language": "zh-Hans",
      "translation": "设置你的账户"
    }
  ]
}
```

CSV columns:

```csv
key,source,target_language,translation
account_settings.button.save,Save,zh-Hans,保存
```

If a translation remains missing, production files can still be generated, but the report must mark `missing_translation` and `needs_review`.

## Output Fields

Default production CSV columns:

```csv
key,source,zh-Hans,ja,fr
```

Default production JSON shape:

```json
{
  "home.title.welcome_back": {
    "source": "Welcome back",
    "zh-Hans": "欢迎回来",
    "ja": "おかえりなさい",
    "fr": "Bon retour"
  }
}
```

No Figma metadata should be included in production files.

Advanced CSV output may include:

```csv
key,source,zh-Hans,ja,fr,status,page,frame,node_id,ui_role,figma_path,notes
```

## Extraction Report

Generate a report after each extraction/comparison when the user needs review context, CI summaries, or stakeholder-readable impact notes.

Supported report outputs:

- Markdown: `--report-md localization_report.md`
- JSON: `--report-json localization_report.json`

Recommended output set:

```text
strings.csv
strings.json
localization_report.md
localization_report.json
context_map.json
```

The report should answer:

- how many text layers were scanned
- how many valid strings were extracted
- how many strings are existing, new, changed, duplicated, or conflicting
- how many glossary, do-not-translate, exact TM, and fuzzy TM matches were found
- how many entries need human review
- whether placeholder errors or localization rule conflicts exist
- which frames contain the most new or problematic strings

Each exported string should include `report_tags`, such as:

```json
["new", "glossary_match", "tm_fuzzy_match", "needs_review", "auto_key_generated"]
```

Report review severity:

- `info`: useful context, no action required, such as glossary or do-not-translate matches.
- `warning`: human review recommended, such as fuzzy TM matches or ambiguous short strings.
- `error`: must be fixed before merge, such as placeholder errors, key conflicts, or rule conflicts.

Change impact levels:

- `low_impact`: few new strings and no conflicts or placeholder errors.
- `medium_impact`: multiple new strings or fuzzy matches, but no blocking errors.
- `high_impact`: key conflicts, placeholder errors, rule conflicts, or many new strings.

## Context Map

Always generate `context_map.json` for traceability and future Figma write-back. Map each localization key to source text, Figma node IDs, Figma paths, page, frame, UI role, status, glossary matches, do-not-translate matches, and review state.

Example:

```json
{
  "account_settings.button.save": {
    "source": "Save",
    "figma_nodes": ["123:456"],
    "figma_paths": ["Account / Account Settings / Primary Button"],
    "page": "Account",
    "frame": "Account Settings",
    "ui_role": "button",
    "status": "new",
    "matched_glossary_terms": ["connect"],
    "do_not_translate_matches": [],
    "needs_review": false
  }
}
```

## Translation Rules

When generating translations, follow these constraints:

- Preserve placeholders exactly.
- Keep brand/product/model names unchanged.
- Keep button labels concise.
- Use mobile UI wording, not marketing copy.
- Follow any glossary supplied by the user.
- If ambiguity remains, generate the best translation based on Figma context and mark the string as `needs_review` in the report.

Translation memory status values:

- `tm_exact_match`: full source string matched approved translation memory; reuse the translation.
- `tm_fuzzy_match`: similar source string matched translation memory; export suggestion and set `needs_review`.
- `no_tm_match`: no translation memory match was found.

Placeholder status values:

- `ok`: no placeholder issue detected.
- `placeholder_error`: a non-empty translation is missing, renaming, or duplicating a source placeholder.

## Quality Checks

Before final delivery:

- Confirm every exported row has `key`, `source`, `status`, and Figma context.
- Check duplicate and conflict counts.
- Check `rule_conflicts`, `tm_status`, `needs_review`, and `placeholder_status`.
- Confirm production CSV/JSON contains no Figma metadata unless `--export-mode advanced` was requested.
- Confirm `localization_report.md`, `localization_report.json`, and `context_map.json` were generated.
- Verify generated keys are deterministic across repeated runs.
- Confirm placeholder tokens in `source` are unchanged.
- Show the output path and a short classification summary.
