"""Deterministic, privacy-preserving question mapping for Aleph-prime."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from noema.canonical import JSONValue, digest_bytes, load_json_bytes
from noema.errors import CanonicalizationError, QuestionMappingError
from noema.model import Release, valid_identifier


MAX_QUESTION_BYTES = 512
FORMAL_TEMPLATE_ID = "template:formal-query"
_SPACE = re.compile(r" +")


def _fail(message: str) -> QuestionMappingError:
    return QuestionMappingError(message)


def _object(value: object, keys: set[str], location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _fail(f"{location} fields differ")
    return value


def _array(value: object, location: str) -> list[object]:
    if not isinstance(value, list):
        raise _fail(f"{location} must be an array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(f"{location} must be a non-empty string")
    return value


def _identifier(value: object, location: str) -> str:
    result = _string(value, location)
    if not valid_identifier(result):
        raise _fail(f"{location} must be a stable identifier")
    return result


def _normalise(text: str) -> str:
    return _SPACE.sub(" ", text.strip()).lower()


def _is_catalogue_normal_form(text: str) -> bool:
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError:
        return False
    return (
        bool(encoded)
        and all(0x20 <= byte <= 0x7E for byte in encoded)
        and text == _normalise(text)
    )


class MappingStatus(StrEnum):
    MAPPED = "mapped"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class EntitySpec:
    id: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuestionTemplate:
    id: str
    pattern: str
    operator: str | None
    outcome: str
    reason_code: str | None
    bindings: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def binding_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.bindings)

    def match(self, question: str) -> str | None:
        prefix, suffix = self.pattern.split("{entity}")
        if not question.startswith(prefix) or not question.endswith(suffix):
            return None
        end = len(question) - len(suffix) if suffix else len(question)
        entity_text = question[len(prefix) : end].strip()
        return entity_text or None


@dataclass(frozen=True, slots=True)
class QuestionCatalogue:
    release_digest: str
    entities: tuple[EntitySpec, ...]
    templates: tuple[QuestionTemplate, ...]

    @property
    def entity_by_id(self) -> dict[str, EntitySpec]:
        return {entity.id: entity for entity in self.entities}

    @property
    def template_by_id(self) -> dict[str, QuestionTemplate]:
        return {template.id: template for template in self.templates}

    @property
    def alias_index(self) -> dict[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {}
        for entity in self.entities:
            for alias in entity.aliases:
                result.setdefault(alias, []).append(entity.id)
        return {
            alias: tuple(sorted(entity_ids))
            for alias, entity_ids in result.items()
        }


@dataclass(frozen=True, slots=True)
class QuestionMapping:
    status: MappingStatus
    template_id: str | None
    entity_ids: tuple[str, ...]
    operator: str | None
    query_ids: tuple[str, ...]
    reason_code: str | None

    def validate(self) -> None:
        if not isinstance(self.status, MappingStatus):
            raise _fail("mapping status is unknown")
        for value in (*self.entity_ids, *self.query_ids):
            if not valid_identifier(value):
                raise _fail("mapping contains an invalid identifier")
        if self.template_id is not None and not valid_identifier(self.template_id):
            raise _fail("mapping template ID is invalid")
        if self.reason_code is not None and not valid_identifier(self.reason_code):
            raise _fail("mapping reason code is invalid")
        if len(set(self.entity_ids)) != len(self.entity_ids):
            raise _fail("mapping repeats an entity")
        if len(set(self.query_ids)) != len(self.query_ids):
            raise _fail("mapping repeats a query")
        if self.entity_ids != tuple(sorted(self.entity_ids)):
            raise _fail("mapping entities are not ID-sorted")
        if self.query_ids != tuple(sorted(self.query_ids)):
            raise _fail("mapping queries are not ID-sorted")
        if self.status is MappingStatus.MAPPED:
            if self.template_id is None or self.operator != "all":
                raise _fail("mapped question lacks an all-query plan")
            if not self.query_ids or self.reason_code is not None:
                raise _fail("mapped question has an invalid result contract")
            if self.template_id != FORMAL_TEMPLATE_ID and len(self.entity_ids) != 1:
                raise _fail("template mapping must bind exactly one entity")
        else:
            if self.operator is not None or self.query_ids:
                raise _fail("refused mapping cannot carry a query plan")
            if self.reason_code is None:
                raise _fail("refused mapping lacks a reason code")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "entity_ids": list(self.entity_ids),
            "operator": self.operator,
            "query_ids": list(self.query_ids),
            "reason_code": self.reason_code,
            "status": self.status.value,
            "template_id": self.template_id,
        }


def load_question_catalogue(path: Path, release: Release) -> QuestionCatalogue:
    """Load a strict release-bound mapping catalogue."""
    sources = tuple(source for source in release.sources if source.path == "questions.json")
    if len(sources) != 1:
        raise _fail("question catalogue is not uniquely pinned by the release")
    try:
        data = Path(path).read_bytes()
        if len(data) != sources[0].byte_length or digest_bytes(data) != sources[0].sha256:
            raise _fail("question catalogue bytes differ from the pinned source")
        raw = load_json_bytes(data)
    except (CanonicalizationError, OSError) as exc:
        raise _fail("question catalogue cannot be loaded") from exc
    root = _object(
        raw,
        {"entities", "release_id", "schema", "templates"},
        "catalogue",
    )
    if root["schema"] != "noema.questions/v1":
        raise _fail("question catalogue schema differs")
    release_id = _string(root["release_id"], "catalogue.release_id")
    if release_id != release.release_id:
        raise _fail("question catalogue targets a different release")
    entities: list[EntitySpec] = []
    seen_entities: set[str] = set()
    for index, value in enumerate(_array(root["entities"], "catalogue.entities")):
        item = _object(value, {"aliases", "id"}, f"entities[{index}]")
        entity_id = _identifier(item["id"], f"entities[{index}].id")
        if entity_id in seen_entities:
            raise _fail("question catalogue repeats an entity")
        aliases = tuple(
            _string(alias, f"entities[{index}].aliases[{alias_index}]")
            for alias_index, alias in enumerate(
                _array(item["aliases"], f"entities[{index}].aliases")
            )
        )
        if not aliases or any(not _is_catalogue_normal_form(alias) for alias in aliases):
            raise _fail("entity aliases must be non-empty normal forms")
        if len(set(aliases)) != len(aliases):
            raise _fail("entity repeats an alias")
        if aliases != tuple(sorted(aliases)):
            raise _fail("entity aliases are not sorted")
        entities.append(EntitySpec(entity_id, aliases))
        seen_entities.add(entity_id)
    if tuple(entity.id for entity in entities) != tuple(sorted(seen_entities)):
        raise _fail("catalogue entities are not ID-sorted")

    query_ids = {query.id for query in release.queries}
    templates: list[QuestionTemplate] = []
    seen_templates: set[str] = set()
    seen_patterns: set[str] = set()
    for index, value in enumerate(_array(root["templates"], "catalogue.templates")):
        item = _object(
            value,
            {"bindings", "id", "operator", "outcome", "pattern", "reason_code"},
            f"templates[{index}]",
        )
        template_id = _identifier(item["id"], f"templates[{index}].id")
        pattern = _string(item["pattern"], f"templates[{index}].pattern")
        outcome = _string(item["outcome"], f"templates[{index}].outcome")
        operator = item["operator"]
        reason_code = item["reason_code"]
        if template_id in seen_templates or pattern in seen_patterns:
            raise _fail("question catalogue repeats a template or pattern")
        if not _is_catalogue_normal_form(pattern) or pattern.count("{entity}") != 1:
            raise _fail("question pattern must be a normal-form entity template")
        if operator is not None and not isinstance(operator, str):
            raise _fail("template operator must be a string or null")
        if reason_code is not None and not valid_identifier(reason_code):
            raise _fail("template reason code is invalid")

        bindings: list[tuple[str, tuple[str, ...]]] = []
        seen_bindings: set[str] = set()
        for binding_index, raw_binding in enumerate(
            _array(item["bindings"], f"templates[{index}].bindings")
        ):
            binding = _object(
                raw_binding,
                {"entity_id", "query_ids"},
                f"templates[{index}].bindings[{binding_index}]",
            )
            entity_id = _identifier(binding["entity_id"], "binding.entity_id")
            bound_queries = tuple(
                _identifier(query_id, "binding.query_id")
                for query_id in _array(binding["query_ids"], "binding.query_ids")
            )
            if entity_id not in seen_entities or entity_id in seen_bindings:
                raise _fail("template has an invalid or repeated entity binding")
            if (
                not bound_queries
                or len(set(bound_queries)) != len(bound_queries)
                or any(query_id not in query_ids for query_id in bound_queries)
            ):
                raise _fail("template binding has an invalid query plan")
            if bound_queries != tuple(sorted(bound_queries)):
                raise _fail("template query plan is not ID-sorted")
            bindings.append((entity_id, bound_queries))
            seen_bindings.add(entity_id)
        if tuple(entity_id for entity_id, _ in bindings) != tuple(
            sorted(seen_bindings)
        ):
            raise _fail("template bindings are not entity-ID-sorted")

        if outcome == "query":
            if operator != "all" or reason_code is not None or not bindings:
                raise _fail("query template contract is invalid")
        elif outcome == "unsupported":
            if operator is not None or reason_code is None or bindings:
                raise _fail("unsupported template contract is invalid")
        else:
            raise _fail("template outcome is unsupported")
        templates.append(
            QuestionTemplate(
                id=template_id,
                pattern=pattern,
                operator=operator,
                outcome=outcome,
                reason_code=reason_code,
                bindings=tuple(sorted(bindings)),
            )
        )
        seen_templates.add(template_id)
        seen_patterns.add(pattern)
    if tuple(template.id for template in templates) != tuple(sorted(seen_templates)):
        raise _fail("catalogue templates are not ID-sorted")

    return QuestionCatalogue(
        release_digest=release.digest,
        entities=tuple(entities),
        templates=tuple(templates),
    )


def map_question(
    question: str,
    catalogue: QuestionCatalogue,
    release: Release,
) -> QuestionMapping:
    """Map one question without retaining its text in the result."""
    if not isinstance(question, str):
        raise _fail("question must be a string")
    try:
        question_bytes = question.encode("ascii")
    except UnicodeEncodeError:
        question_bytes = b""
    if (
        not question_bytes
        or len(question_bytes) > MAX_QUESTION_BYTES
        or any(byte < 0x20 or byte > 0x7E for byte in question_bytes)
    ):
        result = QuestionMapping(
            status=MappingStatus.UNSUPPORTED,
            template_id=None,
            entity_ids=(),
            operator=None,
            query_ids=(),
            reason_code="question:invalid-input",
        )
        result.validate()
        return result
    normalised = _normalise(question)
    declared_queries = {query.id for query in release.queries}
    if normalised.startswith("query:"):
        if normalised in declared_queries:
            result = QuestionMapping(
                status=MappingStatus.MAPPED,
                template_id=FORMAL_TEMPLATE_ID,
                entity_ids=(),
                operator="all",
                query_ids=(normalised,),
                reason_code=None,
            )
        else:
            result = QuestionMapping(
                status=MappingStatus.UNSUPPORTED,
                template_id=FORMAL_TEMPLATE_ID,
                entity_ids=(),
                operator=None,
                query_ids=(),
                reason_code="question:unknown-query",
            )
        result.validate()
        return result

    matches = [
        (template, entity_text)
        for template in catalogue.templates
        if (entity_text := template.match(normalised)) is not None
    ]
    if not matches:
        result = QuestionMapping(
            MappingStatus.UNSUPPORTED,
            None,
            (),
            None,
            (),
            "question:unsupported-template",
        )
        result.validate()
        return result
    if len(matches) > 1:
        result = QuestionMapping(
            MappingStatus.AMBIGUOUS,
            None,
            (),
            None,
            (),
            "question:ambiguous-template",
        )
        result.validate()
        return result

    template, entity_text = matches[0]
    candidates = catalogue.alias_index.get(entity_text, ())
    if template.outcome == "query":
        bindings = template.binding_map
        candidates = tuple(entity for entity in candidates if entity in bindings)
    if not candidates:
        result = QuestionMapping(
            MappingStatus.UNSUPPORTED,
            template.id,
            (),
            None,
            (),
            "question:unknown-entity",
        )
    elif len(candidates) > 1:
        result = QuestionMapping(
            MappingStatus.AMBIGUOUS,
            template.id,
            candidates,
            None,
            (),
            "question:ambiguous-entity",
        )
    elif template.outcome == "unsupported":
        result = QuestionMapping(
            MappingStatus.UNSUPPORTED,
            template.id,
            candidates,
            None,
            (),
            template.reason_code,
        )
    else:
        result = QuestionMapping(
            MappingStatus.MAPPED,
            template.id,
            candidates,
            "all",
            template.binding_map[candidates[0]],
            None,
        )
    result.validate()
    return result


def validate_mapping(
    mapping: QuestionMapping,
    catalogue: QuestionCatalogue,
    release: Release,
) -> None:
    """Check that a certificate mapping names only catalogue plans."""
    mapping.validate()
    if mapping.template_id == FORMAL_TEMPLATE_ID:
        if mapping.status is MappingStatus.MAPPED:
            if (
                mapping.entity_ids
                or mapping.operator != "all"
                or mapping.reason_code is not None
                or len(mapping.query_ids) != 1
                or mapping.query_ids[0] not in {query.id for query in release.queries}
            ):
                raise _fail("formal query mapping is not declared")
        elif (
            mapping.status is not MappingStatus.UNSUPPORTED
            or mapping.entity_ids
            or mapping.operator is not None
            or mapping.query_ids
            or mapping.reason_code != "question:unknown-query"
        ):
            raise _fail("formal query refusal reason differs")
        return
    if mapping.template_id is None:
        allowed = {
            (
                MappingStatus.UNSUPPORTED,
                "question:invalid-input",
            ),
            (
                MappingStatus.UNSUPPORTED,
                "question:unsupported-template",
            ),
            (
                MappingStatus.AMBIGUOUS,
                "question:ambiguous-template",
            ),
        }
        if (
            (mapping.status, mapping.reason_code) not in allowed
            or mapping.entity_ids
            or mapping.operator is not None
            or mapping.query_ids
        ):
            raise _fail("template-less mapping is not a declared refusal")
        if mapping.status is MappingStatus.AMBIGUOUS:
            candidate_questions = {
                template.pattern.replace("{entity}", alias)
                for template in catalogue.templates
                for alias in catalogue.alias_index
            }
            if not any(
                sum(template.match(question) is not None for template in catalogue.templates)
                > 1
                for question in candidate_questions
            ):
                raise _fail("catalogue has no reproducible template ambiguity")
        return
    template = catalogue.template_by_id.get(mapping.template_id)
    if template is None:
        raise _fail("mapping names an unknown template")
    if any(entity not in catalogue.entity_by_id for entity in mapping.entity_ids):
        raise _fail("mapping names an unknown entity")
    if mapping.status is MappingStatus.MAPPED:
        if template.outcome != "query" or len(mapping.entity_ids) != 1:
            raise _fail("mapping does not match a query template")
        expected = template.binding_map.get(mapping.entity_ids[0])
        if expected != mapping.query_ids or mapping.operator != template.operator:
            raise _fail("mapping query plan differs from the catalogue")
    elif mapping.status is MappingStatus.UNSUPPORTED:
        if template.outcome == "unsupported":
            if len(mapping.entity_ids) != 1 or mapping.reason_code != template.reason_code:
                raise _fail("mapping refusal reason differs from the catalogue")
        elif mapping.entity_ids or mapping.reason_code != "question:unknown-entity":
            raise _fail("query template refusal differs")
    elif mapping.status is MappingStatus.AMBIGUOUS:
        if mapping.reason_code != "question:ambiguous-entity":
            raise _fail("ambiguous entity mapping has the wrong reason")
        possible_sets: set[tuple[str, ...]] = set()
        for candidates in catalogue.alias_index.values():
            if template.outcome == "query":
                candidates = tuple(
                    entity for entity in candidates if entity in template.binding_map
                )
            if len(candidates) > 1:
                possible_sets.add(candidates)
        if mapping.entity_ids not in possible_sets:
            raise _fail("ambiguous entity set is not declared by a shared alias")


def mapping_from_dict(raw: JSONValue) -> QuestionMapping:
    """Strictly decode a mapping certificate with no question-text field."""
    root = _object(
        raw,
        {"entity_ids", "operator", "query_ids", "reason_code", "status", "template_id"},
        "mapping",
    )
    try:
        status = MappingStatus(_string(root["status"], "mapping.status"))
    except ValueError as exc:
        raise _fail("mapping status is unknown") from exc
    template_id = root["template_id"]
    operator = root["operator"]
    reason_code = root["reason_code"]
    for location, value in (
        ("mapping.template_id", template_id),
        ("mapping.operator", operator),
        ("mapping.reason_code", reason_code),
    ):
        if value is not None and not isinstance(value, str):
            raise _fail(f"{location} must be a string or null")
    mapping = QuestionMapping(
        status=status,
        template_id=template_id,
        entity_ids=tuple(
            _identifier(value, f"mapping.entity_ids[{index}]")
            for index, value in enumerate(_array(root["entity_ids"], "mapping.entity_ids"))
        ),
        operator=operator,
        query_ids=tuple(
            _identifier(value, f"mapping.query_ids[{index}]")
            for index, value in enumerate(_array(root["query_ids"], "mapping.query_ids"))
        ),
        reason_code=reason_code,
    )
    mapping.validate()
    return mapping
