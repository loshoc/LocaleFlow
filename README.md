# LocaleFlow

LocaleFlow is a Figma agent skill for extracting UI strings from Figma pages or selected frames, comparing them with existing string files, generating stable localization keys and translations, and exporting clean production-ready CSV or JSON.


## Skill

- Skill folder: `localeflow/`
- Main instructions: `localeflow/SKILL.md`
- MCP tools: `use_figma`
- License: MIT

## MVP

- Extract visible text from selected Figma frames or the current page.
- Normalize UI strings.
- Compare against existing CSV or JSON string files.
- Deduplicate exact repeats globally or by context.
- Generate deterministic localization keys.
- Export clean production CSV or JSON, with metadata kept in report and context-map files.

## Example

```bash
python3 localeflow/scripts/process_figma_strings.py \
  --input localeflow/examples/extracted.json \
  --existing localeflow/examples/existing.csv \
  --format both \
  --output /tmp/strings \
  --target-languages zh-Hans,ja,fr \
  --dedupe-mode context-aware \
  --rules localeflow/examples/localization-rules.json \
  --translations localeflow/examples/generated-translations.json \
  --report-md /tmp/localization_report.md \
  --report-json /tmp/localization_report.json \
  --context-map /tmp/context_map.json \
  --figma-file "Example App" \
  --page "Account" \
  --scope "Selected frames"
```

The optional rules file supports do-not-translate terms, approved glossary terms, exact and fuzzy translation memory, custom placeholder patterns, and UI-role style notes.

LocaleFlow infers source language from extracted Figma strings by default. Target languages should come from `--target-languages`, the rules file, or existing localization file columns; if none are available, ask the user which languages to translate into before running.

By default the production exports are clean: `strings.csv` contains only `key`, `source`, and target-language columns, while `strings.json` uses a production key-value localization shape. Use `--export-mode advanced` when you need Figma metadata and review columns in the export itself.

The report files summarize extraction impact, status counts, glossary and translation memory matches, review severity, and frames with the most new or problematic strings. The context map links localization keys back to Figma node IDs and paths.

See `localeflow/examples/expected-strings.csv` and `localeflow/examples/expected-strings.json` for the expected clean production export shape.

## Community Listing Draft

### Localization

#### localeflow

[SOURCE CODE](https://github.com/YOUR_ORG/LocaleFlow) · [MIT](https://github.com/YOUR_ORG/LocaleFlow/blob/main/LICENSE) **MCP Tools:** `use_figma`

Extracts visible UI strings from the current Figma page or selected frames, compares them with existing CSV/JSON string files, removes duplicates, generates translations and stable localization keys, exports clean production CSV/JSON, and writes separate localization reports plus a Figma context map.
