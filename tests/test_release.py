"""Determinism and validation tests for the release kernel."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from noema.canonical import (
    CanonicalizationError,
    canonical_bytes,
    digest_bytes,
    load_json_bytes,
)
from noema.errors import JudgementValidationError, ReleaseValidationError
from noema.model import Judgement, JudgementStatus
from noema.release import build_release, seal_release, validate_release


FIXTURE = Path(__file__).parent / "fixtures" / "kernel"
MANIFEST = FIXTURE / "release-manifest.json"
EXPECTED_DIGEST = "89c1c08b5d75cd32882360fe3d67f62f9d7a397d334eb0fb06b46e85b39e3492"


class ReleaseBuildTests(unittest.TestCase):
    def test_identical_builds_have_stable_digest(self) -> None:
        first = build_release(MANIFEST)
        second = build_release(MANIFEST)
        self.assertEqual(first.digest, EXPECTED_DIGEST)
        self.assertEqual(first, second)

    def test_set_like_manifest_order_does_not_change_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kernel"
            shutil.copytree(FIXTURE, root)
            manifest_path = root / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for key in ("sources", "claims", "rules", "queries", "claim_maps"):
                manifest[key].reverse()
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            self.assertEqual(build_release(manifest_path).digest, EXPECTED_DIGEST)

    def test_changed_pinned_source_changes_release_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kernel"
            shutil.copytree(FIXTURE, root)
            source_path = root / "source.txt"
            manifest_path = root / "release-manifest.json"
            source_path.write_bytes(source_path.read_bytes() + b"new pinned input\n")
            manifest = json.loads(manifest_path.read_text())
            manifest["sources"][0]["sha256"] = digest_bytes(source_path.read_bytes())
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            self.assertNotEqual(build_release(manifest_path).digest, EXPECTED_DIGEST)

    def test_stale_source_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kernel"
            shutil.copytree(FIXTURE, root)
            source_path = root / "source.txt"
            source_path.write_bytes(source_path.read_bytes() + b"drift")
            with self.assertRaisesRegex(ReleaseValidationError, "pinned digest"):
                build_release(root / "release-manifest.json")

    def test_recorded_digest_is_recomputed(self) -> None:
        release = build_release(MANIFEST)
        with self.assertRaisesRegex(ReleaseValidationError, "does not match"):
            validate_release(replace(release, digest="0" * 64))

    def test_resealed_claim_mutation_misses_trusted_digest(self) -> None:
        release = build_release(MANIFEST)
        changed_claim = replace(release.claims[0], expression="changed(expression)")
        changed = seal_release(
            replace(release, claims=(changed_claim, *release.claims[1:])),
            source_root=FIXTURE,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "trusted"):
            validate_release(changed, expected_digest=release.digest)

    def test_changed_claim_map_misses_trusted_digest(self) -> None:
        release = build_release(MANIFEST)
        mapping = release.claim_maps[0]
        changed = seal_release(
            replace(
                release,
                claim_maps=(
                    replace(mapping, support_id="support:changed"),
                    *release.claim_maps[1:],
                ),
            ),
            source_root=FIXTURE,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "trusted"):
            validate_release(changed, expected_digest=release.digest)

    def test_changed_half_open_span_misses_trusted_digest(self) -> None:
        release = build_release(MANIFEST)
        mapping = next(
            value for value in release.claim_maps if value.claim_id == "claim:registered"
        )
        source_bytes = (FIXTURE / "source.txt").read_bytes()
        changed_span = replace(
            mapping.spans[0],
            end=35,
            sha256=digest_bytes(source_bytes[0:35]),
        )
        changed_mapping = replace(mapping, spans=(changed_span,))
        changed = seal_release(
            replace(
                release,
                claim_maps=tuple(
                    changed_mapping if value == mapping else value
                    for value in release.claim_maps
                ),
            ),
            source_root=FIXTURE,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "trusted"):
            validate_release(changed, expected_digest=release.digest)

    def test_duplicate_claim_id_is_rejected(self) -> None:
        release = build_release(MANIFEST)
        duplicate = replace(
            release,
            claims=(*release.claims, release.claims[0]),
            digest="",
        )
        with self.assertRaisesRegex(ReleaseValidationError, "duplicate claim"):
            seal_release(duplicate)

    def test_unknown_retention_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kernel"
            shutil.copytree(FIXTURE, root)
            manifest_path = root / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["question_text"] = "private user question"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            with self.assertRaisesRegex(ReleaseValidationError, "unknown"):
                build_release(manifest_path)

    def test_invalid_span_bounds_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kernel"
            shutil.copytree(FIXTURE, root)
            manifest_path = root / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["claim_maps"][0]["spans"][0]["end"] = 122
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            with self.assertRaisesRegex(ReleaseValidationError, "bounds"):
                build_release(manifest_path)

    def test_source_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "kernel"
            shutil.copytree(FIXTURE, root)
            manifest_path = root / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["sources"][0]["path"] = "../source.txt"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            with self.assertRaisesRegex(ReleaseValidationError, "escapes"):
                build_release(manifest_path)

    def test_dangling_ground_rule_premise_is_rejected(self) -> None:
        release = build_release(MANIFEST)
        changed_rule = replace(
            release.rules[0], premise_claim_ids=("claim:not-in-release",)
        )
        with self.assertRaisesRegex(ReleaseValidationError, "dangling premise"):
            seal_release(
                replace(release, rules=(changed_rule, *release.rules[1:])),
                source_root=FIXTURE,
            )

    def test_dangling_query_claim_is_rejected(self) -> None:
        release = build_release(MANIFEST)
        changed_query = replace(
            release.queries[0], positive_claim_id="claim:not-in-release"
        )
        with self.assertRaisesRegex(ReleaseValidationError, "dangling positive"):
            seal_release(
                replace(release, queries=(changed_query, *release.queries[1:])),
                source_root=FIXTURE,
            )

    def test_query_signature_mutation_misses_trusted_digest(self) -> None:
        release = build_release(MANIFEST)
        changed_query = replace(release.queries[0], id="query:changed")
        changed = seal_release(
            replace(release, queries=(changed_query, *release.queries[1:])),
            source_root=FIXTURE,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "trusted"):
            validate_release(changed, expected_digest=release.digest)

    def test_semantic_assumption_mutation_misses_trusted_digest(self) -> None:
        release = build_release(MANIFEST)
        changed = seal_release(
            replace(
                release,
                backend=replace(release.backend, world_assumption="closed"),
            ),
            source_root=FIXTURE,
        )
        with self.assertRaisesRegex(ReleaseValidationError, "trusted"):
            validate_release(changed, expected_digest=release.digest)


class CanonicalJsonTests(unittest.TestCase):
    def test_object_key_order_is_canonical(self) -> None:
        self.assertEqual(canonical_bytes({"b": 2, "a": 1}), b'{"a":1,"b":2}')

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(CanonicalizationError, "duplicate"):
            load_json_bytes(b'{"a": 1, "a": 2}')

    def test_floating_point_json_is_rejected(self) -> None:
        with self.assertRaisesRegex(CanonicalizationError, "floating-point"):
            canonical_bytes({"value": 1.0})

    def test_unpaired_unicode_surrogate_is_rejected(self) -> None:
        with self.assertRaisesRegex(CanonicalizationError, "Unicode"):
            canonical_bytes({"value": "\ud800"})

    def test_deep_json_fails_with_a_canonicalization_error(self) -> None:
        deeply_nested = b"[" * 2_000 + b"]" * 2_000
        with self.assertRaises(CanonicalizationError):
            load_json_bytes(deeply_nested)

    def test_utf8_bom_is_rejected(self) -> None:
        with self.assertRaisesRegex(CanonicalizationError, "without a BOM"):
            load_json_bytes(b"\xef\xbb\xbf{}")


class JudgementContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.digest = build_release(MANIFEST).digest

    def test_single_proof_judgement_families(self) -> None:
        for status in (JudgementStatus.ENTAILED, JudgementStatus.CONTRADICTED):
            with self.subTest(status=status):
                Judgement(
                    status=status,
                    query_id="query:one",
                    release_digest=self.digest,
                    conclusion_claim_ids=("claim:registered",),
                    proof_root_node_ids=("node:registered",),
                ).validate()

    def test_both_judgement_family(self) -> None:
        Judgement(
            status=JudgementStatus.BOTH,
            query_id="query:both",
            release_digest=self.digest,
            conclusion_claim_ids=("claim:registered", "claim:suffix"),
            proof_root_node_ids=("node:registered", "node:suffix"),
        ).validate()

    def test_every_proofless_judgement_family(self) -> None:
        proofless = (
            JudgementStatus.UNKNOWN,
            JudgementStatus.AMBIGUOUS,
            JudgementStatus.UNSUPPORTED,
            JudgementStatus.INCONSISTENT_RELEASE,
            JudgementStatus.BUDGET_EXCEEDED,
            JudgementStatus.ERROR,
        )
        for status in proofless:
            with self.subTest(status=status):
                Judgement(
                    status=status,
                    query_id="query:terminal",
                    release_digest=self.digest,
                    reason_code="reason:fixture",
                ).validate()

    def test_proofless_status_cannot_smuggle_a_proof(self) -> None:
        with self.assertRaises(JudgementValidationError):
            Judgement(
                status=JudgementStatus.UNKNOWN,
                query_id="query:unknown",
                release_digest=self.digest,
                conclusion_claim_ids=("claim:registered",),
                proof_root_node_ids=("node:registered",),
                reason_code="reason:no-proof",
            ).validate()

    def test_both_requires_distinct_conclusions(self) -> None:
        with self.assertRaisesRegex(JudgementValidationError, "distinct"):
            Judgement(
                status=JudgementStatus.BOTH,
                query_id="query:both",
                release_digest=self.digest,
                conclusion_claim_ids=("claim:registered", "claim:registered"),
                proof_root_node_ids=("node:registered", "node:other"),
            ).validate()

    def test_judgement_has_no_free_form_user_text_field(self) -> None:
        with self.assertRaises(TypeError):
            Judgement(  # type: ignore[call-arg]
                status=JudgementStatus.UNKNOWN,
                query_id="query:unknown",
                release_digest=self.digest,
                reason_code="reason:no-proof",
                question_text="private user question",
            )


class SchemaSyntaxTests(unittest.TestCase):
    def test_all_kernel_schemas_are_strict_json(self) -> None:
        schema_root = PROJECT_ROOT / "schemas"
        for name in ("release.schema.json", "judgement.schema.json", "proof.schema.json"):
            with self.subTest(name=name):
                value = load_json_bytes((schema_root / name).read_bytes())
                self.assertIsInstance(value, dict)
                self.assertFalse(value["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
