# LocaleFlow

LocaleFlow is a skill for extracting localization-ready UI strings from Figma, generating stable keys and translations, and exporting clean production files for product localization.

The default workflow is intentionally small:

```text
strings.csv
strings.json
localization_report.md
```

`strings.csv` and `strings.json` contain the same production table content. The Markdown report keeps concise changelog counts, review items, and report-only strings in one file by appending a timestamped section for each run.

## Install

In Codex, ask:

```text
Install the skill from https://github.com/loshoc/LocaleFlow/tree/main/localeflow
```

Or use the skill installer helper directly:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo loshoc/LocaleFlow \
  --path localeflow
```

Restart Codex after installing so the new skill is loaded.

## What It Does

- Extracts visible Figma text from selected nodes first, then the current page.
- Excludes hidden layers by default.
- Applies Figma visual text casing before export.
- Sorts strings by visual order: top-to-bottom, then left-to-right.
- Generates deterministic semantic localization keys.
- Keeps numeric-only and symbol-only strings out of production exports.
- Replaces numbers inside translatable sentences with placeholders such as `{number_1}`.
- Supports `nt_` text-layer names as non-translatable.
- Compares repeated exports against an existing `strings.csv` or `strings.json`.
- Produces one human-readable report with changelog and review details.

## Output Shape

Production CSV contains only:

```csv
key,zh,en,ja
common.button.buy_now,立即购买,Buy Now,今すぐ購入
```

Production JSON mirrors the same rows:

```json
[
  {
    "key": "common.button.buy_now",
    "zh": "立即购买",
    "en": "Buy Now",
    "ja": "今すぐ購入"
  }
]
```

No Figma node IDs, paths, run IDs, hashes, review flags, or version columns are included in production CSV/JSON.

## Basic Usage

```bash
python3 localeflow/scripts/process_figma_strings.py \
  --input extracted.json \
  --output strings \
  --target-languages en,ja \
  --translations generated-translations.json \
  --dedupe-mode context-aware \
  --non-translatable-prefix nt_ \
  --figma-file "Example App" \
  --page "Account" \
  --scope "Selected frames"
```

By default this writes:

```text
strings.csv
strings.json
localization_report.md
```

The CLI response is compact and includes only output paths plus actionable counts.

`extracted.json` and generated translation JSON are internal handoff formats for the processor. They are not default user-facing deliverables and do not need to be kept unless you want debug or audit input snapshots.

## Extract Only

Use extract-only mode when you want localization-ready source strings and keys without generating translations:

```bash
python3 localeflow/scripts/process_figma_strings.py \
  --input extracted.json \
  --output strings \
  --extract-only \
  --dedupe-mode context-aware
```

This writes `strings.csv`, `strings.json`, and `localization_report.md`. The production files contain only `key` plus the inferred source-language column:

```csv
key,zh
course_name.title.course_name,课程名称
today.label.today,今天
```

Use this mode for copy review, first-pass string inventory, or when translations will be added later by humans or another system.

## Repeated Exports

For later Figma exports, pass the previous production file with `--existing`:

```bash
python3 localeflow/scripts/process_figma_strings.py \
  --input extracted.json \
  --existing strings.csv \
  --output strings \
  --target-languages en,ja \
  --translations generated-translations.json
```

The report changelog classifies production rows as added, changed, existing, removed, or report-only. Existing `key,<source_language>,...` files are supported, including source columns such as `en`, `zh`, or `source`.

## Translation Rules

For the simplest workflow, keep one Markdown file beside your exported files:

```text
localization-rules.md
```

Then pass it to the processor:

```bash
--rules localization-rules.md
```

Recommended shape:

```md
# Localization Rules

## Target Languages

- en
- ja

## Do Not Translate

- API
- 小张

## Glossary

| source | en | ja | context | notes |
| --- | --- | --- | --- | --- |
| 会员卡 | Membership Card | 会員カード | Membership product | Approved UI term |

## Translation Memory

| source | en | ja | context | notes |
| --- | --- | --- | --- | --- |
| 立即购买 | Buy Now | 今すぐ購入 | Primary CTA | Approved full string |

## Style Rules

| scope | rule |
| --- | --- |
| global | Use concise mobile UI wording. |
| button | Keep button labels short. |
| ja | Use natural Japanese UI wording. |
```

Sections:

- `Target Languages`: target languages to export.
- `Do Not Translate`: vocabulary that must stay unchanged, such as brand names, person names, acronyms, product names, IDs, URLs, or API terms.
- `Glossary`: approved translations for terms or short phrases.
- `Translation Memory`: approved translations for full source strings.
- `Style Rules`: plain-language translation instructions. Use scopes such as `global`, `button`, `ja`, or `ja.button`.

CSV and JSON rules are still supported, but Markdown is the recommended format for normal vocabulary and style rules because it is easier to read and review.

Optional rules files can define:

- target languages
- do-not-translate terms
- approved glossary entries
- translation memory
- custom placeholder patterns
- UI-role or language-specific style rules

Rules are applied in this order:

1. Preserve placeholders exactly.
2. Preserve do-not-translate terms.
3. Reuse exact translation memory matches.
4. Apply approved glossary terms.
5. Apply UI-role and target-language style rules.
6. Flag fuzzy matches, missing translations, placeholder errors, and conflicts for review.

## Numeric And Non-Translatable Strings

Numeric-only or symbol-only values are not translated and are excluded from production exports:

```text
999
¥699
9:41
50%
¥
```

Numbers inside sentence-like strings are converted to placeholders before translation:

```text
会员最多可同时持有{number_1} 张期限型卡
```

Text layers named with the `nt_` prefix are extracted for reporting but are excluded from production exports by default.

## Report

`localization_report.md` is the only default report. It appends each export as a timestamped section and includes concise data:

- summary counts
- added, changed, removed, and report-only rows
- report-only strings
- placeholder errors
- missing translations
- entries requiring review

Machine-readable files are opt-in only:

```bash
--report-json localization_report.json
--context-map context_map.json
--changelog-json localization_changelog.json
--changelog-md localization_changelog.md
```

Use these only for automation, debugging, or deeper Figma traceability.

## Skill Files

- Skill instructions: `localeflow/SKILL.md`
- Figma extraction reference: `localeflow/references/figma-extraction.md`
- Processor: `localeflow/scripts/process_figma_strings.py`

## Community Listing Draft

### Localization

#### localeflow

[SOURCE CODE](https://github.com/loshoc/LocaleFlow/tree/main/localeflow) · [MIT](https://github.com/loshoc/LocaleFlow/blob/main/LICENSE) **MCP Tools:** `use_figma`

Extracts visible UI strings from Figma, generates stable semantic localization keys, preserves placeholders and non-translatable content, exports matching production CSV/JSON files, and writes one human-readable localization report with changelog and review guidance.
