"""Mutation tests for proof DAG integrity and semantic replay."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from noema.errors import ProofVerificationError
from noema.model import (
    Judgement,
    JudgementStatus,
    Proof,
    ProofNode,
    ProofNodeKind,
)
from noema.proof import (
    judgement_from_dict,
    load_judgement,
    load_proof,
    proof_from_dict,
    verify_proof,
)
from noema.release import build_release, seal_release


FIXTURE = Path(__file__).parent / "fixtures" / "kernel"


def replace_node(proof: Proof, node_id: str, **changes: object) -> Proof:
    return replace(
        proof,
        nodes=tuple(
            replace(node, **changes) if node.id == node_id else node
            for node in proof.nodes
        ),
    )


def retarget(proof: Proof, judgement: Judgement, digest: str) -> tuple[Proof, Judgement]:
    return replace(proof, release_digest=digest), replace(
        judgement, release_digest=digest
    )


class ProofReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.release = build_release(FIXTURE / "release-manifest.json")
        self.proof = load_proof(FIXTURE / "proof.json")
        self.judgement = load_judgement(FIXTURE / "judgement.json")

    def verify(
        self,
        proof: Proof | None = None,
        judgement: Judgement | None = None,
    ):
        return verify_proof(
            self.release,
            judgement or self.judgement,
            proof or self.proof,
            trusted_release_digest=self.release.digest,
        )

    def test_valid_multi_hop_synthetic_proof_replays(self) -> None:
        result = self.verify()
        self.assertEqual(
            set(result.asserted_leaf_node_ids),
            {"node:registered", "node:suffix"},
        )
        self.assertEqual(
            set(result.applied_rule_ids),
            {"rule:suffix-syntax", "rule:json-serializable"},
        )
        self.assertEqual(len(result.proof_digest), 64)

    def test_changed_proof_release_digest_fails(self) -> None:
        with self.assertRaisesRegex(ProofVerificationError, "trusted release"):
            self.verify(replace(self.proof, release_digest="0" * 64))

    def test_changed_judgement_release_digest_fails(self) -> None:
        changed = replace(self.judgement, release_digest="0" * 64)
        with self.assertRaisesRegex(ProofVerificationError, "trusted release"):
            self.verify(judgement=changed)

    def test_changed_query_id_fails_release_binding(self) -> None:
        changed = replace(self.judgement, query_id="query:not-declared")
        with self.assertRaisesRegex(ProofVerificationError, "not declared"):
            self.verify(judgement=changed)

    def test_contradicted_status_requires_the_formal_complement(self) -> None:
        changed = replace(self.judgement, status=JudgementStatus.CONTRADICTED)
        with self.assertRaisesRegex(ProofVerificationError, "declared query"):
            self.verify(judgement=changed)

    def test_changed_conclusion_fails_rule_replay(self) -> None:
        proof = replace_node(
            self.proof,
            "node:serializable",
            claim_id="claim:json-syntax",
        )
        judgement = replace(
            self.judgement,
            conclusion_claim_ids=("claim:json-syntax",),
        )
        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            self.verify(proof, judgement)

    def test_missing_premise_node_fails(self) -> None:
        proof = replace(
            self.proof,
            nodes=tuple(node for node in self.proof.nodes if node.id != "node:suffix"),
        )
        with self.assertRaisesRegex(ProofVerificationError, "missing premise"):
            self.verify(proof)

    def test_removed_premise_reference_fails_rule_replay(self) -> None:
        proof = replace_node(
            self.proof,
            "node:json-syntax",
            premise_node_ids=("node:registered",),
        )
        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            self.verify(proof)

    def test_reordered_premises_fail_rule_replay(self) -> None:
        proof = replace_node(
            self.proof,
            "node:json-syntax",
            premise_node_ids=("node:suffix", "node:registered"),
        )
        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            self.verify(proof)

    def test_duplicate_premise_node_fails_closed(self) -> None:
        proof = replace_node(
            self.proof,
            "node:json-syntax",
            premise_node_ids=("node:registered", "node:registered"),
        )
        with self.assertRaisesRegex(ProofVerificationError, "repeats a premise"):
            self.verify(proof)

    def test_changed_rule_id_fails_rule_replay(self) -> None:
        proof = replace_node(
            self.proof,
            "node:json-syntax",
            rule_id="rule:json-serializable",
        )
        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            self.verify(proof)

    def test_changed_leaf_claim_fails_rule_replay(self) -> None:
        proof = replace_node(
            self.proof,
            "node:suffix",
            claim_id="claim:hostile-source",
        )
        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            self.verify(proof)

    def test_cycle_fails_closed(self) -> None:
        proof = replace_node(
            self.proof,
            "node:json-syntax",
            premise_node_ids=("node:registered", "node:serializable"),
        )
        with self.assertRaisesRegex(ProofVerificationError, "cycle"):
            self.verify(proof)

    def test_unreachable_node_fails_closed(self) -> None:
        orphan = ProofNode(
            id="node:orphan",
            kind=ProofNodeKind.ASSERTION,
            claim_id="claim:hostile-source",
        )
        proof = replace(self.proof, nodes=(*self.proof.nodes, orphan))
        with self.assertRaisesRegex(ProofVerificationError, "unreachable"):
            self.verify(proof)

    def test_duplicate_node_id_fails_closed(self) -> None:
        proof = replace(self.proof, nodes=(*self.proof.nodes, self.proof.nodes[0]))
        with self.assertRaisesRegex(ProofVerificationError, "duplicate"):
            self.verify(proof)

    def test_node_budget_is_release_pinned(self) -> None:
        release = seal_release(
            replace(
                self.release,
                backend=replace(
                    self.release.backend,
                    max_proof_nodes=3,
                    max_proof_depth=3,
                ),
            ),
            source_root=FIXTURE,
        )
        proof, judgement = retarget(self.proof, self.judgement, release.digest)
        with self.assertRaisesRegex(ProofVerificationError, "node budget"):
            verify_proof(
                release,
                judgement,
                proof,
                trusted_release_digest=release.digest,
            )

    def test_depth_budget_is_release_pinned(self) -> None:
        release = seal_release(
            replace(
                self.release,
                backend=replace(self.release.backend, max_proof_depth=2),
            ),
            source_root=FIXTURE,
        )
        proof, judgement = retarget(self.proof, self.judgement, release.digest)
        with self.assertRaisesRegex(ProofVerificationError, "depth budget"):
            verify_proof(
                release,
                judgement,
                proof,
                trusted_release_digest=release.digest,
            )

    def test_wrong_semantic_replayer_profile_fails(self) -> None:
        release = seal_release(
            replace(
                self.release,
                backend=replace(
                    self.release.backend,
                    semantic_profile="other-semantics/v1",
                ),
            ),
            source_root=FIXTURE,
        )
        proof, judgement = retarget(self.proof, self.judgement, release.digest)
        with self.assertRaisesRegex(ProofVerificationError, "semantic profile"):
            verify_proof(
                release,
                judgement,
                proof,
                trusted_release_digest=release.digest,
            )

    def test_truthy_non_boolean_profile_result_fails_closed(self) -> None:
        class TruthyProfileReplayer:
            def supports(self, backend):
                return "yes"

            def replay(self, rule, premises, conclusion):
                return True

        with self.assertRaisesRegex(ProofVerificationError, "semantic profile"):
            verify_proof(
                self.release,
                self.judgement,
                self.proof,
                trusted_release_digest=self.release.digest,
                replayer=TruthyProfileReplayer(),
            )

    def test_truthy_non_boolean_replay_result_fails_closed(self) -> None:
        class TruthyReplayReplayer:
            def supports(self, backend):
                return True

            def replay(self, rule, premises, conclusion):
                return "yes"

        with self.assertRaisesRegex(ProofVerificationError, "replay rejected"):
            verify_proof(
                self.release,
                self.judgement,
                self.proof,
                trusted_release_digest=self.release.digest,
                replayer=TruthyReplayReplayer(),
            )

    def test_replayer_exception_text_is_not_retained(self) -> None:
        class FailingReplayer:
            def supports(self, backend):
                raise RuntimeError("PRIVATE-RUNTIME-CANARY")

            def replay(self, rule, premises, conclusion):
                return False

        with self.assertRaises(ProofVerificationError) as caught:
            verify_proof(
                self.release,
                self.judgement,
                self.proof,
                trusted_release_digest=self.release.digest,
                replayer=FailingReplayer(),
            )
        self.assertNotIn("PRIVATE-RUNTIME-CANARY", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_proofless_judgement_rejects_attached_proof(self) -> None:
        judgement = Judgement(
            status=JudgementStatus.UNKNOWN,
            query_id="query:unknown",
            release_digest=self.release.digest,
            reason_code="reason:not-derived",
        )
        with self.assertRaisesRegex(ProofVerificationError, "roots"):
            self.verify(judgement=judgement)


class StrictProofParsingTests(unittest.TestCase):
    def test_proof_parser_rejects_question_text(self) -> None:
        proof = load_proof(FIXTURE / "proof.json").to_dict()
        proof["question_text"] = "private user question"
        with self.assertRaisesRegex(ProofVerificationError, "unknown"):
            proof_from_dict(proof)

    def test_judgement_parser_rejects_metadata(self) -> None:
        judgement = load_judgement(FIXTURE / "judgement.json").to_dict()
        judgement["metadata"] = {"question_text": "private user question"}
        with self.assertRaisesRegex(ProofVerificationError, "unknown"):
            judgement_from_dict(judgement)


if __name__ == "__main__":
    unittest.main()
