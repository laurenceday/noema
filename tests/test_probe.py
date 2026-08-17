"""End-to-end tests for Aleph-prime, Lemma-prime, and Null-prime."""

from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import noema.probe as probe_module
from noema.adapters.iana_owl2_rl import IanaOwl2RlAdapter
from noema.answer import answer_question, verify_answer
from noema.canonical import canonical_bytes, digest_bytes
from noema.errors import AnswerVerificationError, ProbeValidationError
from noema.probe import load_evaluation_suite, run_probe
from noema.release import build_release


DOMAIN = ROOT / "domains" / "iana-owl2-rl"
DEMO = (
    "Is application/problem+json a registered media type whose representation "
    "follows JSON syntax?"
)


def _refresh_manifest_source(root: Path, source_id: str) -> None:
    manifest_path = root / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = next(item for item in manifest["sources"] if item["id"] == source_id)
    source["sha256"] = sha256((root / source["path"]).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _signed_adapter(root: Path) -> IanaOwl2RlAdapter:
    release = build_release(root / "release.json")
    return IanaOwl2RlAdapter(root, trusted_release_digest=release.digest)


class AnswerFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adapter = IanaOwl2RlAdapter(DOMAIN)

    def test_demo_certificate_contains_two_independent_proofs(self) -> None:
        answer = answer_question(DOMAIN, DEMO, adapter=self.adapter)
        self.assertEqual(answer.status, "entailed")
        self.assertEqual(
            tuple(result.query_id for result in answer.results),
            ("query:problem-json-syntax", "query:problem-registered"),
        )
        self.assertTrue(all(result.proof is not None for result in answer.results))
        self.assertTrue(all(result.evidence is not None for result in answer.results))
        receipt = verify_answer(DOMAIN, answer, adapter=self.adapter)
        self.assertTrue(receipt.valid)
        self.assertEqual(receipt.result_count, 2)

    def test_repeated_answers_are_byte_identical(self) -> None:
        first = answer_question(DOMAIN, DEMO, adapter=self.adapter)
        second = answer_question(DOMAIN, DEMO, adapter=self.adapter)
        self.assertEqual(canonical_bytes(first.to_dict()), canonical_bytes(second.to_dict()))

    def test_direct_verifier_recomputes_the_answer_identity_digest(self) -> None:
        answer = answer_question(DOMAIN, DEMO, adapter=self.adapter)
        with self.assertRaisesRegex(AnswerVerificationError, "answer digest"):
            verify_answer(
                DOMAIN,
                replace(answer, answer_digest="0" * 64),
                adapter=self.adapter,
            )

    def test_transient_question_form_is_not_retained(self) -> None:
        transient = (
            "  IS   APPLICATION/PROBLEM+JSON A REGISTERED MEDIA TYPE WHOSE "
            "REPRESENTATION FOLLOWS JSON SYNTAX?  "
        )
        answer = answer_question(DOMAIN, transient, adapter=self.adapter)
        encoded = canonical_bytes(answer.to_dict())
        self.assertNotIn(transient.encode(), encoded)
        self.assertNotIn(b"question_text", encoded)
        self.assertNotIn(b"question_hash", encoded)
        self.assertNotIn(b"normalized_question", encoded)

    def test_ambiguity_refuses_before_adapter_decision(self) -> None:
        with patch.object(
            self.adapter,
            "decide",
            side_effect=AssertionError("decision path must not run"),
        ) as decide:
            answer = answer_question(
                DOMAIN,
                "Is JSON media type a registered application media type?",
                adapter=self.adapter,
            )
        decide.assert_not_called()
        self.assertEqual(answer.status, "ambiguous")
        self.assertEqual(answer.results, ())

    def test_out_of_profile_refuses_before_adapter_decision(self) -> None:
        with patch.object(
            self.adapter,
            "decide",
            side_effect=AssertionError("decision path must not run"),
        ) as decide:
            answer = answer_question(
                DOMAIN,
                "Is application/problem+json safe to process?",
                adapter=self.adapter,
            )
        decide.assert_not_called()
        self.assertEqual(answer.status, "unsupported")
        self.assertEqual(answer.results, ())

    def test_explicit_complement_renders_as_contradicted(self) -> None:
        answer = answer_question(
            DOMAIN,
            "Does application/json have the +json structured suffix?",
            adapter=self.adapter,
        )
        self.assertEqual(answer.status, "contradicted")
        self.assertEqual(answer.rendering.code, "no")
        self.assertIsNotNone(answer.results[0].proof)
        self.assertIsNotNone(answer.results[0].evidence)

    def test_open_world_candidate_renders_unknown_and_reverifies(self) -> None:
        answer = answer_question(
            DOMAIN,
            "Is application/unknown+json a registered application media type?",
            adapter=self.adapter,
        )
        self.assertEqual(answer.status, "unknown")
        self.assertEqual(answer.results[0].proof, None)
        self.assertEqual(answer.results[0].evidence, None)
        with patch.object(
            self.adapter,
            "decide",
            wraps=self.adapter.decide,
        ) as decide:
            verify_answer(DOMAIN, answer, adapter=self.adapter)
        decide.assert_called_once_with("query:candidate-registered-application")

    def test_projected_evidence_is_exact_and_source_backed(self) -> None:
        answer = answer_question(DOMAIN, DEMO, adapter=self.adapter)
        syntax_evidence = answer.results[0].evidence
        registration_evidence = answer.results[1].evidence
        assert syntax_evidence is not None
        assert registration_evidence is not None
        self.assertEqual(len(syntax_evidence["items"]), 8)
        self.assertEqual(len(registration_evidence["items"]), 2)
        source_ids = {item["source_id"] for item in syntax_evidence["items"]}
        self.assertIn("source:iana-application-csv", source_ids)
        self.assertIn("source:rfc6839", source_ids)

    def test_hostile_graph_label_is_inert_in_terminal_rendering(self) -> None:
        canary = "CANARY-DO-NOT-RENDER"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "iana-owl2-rl"
            shutil.copytree(DOMAIN, root)
            assertions = root / "theory" / "assertions.ttl"
            text = assertions.read_text(encoding="utf-8").replace(
                '"application/problem+json"',
                f'"\\u001b[31m{canary}\\u001b[0m"',
            )
            assertions.write_text(text, encoding="utf-8")
            _refresh_manifest_source(root, "source:assertions")
            adapter = _signed_adapter(root)
            answer = answer_question(root, DEMO, adapter=adapter)
        self.assertNotIn(canary, answer.rendering.text)
        self.assertNotIn("\x1b", answer.rendering.text)


class NullPrimeProbeTests(unittest.TestCase):
    def test_probe_covers_all_required_outcomes(self) -> None:
        report = run_probe(DOMAIN)
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["coverage"],
            {
                "ambiguous": 1,
                "contradicted": 1,
                "entailed": 1,
                "unknown": 1,
                "unsupported": 2,
            },
        )

    def test_minimal_mutation_is_simulation_only_and_non_promoting(self) -> None:
        release_before = (DOMAIN / "release.json").read_bytes()
        sources_before = {
            source.path: (DOMAIN / source.path).read_bytes()
            for source in build_release(DOMAIN / "release.json").sources
        }
        report = run_probe(DOMAIN)
        mutation = report["mutations"][0]
        self.assertTrue(mutation["simulation_only"])
        self.assertFalse(mutation["hypothetical_adapter_eligible"])
        self.assertEqual(mutation["changed_assertions"], 1)
        self.assertEqual((mutation["before"], mutation["after"]), ("entailed", "unknown"))
        self.assertTrue(mutation["old_certificate_rejected"])
        self.assertTrue(mutation["active_release_unchanged"])
        self.assertEqual((DOMAIN / "release.json").read_bytes(), release_before)
        for path, data in sources_before.items():
            self.assertEqual((DOMAIN / path).read_bytes(), data)

    def test_probe_report_retains_no_questions_or_exception_text(self) -> None:
        encoded = canonical_bytes(run_probe(DOMAIN))
        self.assertNotIn(b"application/problem+json", encoded)
        self.assertNotIn(b"question", encoded)
        self.assertNotIn(b"Traceback", encoded)

    def test_probe_runs_with_socket_and_dns_disabled(self) -> None:
        with (
            patch.object(socket, "socket", side_effect=AssertionError("network")),
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("dns")),
        ):
            report = run_probe(DOMAIN)
        self.assertTrue(report["passed"])

    def test_probe_detects_any_change_to_a_pinned_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "iana-owl2-rl"
            shutil.copytree(DOMAIN, root)
            adapter = _signed_adapter(root)
            original = probe_module._run_mutation

            def mutate_after_probe(*args: object, **kwargs: object) -> dict[str, object]:
                result = original(*args, **kwargs)
                questions = root / "questions.json"
                questions.write_bytes(questions.read_bytes() + b" ")
                return result

            with patch.object(probe_module, "_run_mutation", mutate_after_probe):
                report = run_probe(root, adapter=adapter)
        self.assertFalse(report["passed"])
        self.assertFalse(report["mutations"][0]["active_release_unchanged"])
        self.assertEqual(
            report["mutations"][0]["failure_code"],
            "probe:active-release-mutated",
        )

    def test_evaluation_bytes_must_match_the_release_source(self) -> None:
        release = build_release(DOMAIN / "release.json")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            path.write_bytes((DOMAIN / "evals.json").read_bytes() + b" ")
            with self.assertRaisesRegex(ProbeValidationError, "pinned source"):
                load_evaluation_suite(path, release)

    def test_evaluation_schema_rejects_retention_extensions(self) -> None:
        release = build_release(DOMAIN / "release.json")
        document = json.loads((DOMAIN / "evals.json").read_text())
        document["runtime_questions"] = []
        data = (json.dumps(document, indent=2) + "\n").encode()
        source = next(
            source for source in release.sources if source.path == "evals.json"
        )
        changed = replace(
            release,
            sources=tuple(
                replace(source, sha256=digest_bytes(data), byte_length=len(data))
                if item == source
                else item
                for item in release.sources
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            path.write_bytes(data)
            with self.assertRaisesRegex(ProbeValidationError, "fields differ"):
                load_evaluation_suite(path, changed)


if __name__ == "__main__":
    unittest.main()
