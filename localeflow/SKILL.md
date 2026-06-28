---
name: localeflow
description: Extract localization-ready UI strings from Figma files. Use when a user asks to collect text from the current Figma page, selected frames, sections, components, or instances; compare extracted copy with existing CSV or JSON string files; deduplicate UI copy; generate stable localization keys; classify strings as new, existing, changed, duplicate, or conflict; generate translations; and export clean production-ready CSV/JSON plus one human-readable report for product localization workflows.
---

# LocaleFlow

LocaleFlow turns visible Figma UI text into structured localization entries. It combines Figma MCP extraction with deterministic post-processing so designers and developers get stable keys, generated translations, clean production CSV/JSON, and one human-readable report.

Core principle: production localization files stay clean. Put only `key`, the source-language column, and target-language values in production CSV/JSON. CSV and JSON should share the same table content. The source column should use the language code such as `en` or `zh` when the source language is known, not the generic label `source`.

Output principle: default to exactly three user-facing files: `strings.csv`, `strings.json`, and `localization_report.md`. The report should include the changelog, review items, and report-only strings. Do not create separate context-map, changelog, or report JSON files unless the user explicitly asks for machine-readable/debug artifacts.

## Required Inputs

Ask for missing inputs before taking translation action when they affect output shape or language coverage.

- Figma target: current page, selected nodes, or a specific Figma node URL.
- Existing localization file: optional CSV or JSON path/content. Before extracting or translating, ask whether the user has one unless they already provided a file, explicitly said there is no existing file, or asked for extraction only.
- Output format: CSV, JSON, or both. Default to both when the user does not specify.
- Source language: infer from extracted Figma strings by default. Only override when the user explicitly provides a source language.
- Target languages: infer from existing localization file columns or rules file `target_languages`. If no existing file or rules file supplies target languages, ask the user to confirm the target languages before generating translations or final localization files.
- Dedupe mode: `context-aware` by default, or `global`.
- Hidden layers: exclude by default unless requested.
- Components and instances: include both by default, recording node type context.
- Non-translatable prefix: default `nt_`. Text layers with this prefix are extracted and reported as non-translatable.
- Non-translatable export mode: default `exclude`. Text layers marked `nt_`, numeric-only strings, and symbol-only strings are listed in the report but omitted from production CSV/JSON unless the user explicitly asks to preserve `nt_` strings.
- Key prefix: optional app/product namespace such as `app`, `checkout`, or `jbl_one`.
- Preferred key naming style: optional; default is dot-separated semantic keys.
- Translation rules or glossary: optional; preserve placeholders exactly.
- Generated translations file: optional CSV or JSON when translations are generated before post-processing.

## Workflow

1. Identify whether the user has an existing localization file. If this is unknown, ask first. If the user confirms there is no existing file, create a new localization output from the extracted Figma strings.
2. Determine target languages from the existing file or rules file. If no target languages are discoverable, ask the user which languages are needed before translating or exporting.
3. Extract text nodes from Figma with MCP. Scope priority is selected nodes first, then current page, then all pages only when explicitly requested.
4. Infer the source language from extracted strings.
5. Load optional localization rules, glossary, and translation memory.
6. Normalize source strings and detect placeholders.
7. Compare with any existing CSV or JSON string file.
8. Generate deterministic, human-readable keys from frame/context, UI role, and content.
9. Classify entries as `new`, `existing`, `changed`, `duplicate`, or `conflict`.
10. Generate draft translations for missing target-language values only after target languages are confirmed, then pass them to the processor with `--translations`.
11. Reuse exact translation memory matches, apply full-string glossary matches, validate generated translations, and flag fuzzy matches for review.
12. Export the final merged localization table by default, unless the user explicitly asks for only new or changed strings.
13. Generate `strings.csv`, `strings.json`, and one Markdown report with changelog, review items, and report-only strings.

## Figma Extraction

Use `use_figma` for extraction because it can inspect the current selection and traverse nested node trees through the Figma Plugin API. Before calling `use_figma`, follow the Figma skill prerequisite for that tool in the host agent environment.

For extraction code and expected raw JSON shape, read `references/figma-extraction.md`.

Return one raw record per text node with:

- `raw_text`
- `original_text`
- `text_case`
- `node_id`
- `node_name`
- `page`
- `frame`
- `component`
- `figma_path`
- `ui_role`
- `visible`
- `node_kind`
- `x`
- `y`
- `absolute_x`
- `absolute_y`
- `width`
- `height`
- `non_translatable`
- `non_translatable_reason`
- `inside_instance`
- `inside_component`

Ignore hidden text by default. If the user asks to include hidden text, include it and set `visible: false`.

Apply Figma text casing before writing `raw_text`: if a text node is visually uppercase, lowercase, or title case through Figma text-case styling, export the displayed string. Keep `original_text` for traceability.

Sort extracted records within each page/frame by visual order: top-to-bottom, then left-to-right. This keeps CSV diffs and reviewer flow stable.

Treat text node names beginning with `nt_` as non-translatable. These strings stay in the report; production exports omit them by default or preserve them unchanged only when `--non-translatable-mode preserve` is used.

## Post-Processing

Use `scripts/process_figma_strings.py` whenever extracted records or existing string files need deterministic comparison, key generation, dedupe, or export.

Example:

```bash
python3 localeflow/scripts/process_figma_strings.py \
  --input extracted.json \
  --existing strings.csv \
  --output strings \
  --target-languages zh-Hans,ja,fr \
  --dedupe-mode context-aware \
  --key-prefix app \
  --rules localization-rules.json \
  --translations generated-translations.json \
  --non-translatable-prefix nt_ \
  --non-translatable-mode exclude \
  --report-md localization_report.md \
  --figma-file "Example App" \
  --page "Account" \
  --scope "Selected frames"
```

The script accepts extracted records as either a JSON array or an object with `strings`, `records`, or `items`. Existing files may be CSV or JSON.

If `--target-languages` is omitted, the processor tries `target_languages` from the rules file and then target-language columns from the existing localization file. If no target languages are found, it exits with a clear error so the agent can ask the user.

If `--source-language` is omitted, the processor infers it from extracted strings and writes the inferred value to reports.

The processor defaults to `--format both`, which writes a CSV and JSON version of the same production table. Use `--format csv` or `--format json` only when the user asks for a single file.

Use `--export-mode advanced` only when the user explicitly wants metadata in the exported string file. Production export mode is the default.

Production CSV/JSON must contain only `key`, the source-language column such as `en` or `zh`, and target-language columns. Do not add Figma metadata, review flags, non-translatable flags, numeric-only rows, symbol-only rows, node IDs, hashes, run IDs, or version columns to production exports.

The Markdown report should focus on human decisions:

- overall counts
- changelog counts and rows for added, changed, removed, and report-only strings
- conflicts, missing translations, placeholder errors, and review items
- inferred do-not-translate terms
- screens with the most new or problematic strings

For repeated exports, prefer passing the previous `strings.csv` or `strings.json` with `--existing`. The changelog can derive added, changed, existing, and removed keys from the existing production file. If a team needs deeper automation, `--previous-context-map`, `--context-map`, `--report-json`, `--changelog-json`, and `--changelog-md` remain available as explicit opt-in outputs.

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

## Inferred Do-Not-Translate Terms

Use AI judgment to identify likely terms that should remain unchanged, even when the user did not list them in `do_not_translate`.

Likely do-not-translate terms include:

- brand names, organization names, app names, product names, and feature names
- acronyms and all-caps technical tokens such as `API`, `PIN`, `SSO`, or `URL`
- filenames, URLs, email addresses, protocol names, model names, and version-like tokens
- partner/service names or proper nouns that are not ordinary UI words

Do not ask the user to confirm each inferred term one by one. Preserve inferred terms during translation, then list them in `localization_report.md` so the user can either go ahead with LocaleFlow's decision or ask to translate specific terms.

If a user explicitly says a term should be translated, treat that instruction as an override for that run and do not preserve the term.

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
- Do not translate numeric-only strings or strings made only of numbers plus numeric symbols, punctuation, percentages, or currency signs. Keep them in the report but omit them from production CSV/JSON.
- When a number appears inside otherwise translatable copy, replace the number with a stable placeholder such as `{number_1}` before translation and require the same placeholder in every target-language value.
- For key generation, replace dynamic values with stable placeholder concepts when obvious.
- Treat URLs, email addresses, filenames, trademarks, and product model names as strings that may need translator notes.

Placeholder patterns include `{name}`, `{{count}}`, `%@`, `%d`, `%s`, `$price`, `${price}`, `{device_name}`, `<bold>text</bold>`, `[link]`, and generated number placeholders such as `{number_1}`. Add custom patterns in the rules file when a product uses project-specific placeholder syntax.

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

Before translating, convert numbers inside sentence-like source copy to generated placeholders, for example `有效期为 30 天` becomes `有效期为 {number_1} 天`. Translate around the placeholder and preserve `{number_1}` exactly. Numeric-only values such as `999`, `¥699`, `9:41`, or `50%` are not translated.

Translation-generation rules:

- Preserve placeholders exactly. Do not translate, rename, remove, duplicate, or reorder placeholders unless the target language grammar requires moving the whole unchanged token. Examples: `{name}`, `{{count}}`, `%@`, `%d`, `%s`, `$price`, `${price}`, `<bold>text</bold>`, `[link]`.
- Preserve do-not-translate terms exactly, including technical terms, placeholders, file names, URLs, trademarks, protocol names, and short product-neutral tokens such as `API`, `PIN`, or `URL`.
- Preserve AI-inferred do-not-translate terms exactly, then list them in the report instead of repeatedly asking for confirmation.
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

Generate one Markdown report after each extraction/comparison.

Supported report outputs:

- Markdown: `--report-md localization_report.md`
- Optional machine-readable JSON: `--report-json localization_report.json`

Recommended output set:

```text
strings.csv
strings.json
localization_report.md
```

The report should answer:

- how many text layers were scanned
- how many valid strings were extracted
- how many strings are existing, new, changed, duplicated, or conflicting
- how many glossary, do-not-translate, exact TM, and fuzzy TM matches were found
- which terms LocaleFlow inferred should remain untranslated
- how many entries need human review
- whether placeholder errors or localization rule conflicts exist
- which frames contain the most new or problematic strings

Internally, each processed string can include `report_tags`, such as:

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

## Optional Context Map

Generate `context_map.json` only when explicitly requested for automation, debugging, or future Figma write-back. It can map each localization key to source text, Figma node IDs, Figma paths, page, frame, UI role, status, glossary matches, do-not-translate matches, and review state.

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

- Confirm every exported production row has `key`, the source-language column, and target-language columns.
- Check duplicate and conflict counts.
- Check `rule_conflicts`, `tm_status`, `needs_review`, and `placeholder_status`.
- Confirm production CSV/JSON contains no Figma metadata unless `--export-mode advanced` was requested.
- Confirm `strings.csv`, `strings.json`, and `localization_report.md` were generated by default.
- Verify generated keys are deterministic across repeated runs.
- Confirm placeholder tokens in `source` are unchanged.
- Show the output path and a short classification summary.
