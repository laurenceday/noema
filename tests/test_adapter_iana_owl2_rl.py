"""Deterministic subject and contract tests for the IANA OWL 2 RL adapter."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import Graph, URIRef
from rdflib.namespace import RDF


PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import noema.adapters.iana_owl2_rl as adapter_module
from noema.adapters.iana_owl2_rl import (
    DEFAULT_TRUSTED_RELEASE_DIGEST,
    IanaOwl2RlAdapter,
)
from noema.evidence import project_evidence
from noema.errors import EvidenceProjectionError, ProofVerificationError
from noema.model import JudgementStatus
from noema.proof import verify_proof
from noema.release import build_release, seal_release


DOMAIN = PROJECT_ROOT / "domains" / "iana-owl2-rl"
FIXTURES = Path(__file__).parent / "fixtures" / "iana-owl2-rl"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _refresh_source(manifest: dict[str, object], root: Path, source_id: str) -> None:
    sources = manifest["sources"]
    assert isinstance(sources, list)
    source = next(item for item in sources if item["id"] == source_id)
    source["sha256"] = sha256((root / source["path"]).read_bytes()).hexdigest()


def _signed_adapter(root: Path) -> IanaOwl2RlAdapter:
    release = build_release(root / "release.json")
    return IanaOwl2RlAdapter(root, trusted_release_digest=release.digest)


def _append_fixture(root: Path, target: str, fixture: str, source_id: str) -> None:
    target_path = root / "theory" / target
    target_path.write_bytes(
        target_path.read_bytes() + b"\n" + (FIXTURES / fixture).read_bytes()
    )
    manifest = _read_json(root / "release.json")
    _refresh_source(manifest, root, source_id)
    _write_json(root / "release.json", manifest)


def _set_claim_asserted(root: Path, claim_id: str, asserted: bool) -> None:
    claims_path = root / "theory" / "claims.json"
    claims_doc = _read_json(claims_path)
    for claim in claims_doc["claims"]:
        if claim["id"] == claim_id:
            claim["asserted"] = asserted
            break
    else:
        raise AssertionError(f"claim not found: {claim_id}")
    _write_json(claims_path, claims_doc)

    manifest = _read_json(root / "release.json")
    for claim in manifest["claims"]:
        if claim["id"] == claim_id:
            claim["asserted"] = asserted
            break
    _refresh_source(manifest, root, "source:theory-claims")
    _write_json(root / "release.json", manifest)


def _set_claim_expression(root: Path, claim_id: str, expression: str) -> None:
    claims_path = root / "theory" / "claims.json"
    claims_doc = _read_json(claims_path)
    for claim in claims_doc["claims"]:
        if claim["id"] == claim_id:
            claim["expression"] = expression
            break
    else:
        raise AssertionError(f"claim not found: {claim_id}")
    _write_json(claims_path, claims_doc)

    manifest = _read_json(root / "release.json")
    for claim in manifest["claims"]:
        if claim["id"] == claim_id:
            claim["expression"] = expression
            break
    _refresh_source(manifest, root, "source:theory-claims")
    _write_json(root / "release.json", manifest)


def _add_claim(root: Path, claim: dict[str, object]) -> None:
    claims_path = root / "theory" / "claims.json"
    claims_doc = _read_json(claims_path)
    claims_doc["claims"].append(claim)
    claims_doc["claims"].sort(key=lambda item: item["id"])
    _write_json(claims_path, claims_doc)

    manifest = _read_json(root / "release.json")
    manifest["claims"].append(claim)
    manifest["claims"].sort(key=lambda item: item["id"])
    _refresh_source(manifest, root, "source:theory-claims")
    _write_json(root / "release.json", manifest)


def _set_query_complement(root: Path, query_id: str, complement_id: str) -> None:
    queries_path = root / "theory" / "queries.json"
    queries_doc = _read_json(queries_path)
    for query in queries_doc["queries"]:
        if query["id"] == query_id:
            query["complement_claim_id"] = complement_id
            break
    else:
        raise AssertionError(f"query not found: {query_id}")
    _write_json(queries_path, queries_doc)

    manifest = _read_json(root / "release.json")
    for query in manifest["queries"]:
        if query["id"] == query_id:
            query["complement_claim_id"] = complement_id
            break
    _refresh_source(manifest, root, "source:theory-queries")
    _write_json(root / "release.json", manifest)


class IanaOwlRlAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.release = build_release(DOMAIN / "release.json")
        self.adapter = IanaOwl2RlAdapter(DOMAIN)

    def test_release_validates_against_trusted_digest(self) -> None:
        report = self.adapter.validate()
        self.assertTrue(report.valid)
        self.assertEqual(report.release_digest, DEFAULT_TRUSTED_RELEASE_DIGEST)
        self.assertEqual(report.errors, ())
        self.assertTrue(report.shacl_conforms)
        self.assertTrue(report.reference_materialization_checked)

    def test_capabilities_name_only_the_bounded_fragment(self) -> None:
        capabilities = self.adapter.capabilities()
        self.assertEqual(capabilities["semantic_profile"], "owl2-rl-noema/v1")
        self.assertEqual(
            capabilities["rule_families"],
            ["owlrl:cax-sco", "owlrl:prp-spo2-length-2"],
        )
        self.assertEqual(capabilities["world_assumption"], "open")
        self.assertEqual(capabilities["inconsistency_policy"], "reject-release/v1")
        self.assertNotIn("full-owl-2-rl", json.dumps(capabilities))

    def test_shacl_runs_separately_without_inference(self) -> None:
        with patch.object(
            adapter_module,
            "shacl_validate",
            wraps=adapter_module.shacl_validate,
        ) as called:
            self.assertTrue(self.adapter.validate().valid)
        self.assertEqual(called.call_args.kwargs["inference"], "none")
        self.assertFalse(called.call_args.kwargs["do_owl_imports"])

    def test_reference_owlrl_materializes_the_two_hop_type(self) -> None:
        graph = Graph()
        graph.parse(DOMAIN / "theory" / "vocabulary.ttl", format="turtle")
        graph.parse(DOMAIN / "theory" / "assertions.ttl", format="turtle")
        DeductiveClosure(
            OWLRL_Semantics,
            axiomatic_triples=False,
            datatype_axioms=False,
        ).expand(graph)
        problem = URIRef(
            "https://noema.invalid/iana/media/application_problem_json"
        )
        media_type = URIRef("https://noema.invalid/iana/MediaType")
        self.assertIn((problem, RDF.type, media_type), graph)

    def test_raw_official_sources_match_pinned_digests(self) -> None:
        expected = {
            "iana-application-2026-08-14.csv": (
                "e8ac01c61f0741fe0b7dcfc96c1276390c41410f66588adf8bb1a450398031b0"
            ),
            "iana-structured-syntax-suffix-2026-06-25.csv": (
                "8f67c993b42ca7027dbcf108d831a8b38d38485c941efd72c8099585420547bf"
            ),
            "rfc6838.txt": "b08ccba7e5116e61085f2e1fe447d90eee785fb0efaa448a4b4ef6ea48b03b80",
            "rfc6839.txt": "f754a5e85371359a1b6609427ab9a759dc012af7f656a8741fdac4942abf8c13",
            "rfc8259.txt": "61a5378f4255c720beb2a4b4a63b29540147c140f36988bf086291989b4cd2d7",
        }
        for name, digest in expected.items():
            with self.subTest(name=name):
                data = (DOMAIN / "sources" / name).read_bytes()
                self.assertEqual(sha256(data).hexdigest(), digest)
        self.assertIn(
            b"json,application/json,[RFC8259]\r\n",
            (DOMAIN / "sources" / "iana-application-2026-08-14.csv").read_bytes(),
        )

    def test_generated_slices_replay_from_vendored_csv(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(DOMAIN / "sources" / "extract_iana_slices.py"),
                "--check",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_validation_does_not_open_a_network_socket(self) -> None:
        with patch.object(
            socket,
            "socket",
            side_effect=AssertionError("network access attempted"),
        ):
            self.assertTrue(self.adapter.validate().valid)

    def test_direct_assertion_has_a_one_node_proof(self) -> None:
        decision = self.adapter.decide("query:problem-registered-application")
        self.assertEqual(decision.judgement.status, JudgementStatus.ENTAILED)
        self.assertIsNotNone(decision.proof)
        self.assertEqual(len(decision.proof.nodes), 1)
        self.assertEqual(
            decision.proof.nodes[0].claim_id,
            "claim:problem-registered-application",
        )
        self.adapter.verify(decision.judgement, decision.proof)

    def test_registered_type_has_a_replayable_one_hop_proof(self) -> None:
        decision = self.adapter.decide("query:problem-registered")
        self.assertEqual(decision.judgement.status, JudgementStatus.ENTAILED)
        self.assertEqual(len(decision.proof.nodes), 3)
        result = self.adapter.verify(decision.judgement, decision.proof)
        self.assertEqual(
            result.applied_rule_ids,
            ("owlrl:cax-sco:problem-registered",),
        )

    def test_media_type_uses_the_deterministic_two_hop_proof(self) -> None:
        decision = self.adapter.decide("query:problem-media-type")
        self.assertEqual(decision.judgement.status, JudgementStatus.ENTAILED)
        self.assertEqual(len(decision.proof.nodes), 5)
        result = self.adapter.verify(decision.judgement, decision.proof)
        self.assertEqual(
            result.applied_rule_ids,
            (
                "owlrl:cax-sco:problem-application",
                "owlrl:cax-sco:problem-media-via-application",
            ),
        )

    def test_alternative_proof_selection_is_stable(self) -> None:
        first = self.adapter.decide("query:problem-media-type")
        second = self.adapter.decide("query:problem-media-type")
        self.assertEqual(first, second)
        rule_ids = {node.rule_id for node in first.proof.nodes if node.rule_id}
        self.assertNotIn("owlrl:cax-sco:problem-media-via-registration", rule_ids)

    def test_property_chain_proof_replays(self) -> None:
        decision = self.adapter.decide("query:problem-json-syntax")
        self.assertEqual(decision.judgement.status, JudgementStatus.ENTAILED)
        result = self.adapter.verify(decision.judgement, decision.proof)
        self.assertEqual(
            result.applied_rule_ids,
            ("owlrl:prp-spo2:problem-json-syntax",),
        )

    def test_class_complement_returns_explicit_contradiction(self) -> None:
        decision = self.adapter.decide("query:problem-unregistered")
        self.assertEqual(decision.judgement.status, JudgementStatus.CONTRADICTED)
        self.assertEqual(
            decision.judgement.conclusion_claim_ids,
            ("claim:problem-registered",),
        )
        self.adapter.verify(decision.judgement, decision.proof)

    def test_negative_property_assertion_returns_contradiction(self) -> None:
        decision = self.adapter.decide("query:application-json-has-json-suffix")
        self.assertEqual(decision.judgement.status, JudgementStatus.CONTRADICTED)
        self.assertEqual(
            decision.judgement.conclusion_claim_ids,
            ("claim:application-json-lacks-json-suffix",),
        )
        self.assertEqual(len(decision.proof.nodes), 1)
        self.adapter.verify(decision.judgement, decision.proof)

    def test_in_signature_registry_candidate_is_genuinely_unknown(self) -> None:
        decision = self.adapter.decide("query:candidate-registered-application")
        self.assertEqual(decision.judgement.status, JudgementStatus.UNKNOWN)
        self.assertEqual(decision.judgement.reason_code, "open-world:neither-derivable")
        self.assertIsNone(decision.proof)

    def test_payload_safety_is_out_of_signature(self) -> None:
        decision = self.adapter.decide("query:problem-safe-payload")
        self.assertEqual(decision.judgement.status, JudgementStatus.UNSUPPORTED)
        self.assertEqual(decision.judgement.reason_code, "query:not-declared")
        self.assertIsNone(decision.proof)

    def test_application_json_syntax_is_a_direct_assertion(self) -> None:
        decision = self.adapter.decide("query:application-json-uses-json-syntax")
        self.assertEqual(decision.judgement.status, JudgementStatus.ENTAILED)
        self.assertEqual(len(decision.proof.nodes), 1)

    def test_application_json_syntax_projects_joint_registry_and_rfc_evidence(
        self,
    ) -> None:
        decision = self.adapter.decide("query:application-json-uses-json-syntax")
        packet = project_evidence(
            self.release,
            decision.judgement,
            decision.proof,
            source_root=DOMAIN,
            trusted_release_digest=DEFAULT_TRUSTED_RELEASE_DIGEST,
            replayer=self.adapter.replayer,
        )
        self.assertEqual(
            {item.source_id for item in packet.items},
            {"source:iana-application-csv", "source:rfc8259"},
        )
        rfc_item = next(
            item for item in packet.items if item.source_id == "source:rfc8259"
        )
        self.assertEqual(
            rfc_item.quote_text,
            "   The media type for JSON text is application/json.",
        )

    def test_justify_returns_the_same_proof_as_decide(self) -> None:
        decision = self.adapter.decide("query:problem-json-syntax")
        self.assertEqual(
            self.adapter.justify("query:problem-json-syntax"),
            decision.proof,
        )

    def test_evidence_projection_reaches_raw_registry_and_rfc_bytes(self) -> None:
        decision = self.adapter.decide("query:problem-json-syntax")
        packet = project_evidence(
            self.release,
            decision.judgement,
            decision.proof,
            source_root=DOMAIN,
            trusted_release_digest=DEFAULT_TRUSTED_RELEASE_DIGEST,
            replayer=self.adapter.replayer,
        )
        source_ids = {item.source_id for item in packet.items}
        self.assertIn("source:iana-application-csv", source_ids)
        self.assertIn("source:iana-suffix-csv", source_ids)
        self.assertIn("source:rfc6839", source_ids)
        self.assertIn("source:vocabulary", source_ids)
        self.assertNotIn("source:rfc-locators", source_ids)

    def test_stale_trust_anchor_is_an_error_not_inconsistency(self) -> None:
        adapter = IanaOwl2RlAdapter(DOMAIN, trusted_release_digest="0" * 64)
        report = adapter.validate()
        self.assertIn("trusted-release-digest", report.errors)
        decision = adapter.decide("query:problem-registered")
        self.assertEqual(decision.judgement.status, JudgementStatus.ERROR)
        self.assertEqual(decision.judgement.reason_code, "release:invalid")

    def test_changed_premise_order_fails_independent_replay(self) -> None:
        decision = self.adapter.decide("query:problem-media-type")
        root_id = decision.proof.root_node_ids[0]
        root = next(node for node in decision.proof.nodes if node.id == root_id)
        changed_root = replace(
            root,
            premise_node_ids=tuple(reversed(root.premise_node_ids)),
        )
        changed_id = adapter_module._node_id(
            "rule",
            {
                "claim_id": changed_root.claim_id,
                "premise_node_ids": list(changed_root.premise_node_ids),
                "rule_id": changed_root.rule_id,
            },
        )
        changed_root = replace(changed_root, id=changed_id)
        changed = replace(
            decision.proof,
            root_node_ids=(changed_id,),
            nodes=tuple(
                changed_root if node.id == root_id else node
                for node in decision.proof.nodes
            ),
        )
        changed_judgement = replace(
            decision.judgement,
            proof_root_node_ids=(changed_id,),
        )
        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            self.adapter.verify(changed_judgement, changed)

    def test_changed_rule_id_fails_independent_replay(self) -> None:
        decision = self.adapter.decide("query:problem-media-type")
        root_id = decision.proof.root_node_ids[0]
        root = next(node for node in decision.proof.nodes if node.id == root_id)
        changed_root = replace(
            root,
            rule_id="owlrl:cax-sco:problem-media-via-registration",
        )
        changed_id = adapter_module._node_id(
            "rule",
            {
                "claim_id": changed_root.claim_id,
                "premise_node_ids": list(changed_root.premise_node_ids),
                "rule_id": changed_root.rule_id,
            },
        )
        changed_root = replace(changed_root, id=changed_id)
        changed = replace(
            decision.proof,
            root_node_ids=(changed_id,),
            nodes=tuple(
                changed_root if node.id == root_id else node
                for node in decision.proof.nodes
            ),
        )
        changed_judgement = replace(
            decision.judgement,
            proof_root_node_ids=(changed_id,),
        )
        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            self.adapter.verify(changed_judgement, changed)

    def test_renamed_node_fails_payload_bound_id_validation(self) -> None:
        decision = self.adapter.decide("query:problem-registered-application")
        renamed_id = "node:assertion:" + "0" * 32
        changed = replace(
            decision.proof,
            root_node_ids=(renamed_id,),
            nodes=(replace(decision.proof.nodes[0], id=renamed_id),),
        )
        changed_judgement = replace(
            decision.judgement,
            proof_root_node_ids=(renamed_id,),
        )
        with self.assertRaisesRegex(
            ProofVerificationError,
            "does not match its payload",
        ):
            self.adapter.verify(changed_judgement, changed)

    def test_raising_node_id_hook_lookup_is_contained_without_canary(self) -> None:
        class RaisingLookupReplayer:
            def supports(self, backend: object) -> bool:
                return True

            def replay(
                self,
                rule: object,
                premises: tuple[object, ...],
                conclusion: object,
            ) -> bool:
                return True

            @property
            def validate_node_id(self) -> object:
                raise RuntimeError("NODE-ID-CANARY")

        decision = self.adapter.decide("query:problem-registered-application")
        with self.assertRaises(ProofVerificationError) as caught:
            verify_proof(
                self.release,
                decision.judgement,
                decision.proof,
                trusted_release_digest=DEFAULT_TRUSTED_RELEASE_DIGEST,
                replayer=RaisingLookupReplayer(),
            )
        self.assertEqual(
            str(caught.exception),
            "proof node ID validator lookup failed",
        )
        self.assertNotIn("CANARY", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_alternative_valid_derivation_cannot_reuse_original_root_id(self) -> None:
        decision = self.adapter.decide("query:problem-media-type")
        claims = {claim.id: claim for claim in self.release.claims}
        rules = {rule.id: rule for rule in self.release.rules}
        leaf = adapter_module._assertion_candidate(
            claims["claim:problem-registered-application"]
        )
        registered_subclass = adapter_module._assertion_candidate(
            claims["claim:registered-application-subclass-registered"]
        )
        registered = adapter_module._rule_candidate(
            rules["owlrl:cax-sco:problem-registered"],
            (leaf, registered_subclass),
        )
        media_subclass = adapter_module._assertion_candidate(
            claims["claim:registered-subclass-media"]
        )
        alternative = adapter_module._rule_candidate(
            rules["owlrl:cax-sco:problem-media-via-registration"],
            (registered, media_subclass),
        )
        valid_alternative = replace(
            decision.proof,
            root_node_ids=(alternative.root_node_id,),
            nodes=alternative.nodes,
        )
        valid_alternative_judgement = replace(
            decision.judgement,
            proof_root_node_ids=(alternative.root_node_id,),
        )
        self.adapter.verify(valid_alternative_judgement, valid_alternative)
        original_root = decision.proof.root_node_ids[0]
        relabelled_nodes = tuple(
            replace(node, id=original_root)
            if node.id == alternative.root_node_id
            else node
            for node in alternative.nodes
        )
        relabelled = replace(
            decision.proof,
            nodes=relabelled_nodes,
        )
        with self.assertRaisesRegex(
            ProofVerificationError,
            "does not match its payload",
        ):
            project_evidence(
                self.release,
                decision.judgement,
                relabelled,
                source_root=DOMAIN,
                trusted_release_digest=DEFAULT_TRUSTED_RELEASE_DIGEST,
                replayer=self.adapter.replayer,
            )

    def test_unmapped_verified_leaf_fails_evidence_projection(self) -> None:
        decision = self.adapter.decide("query:problem-media-type")
        changed_release = seal_release(
            replace(
                self.release,
                claim_maps=tuple(
                    mapping
                    for mapping in self.release.claim_maps
                    if mapping.claim_id != "claim:application-subclass-media"
                ),
            ),
            source_root=DOMAIN,
        )
        changed_proof = replace(
            decision.proof,
            release_digest=changed_release.digest,
        )
        changed_judgement = replace(
            decision.judgement,
            release_digest=changed_release.digest,
        )
        with self.assertRaisesRegex(EvidenceProjectionError, "no admissible"):
            project_evidence(
                changed_release,
                changed_judgement,
                changed_proof,
                source_root=DOMAIN,
                trusted_release_digest=changed_release.digest,
                replayer=self.adapter.replayer,
            )


class IanaOwlRlMutationTests(unittest.TestCase):
    def _copy(self, temporary: str) -> Path:
        root = Path(temporary) / "iana-owl2-rl"
        shutil.copytree(DOMAIN, root)
        return root

    def test_signed_wrong_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            manifest = _read_json(root / "release.json")
            manifest["backend"]["semantic_profile"] = "owl2-rl-unbounded/v1"
            _write_json(root / "release.json", manifest)
            report = _signed_adapter(root).validate()
            self.assertIn("semantic-assumptions", report.errors)

    def test_signed_closed_world_assumption_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            manifest = _read_json(root / "release.json")
            manifest["backend"]["world_assumption"] = "closed"
            _write_json(root / "release.json", manifest)
            report = _signed_adapter(root).validate()
            self.assertIn("semantic-assumptions", report.errors)

    def test_unsupported_owl_syntax_is_rejected_after_resigning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "vocabulary.ttl",
                "unsupported-axiom.ttl",
                "source:vocabulary",
            )
            report = _signed_adapter(root).validate()
            self.assertIn("owl-fragment", report.errors)

    def test_undeclared_semantic_triple_is_rejected_after_resigning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "assertions.ttl",
                "rogue-semantic-triple.ttl",
                "source:assertions",
            )
            report = _signed_adapter(root).validate()
            self.assertEqual(report.errors, ("owl-fragment",))

    def test_rogue_complement_axiom_is_rejected_after_resigning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "vocabulary.ttl",
                "rogue-complement-axiom.ttl",
                "source:vocabulary",
            )
            report = _signed_adapter(root).validate()
            self.assertEqual(report.errors, ("owl-fragment",))

    def test_claimed_symmetric_property_profile_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "vocabulary.ttl",
                "symmetric-property-claim.ttl",
                "source:vocabulary",
            )
            _add_claim(
                root,
                {
                    "asserted": True,
                    "expression": (
                        '["triple","https://noema.invalid/iana/hasSuffix",'
                        '"http://www.w3.org/1999/02/22-rdf-syntax-ns#type",'
                        '"http://www.w3.org/2002/07/owl#SymmetricProperty"]'
                    ),
                    "id": "claim:rogue-symmetric-has-suffix",
                },
            )
            report = _signed_adapter(root).validate()
            self.assertEqual(report.errors, ("owl-fragment",))

    def test_malformed_claim_expressions_return_stable_validation_errors(self) -> None:
        for expression in ("[]", "not-json"):
            with self.subTest(expression=expression):
                with tempfile.TemporaryDirectory() as temporary:
                    root = self._copy(temporary)
                    _set_claim_expression(
                        root,
                        "claim:candidate-registered-application",
                        expression,
                    )
                    report = _signed_adapter(root).validate()
                    self.assertEqual(report.errors, ("owl-fragment",))

    def test_shacl_violation_is_not_used_as_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            assertions = root / "theory" / "assertions.ttl"
            text = assertions.read_text(encoding="utf-8")
            text = text.replace(
                '    iana:mediaTypeName "application/problem+json" ;\n',
                "",
            )
            assertions.write_text(text, encoding="utf-8")
            manifest = _read_json(root / "release.json")
            _refresh_source(manifest, root, "source:assertions")
            _write_json(root / "release.json", manifest)
            report = _signed_adapter(root).validate()
            self.assertIn("shacl-violation", report.errors)
            self.assertNotIn("reference-materialization", report.errors)

    def test_malformed_turtle_is_rejected_after_resigning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            assertions = root / "theory" / "assertions.ttl"
            assertions.write_bytes(assertions.read_bytes() + b"\nnot valid turtle {\n")
            manifest = _read_json(root / "release.json")
            _refresh_source(manifest, root, "source:assertions")
            _write_json(root / "release.json", manifest)
            report = _signed_adapter(root).validate()
            self.assertIn("rdf-syntax", report.errors)

    def test_mismatched_class_query_complement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _set_query_complement(
                root,
                "query:candidate-registered-application",
                "claim:problem-not-media-type",
            )
            report = _signed_adapter(root).validate()
            self.assertIn("owl-fragment", report.errors)

    def test_mismatched_negative_property_query_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _set_query_complement(
                root,
                "query:application-json-has-json-suffix",
                "claim:application-json-not-json-syntax",
            )
            report = _signed_adapter(root).validate()
            self.assertIn("owl-fragment", report.errors)

    def test_class_complement_conflict_is_release_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "assertions.ttl",
                "inconsistent-class-assertion.ttl",
                "source:assertions",
            )
            _set_claim_asserted(
                root,
                "claim:problem-not-registered-application",
                True,
            )
            adapter = _signed_adapter(root)
            report = adapter.validate()
            self.assertIn("inconsistent-release", report.errors)
            decision = adapter.decide("query:problem-registered-application")
            self.assertEqual(
                decision.judgement.status,
                JudgementStatus.INCONSISTENT_RELEASE,
            )

    def test_stale_trust_dominates_a_contradictory_local_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "assertions.ttl",
                "inconsistent-class-assertion.ttl",
                "source:assertions",
            )
            _set_claim_asserted(
                root,
                "claim:problem-not-registered-application",
                True,
            )
            adapter = IanaOwl2RlAdapter(root, trusted_release_digest="0" * 64)
            report = adapter.validate()
            self.assertEqual(report.errors, ("trusted-release-digest",))
            decision = adapter.decide("query:problem-registered-application")
            self.assertEqual(decision.judgement.status, JudgementStatus.ERROR)
            self.assertEqual(decision.judgement.reason_code, "release:invalid")

    def test_positive_and_negative_property_conflict_is_release_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "assertions.ttl",
                "inconsistent-property-assertion.ttl",
                "source:assertions",
            )
            _set_claim_asserted(
                root,
                "claim:application-json-has-json-suffix",
                True,
            )
            report = _signed_adapter(root).validate()
            self.assertIn("inconsistent-release", report.errors)

    def test_ungrounded_derived_class_conflict_is_release_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "assertions.ttl",
                "ungrounded-class-conflict.ttl",
                "source:assertions",
            )
            for claim in (
                {
                    "asserted": True,
                    "expression": (
                        '["triple","https://noema.invalid/iana/media/'
                        'application_rogue",'
                        '"http://www.w3.org/1999/02/22-rdf-syntax-ns#type",'
                        '"https://noema.invalid/iana/RegisteredApplicationMediaType"]'
                    ),
                    "id": "claim:rogue-registered-application",
                },
                {
                    "asserted": True,
                    "expression": (
                        '["triple","https://noema.invalid/iana/media/'
                        'application_rogue",'
                        '"http://www.w3.org/1999/02/22-rdf-syntax-ns#type",'
                        '"https://noema.invalid/iana/NotMediaType"]'
                    ),
                    "id": "claim:rogue-not-media-type",
                },
            ):
                _add_claim(root, claim)
            adapter = _signed_adapter(root)
            report = adapter.validate()
            self.assertIn("inconsistent-release", report.errors)
            decision = adapter.decide("query:problem-registered-application")
            self.assertEqual(
                decision.judgement.status,
                JudgementStatus.INCONSISTENT_RELEASE,
            )

    def test_ungrounded_property_chain_conflict_is_release_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            _append_fixture(
                root,
                "assertions.ttl",
                "ungrounded-property-conflict.ttl",
                "source:assertions",
            )
            for claim in (
                {
                    "asserted": True,
                    "expression": (
                        '["triple","https://noema.invalid/iana/media/'
                        'application_rogue",'
                        '"https://noema.invalid/iana/hasSuffix",'
                        '"https://noema.invalid/iana/suffix/json"]'
                    ),
                    "id": "claim:rogue-has-json-suffix",
                },
                {
                    "asserted": True,
                    "expression": (
                        '["negative-property",'
                        '"https://noema.invalid/iana/media/application_rogue",'
                        '"https://noema.invalid/iana/usesRepresentationSyntax",'
                        '"https://noema.invalid/iana/syntax/json"]'
                    ),
                    "id": "claim:rogue-not-json-syntax",
                },
            ):
                _add_claim(root, claim)
            report = _signed_adapter(root).validate()
            self.assertIn("inconsistent-release", report.errors)

    def test_stale_vendored_source_digest_fails_before_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._copy(temporary)
            source = root / "sources" / "iana-application-2026-08-14.csv"
            source.write_bytes(source.read_bytes() + b"drift")
            report = IanaOwl2RlAdapter(root).validate()
            self.assertEqual(report.errors, ("release-integrity",))


if __name__ == "__main__":
    unittest.main()
