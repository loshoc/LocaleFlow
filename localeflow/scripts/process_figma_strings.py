#!/usr/bin/env python3
"""Process Figma text extraction records into localization-ready CSV or JSON."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

PROCESSOR_VERSION = "0.2.0"

PLACEHOLDER_RE = re.compile(
    r"(\{\{[^{}]+\}\}|\$\{[^{}]+\}|\{[^{}]+\}|%[@dfs]|[$][A-Za-z_][A-Za-z0-9_]*|"
    r"<[A-Za-z][^>]*>.*?</[A-Za-z][^>]*>|\[[A-Za-z0-9_-]+\])"
)
NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])[$€£¥￥]?\s?\d+(?:[.,]\d+)?%?(?![A-Za-z0-9_])")
NUMERIC_LIKE_RE = re.compile(r"^[\s\d.,:%$€£¥￥+\-/]+$")
SYMBOL_LIKE_RE = re.compile(r"^[\s$€£¥￥%:.,+\-/]+$")
GENERIC_CONTEXT_NAMES = {
    "",
    "_",
    "frame",
    "frame_value",
    "content",
    "button",
    "header",
    "item",
    "time",
    "text",
    "title",
    "value",
    "page",
    "page_value",
}


def normalize_source(text: str) -> str:
    text = (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
        .replace("—", "-")
        .replace("–", "-")
    )
    text = text.replace("\u00a0", " ").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r" {2,}", " ", text).strip()


def is_numeric_like(text: str) -> bool:
    return bool(text and NUMERIC_LIKE_RE.fullmatch(text) and re.search(r"[\d$€£¥￥]", text))


def is_symbol_like(text: str) -> bool:
    return bool(text and SYMBOL_LIKE_RE.fullmatch(text) and re.search(r"[$€£¥￥%]", text))


def is_non_production_source(text: str) -> bool:
    return is_numeric_like(text) or is_symbol_like(text)


def number_placeholders_for_source(text: str) -> tuple[str, list[tuple[str, str]]]:
    if is_non_production_source(text):
        return text, []

    replacements: list[tuple[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        placeholder = f"{{number_{len(replacements) + 1}}}"
        replacements.append((token, placeholder))
        return placeholder

    return NUMBER_TOKEN_RE.sub(replace, text), replacements


def apply_number_placeholders(text: str, replacements: list[tuple[str, str]]) -> str:
    output = text
    for token, placeholder in replacements:
        variants = [token]
        compact_token = re.sub(r"\s+", "", token)
        if compact_token != token:
            variants.append(compact_token)
        for variant in variants:
            pattern = re.compile(rf"(?<![A-Za-z0-9_}}]){re.escape(variant)}(?![A-Za-z0-9_{{])")
            output = pattern.sub(placeholder, output)
    return output


def is_valid_source(text: str, ignore_numeric: bool = False) -> bool:
    if not text:
        return False
    if ignore_numeric and is_non_production_source(text):
        return False
    if is_non_production_source(text):
        return True
    if PLACEHOLDER_RE.search(text):
        return True
    return bool(re.search(r"[A-Za-z0-9\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))


def source_for_key(text: str) -> str:
    text = PLACEHOLDER_RE.sub(" value ", text)
    text = NUMBER_TOKEN_RE.sub(" value ", text)
    return normalize_source(text)


def slug_segment(value: str, fallback: str = "common") -> str:
    value = source_for_key(value).lower()
    value = re.sub(r"['’]", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if len(value) > 56:
        value = value[:56].rstrip("_")
    return value or fallback


def meaningful_segment(value: str) -> str:
    segment = slug_segment(value, "")
    if segment in GENERIC_CONTEXT_NAMES:
        return ""
    if re.fullmatch(r"frame_?\d*", segment):
        return ""
    return segment


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:4]


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def source_hash(source: str) -> str:
    return hashlib.sha256(normalize_source(source).encode("utf-8")).hexdigest()[:12]


def make_run_id(exported_at: str, records: list[dict[str, Any]], entries: list[dict[str, Any]]) -> str:
    payload = {
        "exported_at": exported_at,
        "records_hash": stable_json_hash(records),
        "entries_hash": stable_json_hash(
            [{"key": entry.get("key", ""), "source": entry.get("source", "")} for entry in entries]
        ),
    }
    return f"{exported_at.replace(':', '').replace('-', '').split('.')[0]}-{stable_json_hash(payload)[:8]}"


def load_json_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    def with_indexes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records = [dict(item) for item in items if isinstance(item, dict)]
        for index, record in enumerate(records):
            record.setdefault("_record_index", index)
        return records

    if isinstance(data, list):
        return with_indexes(data)
    if isinstance(data, dict):
        for key in ("records", "strings", "items"):
            items = data.get(key)
            if isinstance(items, list):
                return with_indexes(items)
    raise ValueError(f"Unsupported extracted JSON shape: {path}")


def row_source_value(row: dict[str, Any], preferred_source_language: str = "") -> str:
    for column in ("source", preferred_source_language, "en"):
        if column and row.get(column):
            return normalize_source(str(row.get(column) or ""))
    for column, value in row.items():
        if column and column not in METADATA_COLUMNS and value:
            return normalize_source(str(value))
    return ""


def load_existing(path: Path | None, source_language: str = "") -> tuple[dict[str, str], dict[str, str], list[dict[str, str]]]:
    by_key: dict[str, str] = {}
    by_source: dict[str, str] = {}
    rows_out: list[dict[str, str]] = []
    if not path:
        return by_key, by_source, rows_out

    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("key") or "").strip()
                source = row_source_value(row, source_language)
                if key and source:
                    by_key[key] = source
                    by_source[source] = key
                    rows_out.append({str(k): str(v) for k, v in row.items() if k})
        return by_key, by_source, rows_out

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("strings"), list):
        rows = data["strings"]
    elif isinstance(data, dict):
        rows = []
        for key, value in data.items():
            if isinstance(value, dict):
                row = {"key": key}
                row.update({str(k): str(v) for k, v in value.items()})
                rows.append(row)
            else:
                rows.append({"key": key, "source": value})
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        source = row_source_value(row, source_language)
        if key and source:
            by_key[key] = source
            by_source[source] = key
            rows_out.append({str(k): str(v) for k, v in row.items()})
    return by_key, by_source, rows_out


METADATA_COLUMNS = {
    "key",
    "source",
    "status",
    "context",
    "page",
    "frame",
    "node_name",
    "node_id",
    "ui_role",
    "figma_path",
    "notes",
    "tm_status",
    "matched_source",
    "suggested_translation",
    "match_confidence",
    "needs_review",
    "matched_glossary_terms",
    "do_not_translate_terms",
    "placeholder_status",
    "report_tags",
    "review_severity",
    "style_notes",
    "generated_translation_languages",
    "missing_translation_languages",
    "non_translatable",
    "non_translatable_reason",
    "non_production",
    "non_production_reason",
}


def infer_target_languages(existing_rows: list[dict[str, str]]) -> list[str]:
    languages: list[str] = []
    for row in existing_rows:
        for column in row:
            if column in METADATA_COLUMNS:
                continue
            if column and column not in languages:
                languages.append(column)
    return languages


def infer_source_language(records: list[dict[str, Any]]) -> str:
    sample = " ".join(
        normalize_source(record_text(record))
        for record in records[:100]
    )
    if not sample.strip():
        return "und"
    if re.search(r"[\u3040-\u30ff]", sample):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", sample):
        return "zh"
    if re.search(r"[\uac00-\ud7af]", sample):
        return "ko"
    if re.search(r"[\u0400-\u04ff]", sample):
        return "ru"
    latin_letters = re.findall(r"[A-Za-z]", sample)
    if latin_letters:
        return "en"
    return "und"


def record_text(record: dict[str, Any]) -> str:
    return str(record.get("display_text") or record.get("raw_text") or record.get("source") or record.get("text") or "")


def is_non_translatable_record(record: dict[str, Any], prefix: str = "nt_") -> bool:
    if bool(record.get("non_translatable")) or bool(record.get("hasNonTranslatable")):
        return True
    node_name = str(record.get("node_name") or record.get("name") or "")
    return bool(prefix and node_name.startswith(prefix))


def visual_sort_key(record: dict[str, Any]) -> tuple[str, str, float, float, str]:
    has_position = any(record.get(name) not in {None, ""} for name in ("absolute_y", "absolute_x", "y", "x"))
    if not has_position:
        return ("", "", 0.0, 0.0, f"{int(record.get('_record_index') or 0):012d}")

    def number_value(*names: str) -> float:
        for name in names:
            value = record.get(name)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    continue
        return 0.0

    return (
        str(record.get("page") or ""),
        str(record.get("frame") or record.get("page") or ""),
        number_value("absolute_y", "y"),
        number_value("absolute_x", "x"),
        str(record.get("node_id") or record.get("id") or ""),
    )


def record_number(record: dict[str, Any], *names: str) -> float:
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def empty_rules() -> dict[str, Any]:
    return {
        "source_language": "auto",
        "target_languages": [],
        "do_not_translate": [],
        "glossary": [],
        "translation_memory": [],
        "placeholder_patterns": [],
        "style_rules": {},
        "rule_conflicts": [],
    }


def load_rules(path: Path | None) -> dict[str, Any]:
    rules = empty_rules()
    if not path:
        return rules

    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row_type = (row.get("type") or "").strip()
                source = (row.get("source") or "").strip()
                if not source:
                    continue
                if row_type == "do_not_translate":
                    rules["do_not_translate"].append(source)
                elif row_type == "glossary":
                    rules["glossary"].append(
                        {
                            "source": source,
                            "target_language": (row.get("target_language") or "").strip(),
                            "translation": (row.get("translation") or "").strip(),
                            "context": (row.get("context") or "").strip(),
                            "notes": (row.get("notes") or "").strip(),
                        }
                    )
                elif row_type == "translation_memory":
                    rules["translation_memory"].append(
                        {
                            "source": source,
                            "target_language": (row.get("target_language") or "").strip(),
                            "translation": (row.get("translation") or "").strip(),
                            "context": (row.get("context") or "").strip(),
                            "notes": (row.get("notes") or "").strip(),
                        }
                    )
        rules["rule_conflicts"] = detect_rule_conflicts(rules)
        return rules

    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Rules file must be a JSON object or supported CSV: {path}")
    rules.update(loaded)
    rules.setdefault("do_not_translate", [])
    rules.setdefault("glossary", [])
    rules.setdefault("translation_memory", [])
    rules.setdefault("placeholder_patterns", [])
    rules.setdefault("style_rules", {})
    rules["rule_conflicts"] = detect_rule_conflicts(rules)
    return rules


def load_translations(path: Path | None) -> dict[tuple[str, str, str], str]:
    translations: dict[tuple[str, str, str], str] = {}
    if not path:
        return translations

    def add(row: dict[str, Any]) -> None:
        key = str(row.get("key") or "").strip()
        source = normalize_source(str(row.get("source") or ""))
        language = str(row.get("target_language") or row.get("language") or "").strip()
        translation = str(row.get("translation") or "").strip()
        if language and translation:
            translations[(key, source, language)] = translation

    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if "target_language" in row or "language" in row:
                    add(row)
                    continue
                key = str(row.get("key") or "").strip()
                source = normalize_source(str(row.get("source") or ""))
                for language, translation in row.items():
                    if language not in {"key", "source"} and translation:
                        translations[(key, source, language)] = str(translation)
        return translations

    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]]
    if isinstance(data, list):
        rows = [row for row in data if isinstance(row, dict)]
    elif isinstance(data, dict) and isinstance(data.get("translations"), list):
        rows = [row for row in data["translations"] if isinstance(row, dict)]
    elif isinstance(data, dict):
        rows = []
        for key, value in data.items():
            if isinstance(value, dict):
                row = {"key": key}
                row.update(value)
                rows.append(row)
    else:
        rows = []

    for row in rows:
        if "target_language" in row or "language" in row:
            add(row)
            continue
        key = str(row.get("key") or "").strip()
        source = normalize_source(str(row.get("source") or ""))
        for language, translation in row.items():
            if language not in {"key", "source"} and translation:
                translations[(key, source, str(language))] = str(translation)
    return translations


def detect_rule_conflicts(rules: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    dnt = {str(term).casefold() for term in rules.get("do_not_translate", [])}

    glossary_terms = defaultdict(set)
    glossary_contexts = defaultdict(set)
    for item in rules.get("glossary", []):
        source = normalize_source(str(item.get("source") or ""))
        language = str(item.get("target_language") or "")
        translation = str(item.get("translation") or "")
        context = str(item.get("context") or "")
        if not source:
            continue
        if source.casefold() in dnt:
            conflicts.append(
                {
                    "type": "do_not_translate_glossary_overlap",
                    "source": source,
                    "suggestion": "Remove the term from one list, or make the glossary context-specific.",
                }
            )
        glossary_terms[(source.casefold(), language)].add(translation)
        glossary_contexts[(source.casefold(), language)].add(context)

    for (source, language), translations in glossary_terms.items():
        clean = {item for item in translations if item}
        if len(clean) > 1:
            conflicts.append(
                {
                    "type": "glossary_conflict",
                    "source": source,
                    "target_language": language,
                    "translations": sorted(clean),
                    "suggestion": "Use context-specific glossary entries or choose one approved translation.",
                }
            )
    for (source, language), contexts in glossary_contexts.items():
        if "" in contexts and len(contexts) > 1:
            conflicts.append(
                {
                    "type": "glossary_context_missing",
                    "source": source,
                    "target_language": language,
                    "suggestion": "Add context to every context-dependent glossary entry.",
                }
            )

    tm_terms = defaultdict(set)
    for item in rules.get("translation_memory", []):
        source = normalize_source(str(item.get("source") or ""))
        language = str(item.get("target_language") or "")
        translation = str(item.get("translation") or "")
        if source:
            tm_terms[(source.casefold(), language)].add(translation)
    for (source, language), translations in tm_terms.items():
        clean = {item for item in translations if item}
        if len(clean) > 1:
            conflicts.append(
                {
                    "type": "translation_memory_conflict",
                    "source": source,
                    "target_language": language,
                    "translations": sorted(clean),
                    "suggestion": "Choose one approved full-string translation or split by context.",
                }
            )

    seen_patterns: set[str] = set()
    for pattern in rules.get("placeholder_patterns", []):
        pattern = str(pattern)
        try:
            re.compile(pattern)
        except re.error as exc:
            conflicts.append(
                {
                    "type": "placeholder_pattern_invalid",
                    "pattern": pattern,
                    "error": str(exc),
                    "suggestion": "Fix or remove the invalid regular expression.",
                }
            )
        if pattern in seen_patterns:
            conflicts.append(
                {
                    "type": "placeholder_pattern_duplicate",
                    "pattern": pattern,
                    "suggestion": "Remove duplicate placeholder patterns.",
                }
            )
        seen_patterns.add(pattern)
    return conflicts


def placeholder_regexes(rules: dict[str, Any]) -> list[re.Pattern[str]]:
    regexes = [PLACEHOLDER_RE]
    for pattern in rules.get("placeholder_patterns", []):
        try:
            regexes.append(re.compile(str(pattern)))
        except re.error:
            continue
    return regexes


def extract_placeholders(text: str, regexes: list[re.Pattern[str]]) -> list[str]:
    found: list[str] = []
    for regex in regexes:
        for match in regex.finditer(text):
            value = match.group(0)
            if value not in found:
                found.append(value)
    return found


def placeholder_status(source: str, translations: dict[str, str], regexes: list[re.Pattern[str]]) -> str:
    source_counts = Counter(extract_placeholders(source, regexes))
    if not source_counts:
        return "ok"
    for translation in translations.values():
        if not translation:
            continue
        if Counter(extract_placeholders(translation, regexes)) != source_counts:
            return "placeholder_error"
    return "ok"


def contains_term(source: str, term: str) -> bool:
    return term.casefold() in source.casefold()


def infer_do_not_translate_terms(records: list[dict[str, Any]]) -> list[str]:
    candidates: Counter[str] = Counter()
    generic_sentence_starts = {
        "Welcome",
        "Connection",
        "Set",
        "Display",
        "Cancel",
        "Save",
        "Done",
        "Apply",
        "Open",
        "Close",
        "Error",
        "Settings",
        "Account",
        "Profile",
    }
    for record in records:
        source = normalize_source(record_text(record))
        placeholders = set(extract_placeholders(source, [PLACEHOLDER_RE]))
        scrubbed = source
        for placeholder in placeholders:
            scrubbed = scrubbed.replace(placeholder, " ")
        tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9+._-]{1,}\b", scrubbed)
        for token in tokens:
            if token in generic_sentence_starts:
                continue
            if token.isupper() and len(token) >= 2:
                candidates[token] += 1
                continue
            if re.search(r"[A-Z].*[A-Z]", token) and not token.isupper():
                candidates[token] += 1
                continue
            if re.search(r"\d", token) and re.search(r"[A-Za-z]", token):
                candidates[token] += 1
    return sorted(candidates)


def matched_do_not_translate(source: str, rules: dict[str, Any], inferred_terms: list[str]) -> tuple[list[str], list[str]]:
    explicit = [str(term) for term in rules.get("do_not_translate", []) if contains_term(source, str(term))]
    inferred = [term for term in inferred_terms if contains_term(source, term) and term not in explicit]
    return explicit, inferred


def matched_glossary(source: str, rules: dict[str, Any], target_languages: list[str]) -> list[dict[str, str]]:
    matches = []
    languages = set(target_languages)
    for item in rules.get("glossary", []):
        term = str(item.get("source") or "")
        language = str(item.get("target_language") or "")
        if term and contains_term(source, term) and (not languages or language in languages):
            matches.append(
                {
                    "source": term,
                    "target_language": language,
                    "translation": str(item.get("translation") or ""),
                    "context": str(item.get("context") or ""),
                    "notes": str(item.get("notes") or ""),
                }
            )
    return matches


def tm_matches(source: str, rules: dict[str, Any], target_languages: list[str]) -> tuple[str, dict[str, str], dict[str, Any]]:
    normalized = normalize_source(source)
    exact: dict[str, str] = {}
    best: dict[str, Any] = {"confidence": 0.0}
    languages = set(target_languages)

    for item in rules.get("translation_memory", []):
        tm_source = normalize_source(str(item.get("source") or ""))
        language = str(item.get("target_language") or "")
        translation = str(item.get("translation") or "")
        if languages and language not in languages:
            continue
        if tm_source == normalized and language and translation:
            exact[language] = translation
            continue
        confidence = SequenceMatcher(None, normalized.casefold(), tm_source.casefold()).ratio()
        if confidence > float(best.get("confidence") or 0) and translation:
            best = {
                "matched_source": tm_source,
                "target_language": language,
                "suggested_translation": translation,
                "confidence": round(confidence, 2),
            }

    if exact:
        return "tm_exact_match", exact, {}
    if float(best.get("confidence") or 0) >= 0.75:
        return "tm_fuzzy_match", {}, best
    return "no_tm_match", {}, {}


def style_notes(record: dict[str, Any], rules: dict[str, Any], target_languages: list[str] | None = None) -> list[str]:
    style_rules = rules.get("style_rules") or {}
    if not isinstance(style_rules, dict):
        return []
    role = str(record.get("ui_role") or "text")
    notes = []
    for item in style_rules.get("global", []):
        notes.append(str(item))
    for item in style_rules.get(role, []):
        notes.append(str(item))
    for language in target_languages or []:
        for item in style_rules.get(language, []):
            notes.append(f"{language}: {item}")
        language_roles = style_rules.get(f"{language}.{role}", [])
        for item in language_roles:
            notes.append(f"{language}/{role}: {item}")
    return notes


def infer_context(record: dict[str, Any]) -> str:
    role = str(record.get("ui_role") or "text")
    frame = str(record.get("frame") or record.get("page") or "Figma")
    return f"{role.title()} in {frame}"


def key_context(record: dict[str, Any], source: str, context_hint: str = "") -> str:
    for candidate in (
        record.get("frame"),
        record.get("component"),
        context_hint,
        record.get("node_name"),
        source,
        record.get("page"),
    ):
        segment = meaningful_segment(str(candidate or ""))
        if segment:
            return segment
    return "common"


def key_semantic(record: dict[str, Any], source: str, semantic_hint: str = "", context_hint: str = "") -> str:
    hint_segment = meaningful_segment(semantic_hint)
    if hint_segment:
        return hint_segment
    node_segment = meaningful_segment(str(record.get("node_name") or ""))
    source_segment = slug_segment(source, "text")
    if node_segment and node_segment != key_context(record, source, context_hint):
        return node_segment
    return source_segment


def base_key(record: dict[str, Any], source: str, prefix: str = "", semantic_hint: str = "", context_hint: str = "") -> str:
    role = record.get("ui_role") or "text"
    context = key_context(record, source, context_hint)
    semantic = key_semantic(record, source, semantic_hint, context_hint)
    parts = [context, slug_segment(str(role), "text"), semantic]
    if prefix:
        parts.insert(0, slug_segment(prefix))
    return ".".join(parts)


def dedupe_identity(record: dict[str, Any], normalized: str, mode: str) -> str:
    if mode == "global":
        return normalized
    return "|".join(
        [
            normalized,
            slug_segment(str(record.get("frame") or record.get("page") or "common")),
            slug_segment(str(record.get("ui_role") or "text")),
        ]
    )


def classify_entry(
    key: str,
    source: str,
    existing_by_key: dict[str, str],
    existing_by_source: dict[str, str],
) -> str:
    if source in existing_by_source:
        return "existing"
    if key in existing_by_key and existing_by_key[key] != source:
        return "changed"
    return "new"


def translation_for(
    translations: dict[tuple[str, str, str], str],
    key: str,
    source: str,
    language: str,
) -> str:
    return (
        translations.get((key, source, language))
        or translations.get((key, "", language))
        or translations.get(("", source, language))
        or ""
    )


def key_hint_for(
    translations: dict[tuple[str, str, str], str],
    key: str,
    source: str,
    original_source: str,
    number_replacements: list[tuple[str, str]],
) -> str:
    for language in ("en", "en-US", "en-GB"):
        hint = translation_for(translations, key, source, language) or translation_for(
            translations, key, original_source, language
        )
        if hint:
            return apply_number_placeholders(hint, number_replacements)
    return ""


def detect_source_conflicts(existing_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    keys_by_source: dict[str, set[str]] = defaultdict(set)
    for row in existing_rows:
        key = str(row.get("key") or "").strip()
        source = normalize_source(str(row.get("source") or row.get("en") or ""))
        if key and source:
            keys_by_source[source].add(key)
    conflicts = []
    for source, keys in keys_by_source.items():
        if len(keys) > 1:
            conflicts.append(
                {
                    "type": "source_conflict",
                    "source": source,
                    "keys": sorted(keys),
                    "suggestion": "Review whether these keys represent different contexts or can be consolidated.",
                }
            )
    return conflicts


def make_report_tags(entry: dict[str, Any], duplicate_count: int, key_conflict: bool) -> list[str]:
    tags = [str(entry["status"]), "auto_key_generated"]
    if entry.get("non_production"):
        tags.append("non_production")
    if entry.get("non_translatable"):
        tags.append("non_translatable")
    if duplicate_count > 1:
        tags.append("duplicate")
    if key_conflict:
        tags.append("key_conflict")
    if entry.get("placeholder_status") == "placeholder_error":
        tags.append("placeholder_error")
    if entry.get("matched_glossary_terms"):
        tags.append("glossary_match")
    if entry.get("do_not_translate_terms"):
        tags.append("do_not_translate_match")
    if entry.get("inferred_do_not_translate_terms"):
        tags.append("inferred_do_not_translate")
    if entry.get("tm_status") in {"tm_exact_match", "tm_fuzzy_match"}:
        tags.append(str(entry["tm_status"]))
    if entry.get("generated_translation_languages"):
        tags.append("generated_translation")
    if entry.get("missing_translation_languages"):
        tags.append("missing_translation")
    if entry.get("needs_review"):
        tags.append("needs_review")
    if re.fullmatch(r"[A-Za-z]{1,4}", str(entry.get("source") or "")):
        tags.append("manual_key_recommended")
    return tags


def review_severity(entry: dict[str, Any], key_conflict: bool) -> str:
    if key_conflict or entry.get("placeholder_status") == "placeholder_error":
        return "error"
    if (
        entry.get("tm_status") == "tm_fuzzy_match"
        or entry.get("missing_translation_languages")
        or "manual_key_recommended" in entry.get("report_tags", [])
    ):
        return "warning"
    if entry.get("matched_glossary_terms") or entry.get("do_not_translate_terms") or entry.get("non_translatable"):
        return "info"
    return ""


def build_entries(
    records: list[dict[str, Any]],
    existing_by_key: dict[str, str],
    existing_by_source: dict[str, str],
    dedupe_mode: str,
    key_prefix: str,
    target_languages: list[str],
    rules: dict[str, Any],
    existing_rows: list[dict[str, str]],
    translations: dict[tuple[str, str, str], str],
    ignore_numeric: bool = False,
    non_translatable_prefix: str = "nt_",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    explicit_terms = {str(term).casefold() for term in rules.get("do_not_translate", [])}
    inferred_terms = [term for term in infer_do_not_translate_terms(records) if term.casefold() not in explicit_terms]
    prepared = []
    sorted_records = sorted(records, key=visual_sort_key)
    for record in sorted_records:
        raw = record_text(record)
        normalized = normalize_source(raw)
        if not is_valid_source(normalized, ignore_numeric):
            continue
        source, number_replacements = number_placeholders_for_source(normalized)
        non_production = is_non_production_source(source)
        prepared.append(
            (
                record,
                normalized,
                source,
                number_replacements,
                dedupe_identity(record, source, dedupe_mode),
                is_non_translatable_record(record, non_translatable_prefix),
                non_production,
            )
        )

    identity_counts = Counter(identity for _, _, _, _, identity, _, _ in prepared)
    frame_context_hints: dict[tuple[str, str], str] = {}
    label_candidates: list[tuple[str, float, float, str]] = []
    for record, original_source, source, number_replacements, _, _, non_production in prepared:
        if non_production:
            continue
        role = str(record.get("ui_role") or "")
        if role not in {"label", "title"}:
            continue
        hint = key_hint_for(translations, "", source, original_source, number_replacements)
        if not hint:
            hint = source
        segment = meaningful_segment(hint)
        if not segment:
            continue
        frame_key = (str(record.get("page") or ""), str(record.get("frame") or ""))
        frame_context_hints.setdefault(frame_key, hint)
        label_candidates.append(
            (
                str(record.get("page") or ""),
                record_number(record, "absolute_x", "x"),
                record_number(record, "absolute_y", "y"),
                hint,
            )
        )

    seen_identity: set[str] = set()
    entries: list[dict[str, Any]] = []
    used_keys: dict[str, str] = {}
    conflicts = 0
    placeholder_regex_list = placeholder_regexes(rules)

    for record, original_source, source, number_replacements, identity, non_translatable, non_production in prepared:
        duplicate = identity in seen_identity
        if duplicate:
            continue
        seen_identity.add(identity)

        frame_hint = frame_context_hints.get((str(record.get("page") or ""), str(record.get("frame") or "")), "")
        if not frame_hint and str(record.get("ui_role") or "") == "text":
            record_x = record_number(record, "absolute_x", "x")
            record_y = record_number(record, "absolute_y", "y")
            nearby = [
                (record_y - y, hint)
                for page, x, y, hint in label_candidates
                if page == str(record.get("page") or "") and y <= record_y and abs(x - record_x) <= 96
            ]
            if nearby:
                frame_hint = sorted(nearby, key=lambda item: item[0])[0][1]
        semantic_hint = key_hint_for(translations, "", source, original_source, number_replacements)
        key = existing_by_source.get(source) or base_key(record, source, key_prefix, semantic_hint, frame_hint)
        if key in used_keys and used_keys[key] != source:
            context_suffix = slug_segment(str(record.get("frame") or record.get("page") or "context"), "context")
            key = f"{key}.{context_suffix}"
        if key in used_keys and used_keys[key] != source:
            key = f"{key}_{short_hash(identity)}"
        key_conflict = key in existing_by_key and existing_by_key[key] != source
        if key_conflict:
            conflicts += 1

        used_keys[key] = source
        status = classify_entry(key, source, existing_by_key, existing_by_source)
        tm_status, exact_translations, fuzzy_tm = tm_matches(source, rules, target_languages)
        glossary_matches = matched_glossary(source, rules, target_languages)
        dnt_matches, inferred_dnt_matches = matched_do_not_translate(source, rules, inferred_terms)
        notes_parts = []
        if duplicate or identity_counts[identity] > 1:
            notes_parts.append(f"Duplicate locations: {identity_counts[identity]}")
        if glossary_matches:
            notes_parts.append("Use approved glossary translation.")
        if dnt_matches or inferred_dnt_matches:
            notes_parts.append("Preserve do-not-translate terms exactly.")
        notes_parts.extend(style_notes(record, rules, target_languages))

        language_values = {language: exact_translations.get(language, "") for language in target_languages}
        if non_production or non_translatable:
            language_values = {language: source for language in target_languages}
        for match in glossary_matches:
            language = match["target_language"]
            if (
                language in language_values
                and not language_values[language]
                and source.casefold() == match["source"].casefold()
            ):
                language_values[language] = match["translation"]
        generated_translation_languages = []
        if not non_translatable:
            for language in target_languages:
                generated = translation_for(translations, key, source, language) or translation_for(
                    translations, key, original_source, language
                )
                if generated:
                    generated = apply_number_placeholders(generated, number_replacements)
                    language_values[language] = generated
                    generated_translation_languages.append(language)
        current_placeholder_status = placeholder_status(source, language_values, placeholder_regex_list)
        missing_translation_languages = [language for language in target_languages if not language_values.get(language)]

        entry = {
            "key": key,
            "source": source,
            "status": status,
            "context": record.get("context") or infer_context(record),
            "page": record.get("page") or "",
            "frame": record.get("frame") or "",
            "node_name": record.get("node_name") or "",
            "node_id": record.get("node_id") or record.get("id") or "",
            "ui_role": record.get("ui_role") or "text",
            "figma_path": record.get("figma_path") or "",
            "tm_status": tm_status,
            "matched_source": fuzzy_tm.get("matched_source", ""),
            "suggested_translation": fuzzy_tm.get("suggested_translation", ""),
            "match_confidence": fuzzy_tm.get("confidence", ""),
            "needs_review": (
                bool(fuzzy_tm)
                or bool(missing_translation_languages)
                or current_placeholder_status == "placeholder_error"
                or bool(rules.get("rule_conflicts"))
            ),
            "matched_glossary_terms": ", ".join(match["source"] for match in glossary_matches),
            "do_not_translate_terms": ", ".join(dnt_matches),
            "inferred_do_not_translate_terms": ", ".join(inferred_dnt_matches),
            "placeholder_status": current_placeholder_status,
            "style_notes": " | ".join(style_notes(record, rules, target_languages)),
            "generated_translation_languages": ", ".join(generated_translation_languages),
            "missing_translation_languages": ", ".join(missing_translation_languages),
            "non_translatable": non_translatable,
            "non_translatable_reason": f"Node name starts with {non_translatable_prefix}" if non_translatable else "",
            "non_production": non_production,
            "non_production_reason": "Numeric or symbol-only string" if non_production else "",
            "notes": " | ".join(notes_parts),
        }
        for language in target_languages:
            entry[language] = language_values.get(language, "")
        entry["report_tags"] = make_report_tags(entry, identity_counts[identity], key_conflict)
        severity = review_severity(entry, key_conflict)
        if severity:
            entry["review_severity"] = severity
        entries.append(entry)

    summary = {
        "extracted_records": len(records),
        "non_empty_records": len(prepared),
        "exported_unique_records": len(entries),
        "duplicate_records": sum(max(count - 1, 0) for count in identity_counts.values()),
        "conflicts": conflicts,
        "source_conflicts": detect_source_conflicts(existing_rows),
        "rule_conflicts": rules.get("rule_conflicts", []),
        "inferred_do_not_translate_terms": inferred_terms,
        "status_counts": dict(Counter(entry["status"] for entry in entries)),
        "tm_status_counts": dict(Counter(entry["tm_status"] for entry in entries)),
        "placeholder_status_counts": dict(Counter(entry["placeholder_status"] for entry in entries)),
        "non_translatable_records": sum(1 for entry in entries if entry.get("non_translatable")),
        "non_production_records": sum(1 for entry in entries if entry.get("non_production")),
    }
    return entries, summary


def count_nonempty_terms(entries: list[dict[str, Any]], field: str) -> int:
    count = 0
    for entry in entries:
        value = str(entry.get(field) or "")
        if value:
            count += len([item for item in value.split(",") if item.strip()])
    return count


def build_review_items(
    entries: list[dict[str, Any]],
    rule_conflicts: list[dict[str, Any]],
    source_conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for conflict in source_conflicts:
        items.append(
            {
                "severity": "error",
                "type": "source_conflict",
                "key": ", ".join(conflict.get("keys", [])),
                "source": str(conflict.get("source") or ""),
                "issue": "Same source string appears under multiple existing keys.",
                "suggestion": str(conflict.get("suggestion") or "Review whether the keys need separate contexts."),
            }
        )

    for conflict in rule_conflicts:
        items.append(
            {
                "severity": "error",
                "type": str(conflict.get("type") or "rule_conflict"),
                "key": "",
                "source": str(conflict.get("source") or conflict.get("pattern") or ""),
                "issue": json.dumps(conflict, ensure_ascii=False),
                "suggestion": str(conflict.get("suggestion") or "Resolve the localization rule conflict."),
            }
        )

    for entry in entries:
        if entry.get("non_production"):
            items.append(
                {
                    "severity": "info",
                    "type": "non_production",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": f"String is excluded from production export: {entry.get('non_production_reason')}",
                    "suggestion": "Keep this in the context map/report only; it is numeric or symbol-only UI content.",
                }
            )
        if entry.get("non_translatable"):
            items.append(
                {
                    "severity": "info",
                    "type": "non_translatable",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": f"String is marked non-translatable: {entry.get('non_translatable_reason')}",
                    "suggestion": "Preserve unchanged or exclude from production export according to the selected non-translatable mode.",
                }
            )
        if entry.get("placeholder_status") == "placeholder_error":
            items.append(
                {
                    "severity": "error",
                    "type": "placeholder_error",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": "Target translation placeholders do not match the source placeholders.",
                    "suggestion": "Verify each target translation preserves placeholders exactly.",
                }
            )
        if "key_conflict" in entry.get("report_tags", []):
            items.append(
                {
                    "severity": "error",
                    "type": "key_conflict",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": "Generated key conflicts with a different existing source string.",
                    "suggestion": "Use a more context-specific key before merging.",
                }
            )
        if entry.get("tm_status") == "tm_fuzzy_match":
            items.append(
                {
                    "severity": "warning",
                    "type": "tm_fuzzy_match",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": f"Similar translation memory source found: {entry.get('matched_source')}",
                    "suggestion": "Review the suggested translation before reuse.",
                }
            )
        if entry.get("missing_translation_languages"):
            items.append(
                {
                    "severity": "warning",
                    "type": "missing_translation",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": f"Missing target translations: {entry.get('missing_translation_languages')}",
                    "suggestion": "Generate or provide translations for every target language before release.",
                }
            )
        if entry.get("inferred_do_not_translate_terms"):
            items.append(
                {
                    "severity": "info",
                    "type": "inferred_do_not_translate",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": f"LocaleFlow inferred these terms should remain unchanged: {entry.get('inferred_do_not_translate_terms')}",
                    "suggestion": "Go ahead with this decision, or ask LocaleFlow to translate these terms if they should be localized.",
                }
            )
        if "manual_key_recommended" in entry.get("report_tags", []):
            items.append(
                {
                    "severity": "warning",
                    "type": "ambiguous_short_string",
                    "key": entry["key"],
                    "source": entry["source"],
                    "issue": "Short UI copy may be ambiguous across languages.",
                    "suggestion": "Add context or choose a more specific key if the meaning is product-specific.",
                }
            )
    return items


def build_frame_breakdown(
    records: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    dedupe_mode: str,
) -> list[dict[str, Any]]:
    scanned = Counter()
    extracted = Counter()
    identities_by_frame: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in records:
        raw = record_text(record)
        frame_key = (str(record.get("page") or ""), str(record.get("frame") or record.get("page") or ""))
        scanned[frame_key] += 1
        normalized = normalize_source(raw)
        if normalized:
            extracted[frame_key] += 1
            source, _ = number_placeholders_for_source(normalized)
            identities_by_frame[frame_key].append(dedupe_identity(record, source, dedupe_mode))

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        grouped[(str(entry.get("page") or ""), str(entry.get("frame") or ""))].append(entry)

    all_keys = set(scanned) | set(grouped)
    rows = []
    for page, frame in sorted(all_keys):
        frame_entries = grouped[(page, frame)]
        identity_counts = Counter(identities_by_frame.get((page, frame), []))
        rows.append(
            {
                "page": page,
                "frame": frame,
                "text_layers_scanned": scanned[(page, frame)],
                "strings_extracted": extracted[(page, frame)],
                "unique_strings": len(frame_entries),
                "new_strings": sum(1 for entry in frame_entries if entry.get("status") == "new"),
                "existing_strings": sum(1 for entry in frame_entries if entry.get("status") == "existing"),
                "changed_strings": sum(1 for entry in frame_entries if entry.get("status") == "changed"),
                "duplicates": sum(max(count - 1, 0) for count in identity_counts.values()),
                "needs_review": sum(1 for entry in frame_entries if entry.get("needs_review")),
                "key_conflicts": sum(1 for entry in frame_entries if "key_conflict" in entry.get("report_tags", [])),
                "placeholder_errors": sum(1 for entry in frame_entries if entry.get("placeholder_status") == "placeholder_error"),
            }
        )
    return sorted(rows, key=lambda row: (row["new_strings"], row["needs_review"], row["key_conflicts"]), reverse=True)


def impact_level(summary: dict[str, Any], report_summary: dict[str, Any]) -> dict[str, str]:
    if (
        report_summary["key_conflicts"]
        or report_summary["source_conflicts"]
        or report_summary["placeholder_errors"]
        or report_summary["rule_conflicts"]
        or report_summary["missing_translations"]
        or report_summary["new_strings"] >= 20
    ):
        reasons = []
        if report_summary["key_conflicts"]:
            reasons.append(f"{report_summary['key_conflicts']} key conflicts")
        if report_summary["source_conflicts"]:
            reasons.append(f"{report_summary['source_conflicts']} source conflicts")
        if report_summary["placeholder_errors"]:
            reasons.append(f"{report_summary['placeholder_errors']} placeholder errors")
        if report_summary["rule_conflicts"]:
            reasons.append(f"{report_summary['rule_conflicts']} rule conflicts")
        if report_summary["missing_translations"]:
            reasons.append(f"{report_summary['missing_translations']} missing translations")
        if report_summary["new_strings"] >= 20:
            reasons.append(f"{report_summary['new_strings']} new strings")
        return {"level": "high_impact", "reason": "High impact: " + ", ".join(reasons) + "."}
    if report_summary["new_strings"] > 5 or report_summary["tm_fuzzy_matches"] or report_summary["needs_review"]:
        return {
            "level": "medium_impact",
            "reason": (
                f"{report_summary['new_strings']} new strings, "
                f"{report_summary['tm_fuzzy_matches']} fuzzy translation memory matches, "
                f"and {report_summary['needs_review']} review items were found. No blocking errors detected."
            ),
        }
    return {
        "level": "low_impact",
        "reason": "Only a few new strings were found and no blocking conflicts or placeholder errors were detected.",
    }


def build_report(
    records: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    summary: dict[str, Any],
    source_language: str,
    target_languages: list[str],
    dedupe_mode: str,
    figma_file: str,
    page: str,
    scope: str,
    figma_file_key: str = "",
    figma_url: str = "",
    existing_file_hash: str = "",
    rules_file_hash: str = "",
    previous_context_hash: str = "",
) -> dict[str, Any]:
    status_counts = Counter(entry.get("status") for entry in entries)
    tm_counts = Counter(entry.get("tm_status") for entry in entries)
    placeholder_errors = sum(1 for entry in entries if entry.get("placeholder_status") == "placeholder_error")
    non_translatable = sum(1 for entry in entries if entry.get("non_translatable"))
    non_production = sum(1 for entry in entries if entry.get("non_production"))
    rule_conflicts = summary.get("rule_conflicts", [])
    source_conflicts = summary.get("source_conflicts", [])
    exported_at = datetime.now(timezone.utc).isoformat()
    run_id = make_run_id(exported_at, records, entries)
    extraction_hash = stable_json_hash(records)
    entries_hash = stable_json_hash(
        [{"key": entry.get("key", ""), "source": entry.get("source", "")} for entry in entries]
    )
    report_summary = {
        "export_run_id": run_id,
        "figma_file": figma_file,
        "figma_file_key": figma_file_key,
        "figma_url": figma_url,
        "page": page,
        "scope": scope,
        "exported_at": exported_at,
        "processor_version": PROCESSOR_VERSION,
        "rules_version": rules_file_hash,
        "source_extraction_hash": extraction_hash,
        "entries_hash": entries_hash,
        "existing_file_hash": existing_file_hash,
        "previous_context_hash": previous_context_hash,
        "source_language": source_language,
        "target_languages": target_languages,
        "text_layers_scanned": len(records),
        "strings_extracted": summary["non_empty_records"],
        "unique_strings": len(entries),
        "existing_strings": status_counts.get("existing", 0),
        "new_strings": status_counts.get("new", 0),
        "changed_strings": status_counts.get("changed", 0),
        "duplicates": summary["duplicate_records"],
        "key_conflicts": summary["conflicts"],
        "source_conflicts": len(source_conflicts),
        "placeholder_errors": placeholder_errors,
        "rule_conflicts": len(rule_conflicts),
        "do_not_translate_matches": count_nonempty_terms(entries, "do_not_translate_terms"),
        "inferred_do_not_translate_matches": count_nonempty_terms(entries, "inferred_do_not_translate_terms"),
        "glossary_matches": count_nonempty_terms(entries, "matched_glossary_terms"),
        "tm_exact_matches": tm_counts.get("tm_exact_match", 0),
        "tm_fuzzy_matches": tm_counts.get("tm_fuzzy_match", 0),
        "missing_translations": count_nonempty_terms(entries, "missing_translation_languages"),
        "needs_review": sum(1 for entry in entries if entry.get("needs_review")),
        "non_translatable": non_translatable,
        "non_production": non_production,
    }
    frame_breakdown = build_frame_breakdown(records, entries, dedupe_mode)
    review_items = build_review_items(entries, rule_conflicts, source_conflicts)
    return {
        "report_summary": report_summary,
        "change_impact": impact_level(summary, report_summary),
        "frame_breakdown": frame_breakdown,
        "review_items": review_items,
        "rule_conflicts": rule_conflicts,
        "source_conflicts": source_conflicts,
        "inferred_do_not_translate_terms": summary.get("inferred_do_not_translate_terms", []),
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(output)


def write_report_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report_markdown(path: Path, report: dict[str, Any], changelog: dict[str, Any] | None = None) -> None:
    summary = report["report_summary"]
    impact = report["change_impact"]
    frame_rows = report["frame_breakdown"][:10]
    review_rows = report["review_items"][:25]
    changelog = changelog or {"summary": {}, "added": [], "changed": [], "removed": [], "report_only": []}
    changelog_summary = changelog.get("summary", {})

    def changelog_rows(items: list[dict[str, Any]], include_reason: bool = False) -> list[list[str]]:
        rows = []
        for item in items[:50]:
            row = [item.get("key", ""), item.get("source", "")]
            if include_reason:
                row.append(item.get("reason", ""))
            rows.append(row)
        return rows

    lines = [
        "# Localization Extraction Report",
        "",
        "## Summary",
        "",
        f"- Figma file: {summary['figma_file'] or ''}",
        f"- Page: {summary['page'] or ''}",
        f"- Scope: {summary['scope'] or ''}",
        f"- Source language: {summary['source_language']}",
        f"- Target languages: {', '.join(summary['target_languages'])}",
        f"- Text layers scanned: {summary['text_layers_scanned']}",
        f"- Valid strings extracted: {summary['strings_extracted']}",
        f"- Unique strings: {summary['unique_strings']}",
        "",
        "## Change Impact",
        "",
        f"- Level: {impact['level']}",
        f"- Reason: {impact['reason']}",
        "",
        "## String Status",
        "",
        markdown_table(
            ["Status", "Count"],
            [
                ["Existing strings", summary["existing_strings"]],
                ["New strings", summary["new_strings"]],
                ["Changed strings", summary["changed_strings"]],
                ["Duplicates", summary["duplicates"]],
                ["Key conflicts", summary["key_conflicts"]],
                ["Source conflicts", summary["source_conflicts"]],
                ["Placeholder errors", summary["placeholder_errors"]],
                ["Missing translations", summary["missing_translations"]],
                ["Needs review", summary["needs_review"]],
                ["Non-translatable", summary["non_translatable"]],
                ["Report-only strings", summary["non_production"]],
            ],
        ),
        "",
        "## Changelog",
        "",
        markdown_table(
            ["Type", "Count"],
            [
                ["Added", changelog_summary.get("added", 0)],
                ["Changed", changelog_summary.get("changed", 0)],
                ["Existing", changelog_summary.get("existing", 0)],
                ["Removed", changelog_summary.get("removed", 0)],
                ["Report-only", changelog_summary.get("report_only", 0)],
            ],
        ),
        "",
        "### Added",
        "",
        markdown_table(["Key", "Source"], changelog_rows(changelog.get("added", [])) or [["None", ""]]),
        "",
        "### Changed",
        "",
        markdown_table(["Key", "Source"], changelog_rows(changelog.get("changed", [])) or [["None", ""]]),
        "",
        "### Removed",
        "",
        markdown_table(["Key", "Source"], changelog_rows(changelog.get("removed", [])) or [["None", ""]]),
        "",
        "### Report-Only",
        "",
        markdown_table(
            ["Key", "Source", "Reason"],
            changelog_rows(changelog.get("report_only", []), include_reason=True) or [["None", "", ""]],
        ),
        "",
        "## Localization Rule Matches",
        "",
        markdown_table(
            ["Type", "Count"],
            [
                ["Do-not-translate matches", summary["do_not_translate_matches"]],
                ["Inferred do-not-translate matches", summary["inferred_do_not_translate_matches"]],
                ["Glossary matches", summary["glossary_matches"]],
                ["Translation memory exact matches", summary["tm_exact_matches"]],
                ["Translation memory fuzzy matches", summary["tm_fuzzy_matches"]],
                ["Rule conflicts", summary["rule_conflicts"]],
            ],
        ),
        "",
        "## Inferred Do-Not-Translate Terms",
        "",
        (
            "LocaleFlow inferred these terms should remain unchanged. Go ahead with this decision, "
            "or ask LocaleFlow to translate specific terms if they should be localized."
        ),
        "",
        markdown_table(
            ["Term"],
            [[term] for term in report.get("inferred_do_not_translate_terms", [])] or [["None"]],
        ),
        "",
        "## Screens With Most New Or Problematic Strings",
        "",
        markdown_table(
            ["Frame", "New Strings", "Needs Review", "Conflicts"],
            [
                [f"{row['page']} / {row['frame']}", row["new_strings"], row["needs_review"], row["key_conflicts"]]
                for row in frame_rows
            ],
        ),
        "",
        "## Items Requiring Review",
        "",
        markdown_table(
            ["Severity", "Key", "Source", "Issue", "Suggested Action"],
            [
                [row["severity"], row["key"], row["source"], row["issue"], row["suggestion"]]
                for row in review_rows
            ],
        ),
        "",
        "## Suggested Next Actions",
        "",
        f"1. Review {summary['needs_review']} strings marked as `needs_review`.",
        f"2. Resolve {summary['key_conflicts']} key conflicts before merging the exported string file.",
        f"3. Resolve {summary['source_conflicts']} source conflicts in the existing localization file.",
        f"4. Fix {summary['placeholder_errors']} placeholder errors.",
        f"5. Add {summary['missing_translations']} missing target translations.",
        f"6. Confirm {summary['tm_fuzzy_matches']} fuzzy translation memory matches before reuse.",
        "7. Add missing standard translations for repeated terms if needed.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_production_rows(
    existing_rows: list[dict[str, str]],
    entries: list[dict[str, Any]],
    target_languages: list[str],
    non_translatable_mode: str = "exclude",
    source_language: str = "",
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    ordered_keys: list[str] = []

    for row in existing_rows:
        key = str(row.get("key") or "").strip()
        source = row_source_value(row, source_language)
        if not key or not source:
            continue
        clean = {"key": key, "source": source}
        for language in target_languages:
            clean[language] = str(row.get(language) or "")
        merged[key] = clean
        ordered_keys.append(key)

    for entry in entries:
        if non_translatable_mode == "exclude" and entry.get("non_translatable"):
            continue
        if entry.get("non_production"):
            continue
        key = str(entry.get("key") or "").strip()
        if not key:
            continue
        if key not in merged:
            ordered_keys.append(key)
            merged[key] = {"key": key, "source": str(entry.get("source") or "")}
            for language in target_languages:
                merged[key][language] = ""
        else:
            merged[key]["source"] = str(entry.get("source") or merged[key]["source"])
        for language in target_languages:
            value = str(entry.get(language) or "")
            if value:
                merged[key][language] = value

    return [merged[key] for key in ordered_keys if key in merged]


def source_column_name(source_language: str) -> str:
    language = (source_language or "").strip()
    if not language or language in {"auto", "und"}:
        return "source"
    return language


def write_production_csv(path: Path, rows: list[dict[str, str]], target_languages: list[str], source_language: str) -> None:
    source_column = source_column_name(source_language)
    fields = ["key", source_column, *[language for language in target_languages if language != source_column]]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            output_row = {field: row.get(field, "") for field in fields}
            output_row[source_column] = row.get("source", "")
            writer.writerow(output_row)


def write_production_json(path: Path, rows: list[dict[str, str]], target_languages: list[str], source_language: str) -> None:
    source_column = source_column_name(source_language)
    fields = ["key", source_column, *[language for language in target_languages if language != source_column]]
    payload = []
    for row in rows:
        output_row = {field: row.get(field, "") for field in fields}
        output_row[source_column] = row.get("source", "")
        payload.append(output_row)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_advanced_csv(path: Path, entries: list[dict[str, Any]], target_languages: list[str]) -> None:
    fields = [
        "key",
        "source",
        *target_languages,
        "status",
        "tm_status",
        "matched_source",
        "suggested_translation",
        "match_confidence",
        "needs_review",
        "context",
        "page",
        "frame",
        "node_name",
        "node_id",
        "ui_role",
        "figma_path",
        "matched_glossary_terms",
        "do_not_translate_terms",
        "inferred_do_not_translate_terms",
        "placeholder_status",
        "report_tags",
        "review_severity",
        "generated_translation_languages",
        "missing_translation_languages",
        "non_translatable",
        "non_translatable_reason",
        "non_production",
        "non_production_reason",
        "style_notes",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for entry in entries:
            row = {field: entry.get(field, "") for field in fields}
            row["report_tags"] = ", ".join(entry.get("report_tags", []))
            writer.writerow(row)


def write_advanced_json(
    path: Path,
    entries: list[dict[str, Any]],
    source_language: str,
    target_languages: list[str],
    dedupe_mode: str,
    summary: dict[str, Any],
    report: dict[str, Any] | None = None,
) -> None:
    payload = {
        "metadata": {
            "figma_file": "",
            "page": "",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_language": source_language,
            "target_languages": target_languages,
            "dedupe_mode": dedupe_mode,
            "summary": summary,
        },
        "report_summary": report["report_summary"] if report else {},
        "strings": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_context_map(
    records: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    dedupe_mode: str,
    run_id: str = "",
    previous_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_context = previous_context or {}
    entry_by_identity: dict[str, dict[str, Any]] = {}
    entry_by_source: dict[str, dict[str, Any]] = {}
    for entry in entries:
        source = normalize_source(str(entry.get("source") or ""))
        entry_by_source[source] = entry
        synthetic_record = {
            "frame": entry.get("frame", ""),
            "page": entry.get("page", ""),
            "ui_role": entry.get("ui_role", "text"),
        }
        entry_by_identity[dedupe_identity(synthetic_record, source, dedupe_mode)] = entry

    context: dict[str, Any] = {}
    for record in records:
        normalized = normalize_source(record_text(record))
        source, _ = number_placeholders_for_source(normalized)
        if not source:
            continue
        identity = dedupe_identity(record, source, dedupe_mode)
        entry = entry_by_identity.get(identity) or entry_by_source.get(source)
        if not entry:
            continue
        key = str(entry["key"])
        previous_item = previous_context.get(key) if isinstance(previous_context.get(key), dict) else {}
        first_seen_run_id = (
            previous_item.get("first_seen_run_id")
            or previous_item.get("last_seen_run_id")
            or run_id
        )
        item = context.setdefault(
            key,
            {
                "source": entry.get("source", ""),
                "source_hash": source_hash(str(entry.get("source") or "")),
                "figma_nodes": [],
                "figma_paths": [],
                "page": entry.get("page", ""),
                "frame": entry.get("frame", ""),
                "ui_role": entry.get("ui_role", ""),
                "status": entry.get("status", ""),
                "matched_glossary_terms": [],
                "do_not_translate_matches": [],
                "inferred_do_not_translate_matches": [],
                "needs_review": bool(entry.get("needs_review")),
                "non_translatable": bool(entry.get("non_translatable")),
                "non_translatable_reason": entry.get("non_translatable_reason", ""),
                "non_production": bool(entry.get("non_production")),
                "non_production_reason": entry.get("non_production_reason", ""),
                "first_seen_run_id": first_seen_run_id,
                "last_seen_run_id": run_id,
            },
        )
        if run_id:
            item.setdefault("first_seen_run_id", first_seen_run_id)
            item["last_seen_run_id"] = run_id
        node_id = str(record.get("node_id") or record.get("id") or "")
        path = str(record.get("figma_path") or "")
        if node_id and node_id not in item["figma_nodes"]:
            item["figma_nodes"].append(node_id)
        if path and path not in item["figma_paths"]:
            item["figma_paths"].append(path)
        item["matched_glossary_terms"] = [term.strip() for term in str(entry.get("matched_glossary_terms") or "").split(",") if term.strip()]
        item["do_not_translate_matches"] = [term.strip() for term in str(entry.get("do_not_translate_terms") or "").split(",") if term.strip()]
        item["inferred_do_not_translate_matches"] = [
            term.strip() for term in str(entry.get("inferred_do_not_translate_terms") or "").split(",") if term.strip()
        ]
    return context


def write_context_map(path: Path, context_map: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_context_map(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("strings"), dict):
        return {str(key): value for key, value in data["strings"].items() if isinstance(value, dict)}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def build_changelog(
    entries: list[dict[str, Any]],
    report: dict[str, Any],
    production_rows: list[dict[str, str]],
    previous_context: dict[str, Any] | None = None,
    existing_rows: list[dict[str, str]] | None = None,
    source_language: str = "",
) -> dict[str, Any]:
    previous_context = previous_context or {}
    existing_rows = existing_rows or []
    production_keys = {row["key"] for row in production_rows if row.get("key")}
    previous_rows_by_key = {
        str(row.get("key") or ""): row
        for row in existing_rows
        if row.get("key")
    }
    added = []
    report_only = []
    changed = []
    existing = []
    for entry in entries:
        item = {
            "key": entry.get("key", ""),
            "source": entry.get("source", ""),
            "source_hash": source_hash(str(entry.get("source") or "")),
            "status": entry.get("status", ""),
        }
        if entry.get("key") not in production_keys:
            reason = entry.get("non_production_reason") or entry.get("non_translatable_reason") or "Excluded from production export"
            report_only.append({**item, "reason": reason})
        elif previous_context:
            previous_item = previous_context.get(str(entry.get("key") or ""))
            if not isinstance(previous_item, dict):
                added.append(item)
            elif previous_item.get("source_hash") and previous_item.get("source_hash") != item["source_hash"]:
                changed.append(
                    {
                        **item,
                        "previous_source": previous_item.get("source", ""),
                        "previous_source_hash": previous_item.get("source_hash", ""),
                    }
                )
            else:
                existing.append(item)
        elif previous_rows_by_key:
            previous_row = previous_rows_by_key.get(str(entry.get("key") or ""))
            if not previous_row:
                added.append(item)
            elif source_hash(row_source_value(previous_row, source_language)) != item["source_hash"]:
                changed.append({**item, "previous_source": row_source_value(previous_row, source_language)})
            else:
                existing.append(item)
        elif entry.get("status") == "new":
            added.append(item)
        elif entry.get("status") == "changed":
            changed.append(item)
        elif entry.get("status") == "existing":
            existing.append(item)

    removed = []
    if previous_context:
        for key, previous_item in sorted(previous_context.items()):
            if not isinstance(previous_item, dict):
                continue
            was_report_only = bool(previous_item.get("non_production")) or bool(previous_item.get("non_translatable"))
            if was_report_only or key in production_keys:
                continue
            removed.append(
                {
                    "key": key,
                    "source": previous_item.get("source", ""),
                    "source_hash": previous_item.get("source_hash", source_hash(str(previous_item.get("source") or ""))),
                    "status": "removed",
                    "last_seen_run_id": previous_item.get("last_seen_run_id", ""),
                }
            )
    elif previous_rows_by_key:
        for key, previous_row in sorted(previous_rows_by_key.items()):
            if key not in production_keys:
                previous_source = row_source_value(previous_row, source_language)
                removed.append(
                    {
                        "key": key,
                        "source": previous_source,
                        "source_hash": source_hash(previous_source),
                        "status": "removed",
                    }
                )
    return {
        "metadata": {
            "export_run_id": report["report_summary"].get("export_run_id", ""),
            "exported_at": report["report_summary"].get("exported_at", ""),
            "processor_version": report["report_summary"].get("processor_version", ""),
            "source_extraction_hash": report["report_summary"].get("source_extraction_hash", ""),
            "entries_hash": report["report_summary"].get("entries_hash", ""),
            "previous_context_hash": report["report_summary"].get("previous_context_hash", ""),
        },
        "summary": {
            "added": len(added),
            "changed": len(changed),
            "existing": len(existing),
            "report_only": len(report_only),
            "removed": len(removed),
        },
        "added": added,
        "changed": changed,
        "existing": existing,
        "removed": removed,
        "report_only": report_only,
    }


def write_changelog_json(path: Path, changelog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(changelog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_changelog_markdown(path: Path, changelog: dict[str, Any]) -> None:
    metadata = changelog["metadata"]
    summary = changelog["summary"]

    def rows_for(items: list[dict[str, Any]], include_reason: bool = False) -> list[list[str]]:
        rows = []
        for item in items[:50]:
            row = [item.get("key", ""), item.get("source", ""), item.get("source_hash", "")]
            if include_reason:
                row.append(item.get("reason", ""))
            rows.append(row)
        return rows

    lines = [
        "# Localization Changelog",
        "",
        f"- Export run ID: {metadata.get('export_run_id', '')}",
        f"- Exported at: {metadata.get('exported_at', '')}",
        f"- Processor version: {metadata.get('processor_version', '')}",
        f"- Source extraction hash: {metadata.get('source_extraction_hash', '')}",
        f"- Entries hash: {metadata.get('entries_hash', '')}",
        f"- Previous context hash: {metadata.get('previous_context_hash', '') or 'None'}",
        "",
        "## Summary",
        "",
        markdown_table(
            ["Type", "Count"],
            [
                ["Added", summary["added"]],
                ["Changed", summary["changed"]],
                ["Existing", summary["existing"]],
                ["Removed", summary["removed"]],
                ["Report-only", summary["report_only"]],
            ],
        ),
        "",
        "## Added",
        "",
        markdown_table(["Key", "Source", "Source Hash"], rows_for(changelog["added"]) or [["None", "", ""]]),
        "",
        "## Changed",
        "",
        markdown_table(["Key", "Source", "Source Hash"], rows_for(changelog["changed"]) or [["None", "", ""]]),
        "",
        "## Removed",
        "",
        markdown_table(["Key", "Source", "Source Hash"], rows_for(changelog["removed"]) or [["None", "", ""]]),
        "",
        "## Report-Only",
        "",
        markdown_table(
            ["Key", "Source", "Source Hash", "Reason"],
            rows_for(changelog["report_only"], include_reason=True) or [["None", "", "", ""]],
        ),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Extracted Figma JSON records")
    parser.add_argument("--existing", type=Path, help="Existing CSV or JSON string file")
    parser.add_argument("--output", required=True, type=Path, help="Output file or base path")
    parser.add_argument("--format", choices=["csv", "json", "both"], default="both")
    parser.add_argument("--export-mode", choices=["production", "advanced"], default="production")
    parser.add_argument("--source-language", default="auto")
    parser.add_argument("--target-languages", default="", help="Comma-separated language columns")
    parser.add_argument("--dedupe-mode", choices=["global", "context-aware"], default="context-aware")
    parser.add_argument("--key-prefix", default="")
    parser.add_argument("--rules", type=Path, help="Localization rules JSON or CSV")
    parser.add_argument("--translations", type=Path, help="Generated translations CSV or JSON")
    parser.add_argument("--report-json", type=Path, help="Optional machine-readable JSON report output")
    parser.add_argument("--report-md", type=Path, help="Optional Markdown report output")
    parser.add_argument("--context-map", type=Path, help="Optional machine-readable context map JSON output")
    parser.add_argument("--previous-context-map", type=Path, help="Previous context_map.json for repeated-export changelog diffs")
    parser.add_argument("--changelog-json", type=Path, help="Optional standalone machine-readable changelog JSON output")
    parser.add_argument("--changelog-md", type=Path, help="Optional standalone changelog Markdown output")
    parser.add_argument("--figma-file", default="", help="Figma file name for report metadata")
    parser.add_argument("--figma-file-key", default="", help="Figma file key for report metadata")
    parser.add_argument("--figma-url", default="", help="Figma source URL for report metadata")
    parser.add_argument("--page", default="", help="Figma page name for report metadata")
    parser.add_argument("--scope", default="", help="Extraction scope label for report metadata")
    parser.add_argument("--ignore-numeric", action="store_true", help="Skip strings that are only numeric or currency-like")
    parser.add_argument("--non-translatable-prefix", default="nt_", help="Text node name prefix that marks copy as non-translatable")
    parser.add_argument(
        "--non-translatable-mode",
        choices=["preserve", "exclude"],
        default="exclude",
        help="For production export, preserve non-translatable strings unchanged in target columns or exclude them. Numeric/symbol-only strings are always report-only. Reports always include them.",
    )
    parser.add_argument(
        "--include-status",
        default="all",
        help="Comma-separated statuses to export, or 'all'",
    )
    args = parser.parse_args()

    previous_context = load_context_map(args.previous_context_map)
    records = load_json_records(args.input)
    source_language = infer_source_language(records) if args.source_language == "auto" else args.source_language
    rules = load_rules(args.rules)
    existing_by_key, existing_by_source, existing_rows = load_existing(args.existing, source_language)
    rule_languages = rules.get("target_languages") if isinstance(rules.get("target_languages"), list) else []
    target_languages = [item.strip() for item in args.target_languages.split(",") if item.strip()]
    if not target_languages:
        target_languages = [str(item) for item in rule_languages if str(item).strip()]
    if not target_languages:
        target_languages = infer_target_languages(existing_rows)
    if not target_languages:
        raise SystemExit(
            "No target languages found. Provide --target-languages, add target language columns to the existing localization file, or set target_languages in the rules file."
        )
    translations = load_translations(args.translations)
    entries, summary = build_entries(
        records,
        existing_by_key,
        existing_by_source,
        args.dedupe_mode,
        args.key_prefix,
        target_languages,
        rules,
        existing_rows,
        translations,
        args.ignore_numeric,
        args.non_translatable_prefix,
    )

    production_merge_existing = args.include_status == "all"
    if args.include_status != "all":
        allowed = {item.strip() for item in args.include_status.split(",") if item.strip()}
        entries = [entry for entry in entries if entry["status"] in allowed]

    report = build_report(
        records,
        entries,
        summary,
        source_language,
        target_languages,
        args.dedupe_mode,
        args.figma_file,
        args.page,
        args.scope,
        args.figma_file_key,
        args.figma_url,
        file_hash(args.existing),
        file_hash(args.rules),
        file_hash(args.previous_context_map),
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "both":
        csv_path = args.output.with_suffix(".csv")
        json_path = args.output.with_suffix(".json")
    else:
        csv_path = args.output
        json_path = args.output

    if args.export_mode == "production":
        production_rows = build_production_rows(
            existing_rows if production_merge_existing else [],
            entries,
            target_languages,
            args.non_translatable_mode,
            source_language,
        )
        if args.format in {"csv", "both"}:
            write_production_csv(csv_path, production_rows, target_languages, source_language)
        if args.format in {"json", "both"}:
            write_production_json(json_path, production_rows, target_languages, source_language)
    else:
        production_rows = []
        if args.format in {"csv", "both"}:
            write_advanced_csv(csv_path, entries, target_languages)
        if args.format in {"json", "both"}:
            write_advanced_json(json_path, entries, source_language, target_languages, args.dedupe_mode, summary, report)

    report_json = args.report_json
    report_md = args.report_md or args.output.parent / "localization_report.md"
    context_map_path = args.context_map
    changelog_json_path = args.changelog_json
    changelog_md_path = args.changelog_md
    changelog = build_changelog(entries, report, production_rows, previous_context, existing_rows, source_language)
    if report_json:
        write_report_json(report_json, {**report, "changelog": changelog})
    write_report_markdown(report_md, report, changelog)
    if context_map_path:
        context_map = build_context_map(
            records,
            entries,
            args.dedupe_mode,
            report["report_summary"].get("export_run_id", ""),
            previous_context,
        )
        write_context_map(context_map_path, context_map)
    if changelog_json_path:
        write_changelog_json(changelog_json_path, changelog)
    if changelog_md_path:
        write_changelog_markdown(changelog_md_path, changelog)

    print(
        json.dumps(
            {
                "output": str(args.output),
                "csv_output": str(csv_path) if args.format in {"csv", "both"} else "",
                "json_output": str(json_path) if args.format in {"json", "both"} else "",
                "report_json": str(report_json) if report_json else "",
                "report_md": str(report_md),
                "context_map": str(context_map_path) if context_map_path else "",
                "changelog_json": str(changelog_json_path) if changelog_json_path else "",
                "changelog_md": str(changelog_md_path) if changelog_md_path else "",
                "counts": {
                    "production_rows": len(production_rows),
                    "text_layers_scanned": report["report_summary"]["text_layers_scanned"],
                    "unique_strings": report["report_summary"]["unique_strings"],
                    "added": changelog["summary"]["added"],
                    "changed": changelog["summary"]["changed"],
                    "existing": changelog["summary"]["existing"],
                    "removed": changelog["summary"]["removed"],
                    "report_only": changelog["summary"]["report_only"],
                    "needs_review": report["report_summary"]["needs_review"],
                    "placeholder_errors": report["report_summary"]["placeholder_errors"],
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
