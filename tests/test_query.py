"""Tests for finite, release-pinned Aleph-prime question mapping."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from noema.canonical import digest_bytes
from noema.errors import QuestionMappingError
from noema.query import (
    FORMAL_TEMPLATE_ID,
    MappingStatus,
    QuestionMapping,
    load_question_catalogue,
    map_question,
    mapping_from_dict,
    validate_mapping,
)
from noema.release import build_release


DOMAIN = ROOT / "domains" / "iana-owl2-rl"
DEMO = (
    "Is application/problem+json a registered media type whose representation "
    "follows JSON syntax?"
)


class QuestionMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.release = build_release(DOMAIN / "release.json")
        cls.catalogue = load_question_catalogue(
            DOMAIN / "questions.json",
            cls.release,
        )

    def test_demo_maps_to_explicit_two_query_conjunction(self) -> None:
        mapping = map_question(DEMO, self.catalogue, self.release)
        self.assertEqual(mapping.status, MappingStatus.MAPPED)
        self.assertEqual(mapping.template_id, "template:registered-json-syntax")
        self.assertEqual(mapping.entity_ids, ("entity:problem-json",))
        self.assertEqual(mapping.operator, "all")
        self.assertEqual(
            mapping.query_ids,
            ("query:problem-json-syntax", "query:problem-registered"),
        )

    def test_ascii_case_and_space_normalisation_is_deterministic(self) -> None:
        changed = (
            "  IS   APPLICATION/PROBLEM+JSON A REGISTERED MEDIA TYPE WHOSE "
            "REPRESENTATION FOLLOWS JSON SYNTAX?  "
        )
        self.assertEqual(
            map_question(changed, self.catalogue, self.release),
            map_question(DEMO, self.catalogue, self.release),
        )

    def test_shared_alias_is_refused_as_an_exact_ambiguity(self) -> None:
        mapping = map_question(
            "Is JSON media type a registered application media type?",
            self.catalogue,
            self.release,
        )
        self.assertEqual(mapping.status, MappingStatus.AMBIGUOUS)
        self.assertEqual(
            mapping.entity_ids,
            ("entity:candidate-json", "entity:problem-json"),
        )
        validate_mapping(mapping, self.catalogue, self.release)

    def test_unknown_entity_is_a_typed_refusal(self) -> None:
        mapping = map_question(
            "Is application/xml a registered application media type?",
            self.catalogue,
            self.release,
        )
        self.assertEqual(mapping.status, MappingStatus.UNSUPPORTED)
        self.assertEqual(mapping.reason_code, "question:unknown-entity")
        self.assertEqual(mapping.query_ids, ())

    def test_out_of_profile_template_has_no_formal_plan(self) -> None:
        mapping = map_question(
            "Is application/problem+json safe to process?",
            self.catalogue,
            self.release,
        )
        self.assertEqual(mapping.status, MappingStatus.UNSUPPORTED)
        self.assertEqual(mapping.reason_code, "question:out-of-profile")
        self.assertEqual(mapping.query_ids, ())
        validate_mapping(mapping, self.catalogue, self.release)

    def test_declared_formal_query_path_is_exact(self) -> None:
        mapping = map_question(
            "query:problem-registered",
            self.catalogue,
            self.release,
        )
        self.assertEqual(mapping.template_id, FORMAL_TEMPLATE_ID)
        self.assertEqual(mapping.query_ids, ("query:problem-registered",))
        validate_mapping(mapping, self.catalogue, self.release)

    def test_unknown_formal_query_has_empty_refusal_fields(self) -> None:
        mapping = map_question("query:not-declared", self.catalogue, self.release)
        self.assertEqual(mapping.status, MappingStatus.UNSUPPORTED)
        self.assertEqual(mapping.template_id, FORMAL_TEMPLATE_ID)
        self.assertEqual(mapping.entity_ids, ())
        self.assertIsNone(mapping.operator)
        self.assertEqual(mapping.query_ids, ())
        self.assertEqual(mapping.reason_code, "question:unknown-query")
        validate_mapping(mapping, self.catalogue, self.release)

    def test_bounded_control_free_ascii_input_is_enforced(self) -> None:
        for question in ("", "line one\nline two", "caf\N{LATIN SMALL LETTER E WITH ACUTE}", "x" * 513):
            with self.subTest(question_length=len(question)):
                mapping = map_question(question, self.catalogue, self.release)
                self.assertEqual(mapping.status, MappingStatus.UNSUPPORTED)
                self.assertEqual(mapping.reason_code, "question:invalid-input")
                self.assertEqual(mapping.entity_ids, ())
                self.assertEqual(mapping.query_ids, ())

    def test_mapping_never_retains_question_text_or_hash(self) -> None:
        encoded = json.dumps(
            map_question(DEMO, self.catalogue, self.release).to_dict(),
            sort_keys=True,
        ).lower()
        self.assertNotIn("application/problem+json", encoded)
        self.assertNotIn("question_text", encoded)
        self.assertNotIn("normalized", encoded)
        self.assertNotIn("question_hash", encoded)

    def test_catalogue_bytes_must_match_the_release_source(self) -> None:
        raw = (DOMAIN / "questions.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "questions.json"
            path.write_text(raw + " ", encoding="utf-8")
            with self.assertRaisesRegex(QuestionMappingError, "pinned source"):
                load_question_catalogue(path, self.release)

    def test_catalogue_rejects_unknown_fields_after_valid_pinning(self) -> None:
        document = json.loads((DOMAIN / "questions.json").read_text())
        document["question_log"] = []
        data = (json.dumps(document, indent=2) + "\n").encode()
        source = next(
            source for source in self.release.sources if source.path == "questions.json"
        )
        changed_release = replace(
            self.release,
            sources=tuple(
                replace(source, sha256=digest_bytes(data), byte_length=len(data))
                if item == source
                else item
                for item in self.release.sources
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "questions.json"
            path.write_bytes(data)
            with self.assertRaisesRegex(QuestionMappingError, "fields differ"):
                load_question_catalogue(path, changed_release)

    def test_mapping_decoder_rejects_retention_extensions(self) -> None:
        raw = map_question(DEMO, self.catalogue, self.release).to_dict()
        raw["question_text"] = DEMO
        with self.assertRaisesRegex(QuestionMappingError, "fields differ"):
            mapping_from_dict(raw)

    def test_forged_template_less_refusal_is_rejected(self) -> None:
        forged = QuestionMapping(
            MappingStatus.UNSUPPORTED,
            None,
            (),
            None,
            (),
            "question:out-of-profile",
        )
        with self.assertRaisesRegex(QuestionMappingError, "declared refusal"):
            validate_mapping(forged, self.catalogue, self.release)

    def test_forged_ambiguity_must_equal_a_shared_alias_set(self) -> None:
        forged = QuestionMapping(
            MappingStatus.AMBIGUOUS,
            "template:registered-application",
            ("entity:application-json", "entity:problem-json"),
            None,
            (),
            "question:ambiguous-entity",
        )
        with self.assertRaisesRegex(QuestionMappingError, "shared alias"):
            validate_mapping(forged, self.catalogue, self.release)

    def test_formal_query_refusal_cannot_carry_an_entity(self) -> None:
        forged = QuestionMapping(
            MappingStatus.UNSUPPORTED,
            FORMAL_TEMPLATE_ID,
            ("entity:problem-json",),
            None,
            (),
            "question:unknown-query",
        )
        with self.assertRaisesRegex(QuestionMappingError, "formal query refusal"):
            validate_mapping(forged, self.catalogue, self.release)


if __name__ == "__main__":
    unittest.main()
