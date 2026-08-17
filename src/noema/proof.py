"""Replay proof DAGs against release-pinned grounded rule semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from noema.canonical import JSONValue, digest_domain_json, load_json_file
from noema.errors import (
    CanonicalizationError,
    JudgementValidationError,
    ProofVerificationError,
    ReleaseValidationError,
)
from noema.model import (
    BackendDeclaration,
    FormalClaim,
    GroundRule,
    Judgement,
    JudgementStatus,
    Proof,
    ProofNode,
    ProofNodeKind,
    Release,
    valid_digest,
    valid_identifier,
)
from noema.release import validate_release


PROOF_HASH_DOMAIN = "noema:proof:v1"


class RuleReplayer(Protocol):
    """Adapter hook that independently checks one rule application."""

    def supports(self, backend: BackendDeclaration) -> bool:
        """Return whether this replayer implements the declared semantics."""

    def replay(
        self,
        rule: GroundRule,
        premises: tuple[FormalClaim, ...],
        conclusion: FormalClaim,
    ) -> bool:
        """Return whether the ordered claims satisfy the pinned rule."""


@dataclass(frozen=True, slots=True)
class ExactGroundReplayer:
    """Synthetic Step 2 semantics: exact ordered grounded applications."""

    semantic_profile: str = "exact-ground/v1"

    def supports(self, backend: BackendDeclaration) -> bool:
        return backend.semantic_profile == self.semantic_profile

    def replay(
        self,
        rule: GroundRule,
        premises: tuple[FormalClaim, ...],
        conclusion: FormalClaim,
    ) -> bool:
        return (
            tuple(claim.id for claim in premises) == rule.premise_claim_ids
            and conclusion.id == rule.conclusion_claim_id
        )


@dataclass(frozen=True, slots=True)
class VerificationResult:
    proof_digest: str
    reachable_node_ids: tuple[str, ...]
    asserted_leaf_node_ids: tuple[str, ...]
    applied_rule_ids: tuple[str, ...]


def _fail(message: str) -> ProofVerificationError:
    return ProofVerificationError(message)


def proof_digest(proof: Proof) -> str:
    """Hash the complete proof envelope under its own domain."""
    payload = proof.to_dict()
    payload["nodes"] = [
        node.to_dict() for node in sorted(proof.nodes, key=lambda value: value.id)
    ]
    return digest_domain_json(PROOF_HASH_DOMAIN, payload)


def verify_proof(
    release: Release,
    judgement: Judgement,
    proof: Proof,
    *,
    trusted_release_digest: str,
    replayer: RuleReplayer | None = None,
) -> VerificationResult:
    """Verify graph integrity and replay every reachable rule application."""
    try:
        validate_release(release, expected_digest=trusted_release_digest)
        judgement.validate()
    except (ReleaseValidationError, JudgementValidationError) as exc:
        raise _fail(str(exc)) from exc

    if not valid_digest(proof.release_digest):
        raise _fail("proof release digest is malformed")
    if proof.release_digest != trusted_release_digest:
        raise _fail("proof does not target the trusted release")
    if judgement.release_digest != trusted_release_digest:
        raise _fail("judgement does not target the trusted release")
    if tuple(proof.root_node_ids) != tuple(judgement.proof_root_node_ids):
        raise _fail("proof roots do not match the judgement")
    if not proof.nodes:
        raise _fail("proof contains no nodes")
    if len(proof.nodes) > release.backend.max_proof_nodes:
        raise _fail("proof exceeds the release-pinned node budget")

    node_by_id: dict[str, ProofNode] = {}
    for node in proof.nodes:
        if not valid_identifier(node.id):
            raise _fail("proof node ID is invalid")
        if node.id in node_by_id:
            raise _fail(f"duplicate proof node ID: {node.id}")
        if not valid_identifier(node.claim_id):
            raise _fail(f"proof node {node.id!r} has an invalid claim ID")
        if node.rule_id is not None and not valid_identifier(node.rule_id):
            raise _fail(f"proof node {node.id!r} has an invalid rule ID")
        if any(not valid_identifier(value) for value in node.premise_node_ids):
            raise _fail(f"proof node {node.id!r} has an invalid premise node ID")
        if len(node.premise_node_ids) != len(set(node.premise_node_ids)):
            raise _fail(f"proof node {node.id!r} repeats a premise node")
        node_by_id[node.id] = node

    if len(set(proof.root_node_ids)) != len(proof.root_node_ids):
        raise _fail("proof roots must be distinct")
    for root_id in proof.root_node_ids:
        if not valid_identifier(root_id):
            raise _fail("proof root ID is invalid")
        if root_id not in node_by_id:
            raise _fail(f"missing proof root node: {root_id}")

    claim_by_id = {claim.id: claim for claim in release.claims}
    rule_by_id = {rule.id: rule for rule in release.rules}
    semantic_replayer = replayer or ExactGroundReplayer()
    profile_check_failed = False
    try:
        supported = semantic_replayer.supports(release.backend)
    except Exception:
        profile_check_failed = True
        supported = False
    if profile_check_failed:
        raise _fail("rule replayer profile check failed")
    if supported is not True:
        raise _fail("rule replayer does not implement the release semantic profile")

    visiting: set[str] = set()
    verified: set[str] = set()
    leaves: set[str] = set()
    applied_rules: set[str] = set()

    def replay_node(node_id: str, depth: int) -> None:
        if depth > release.backend.max_proof_depth:
            raise _fail("proof exceeds the release-pinned depth budget")
        if node_id in visiting:
            raise _fail(f"proof cycle detected at node {node_id!r}")
        if node_id in verified:
            return
        node = node_by_id.get(node_id)
        if node is None:
            raise _fail(f"missing premise node: {node_id}")
        claim = claim_by_id.get(node.claim_id)
        if claim is None:
            raise _fail(f"proof node {node.id!r} refers to an unknown claim")

        visiting.add(node_id)
        if node.kind is ProofNodeKind.ASSERTION:
            if node.rule_id is not None or node.premise_node_ids:
                raise _fail(f"assertion node {node.id!r} carries rule material")
            if not claim.asserted:
                raise _fail(f"assertion node {node.id!r} is not a release assertion")
            leaves.add(node_id)
        elif node.kind is ProofNodeKind.RULE:
            if node.rule_id is None:
                raise _fail(f"rule node {node.id!r} lacks a rule ID")
            rule = rule_by_id.get(node.rule_id)
            if rule is None:
                raise _fail(f"rule node {node.id!r} uses an unknown rule")
            if not node.premise_node_ids:
                raise _fail(f"rule node {node.id!r} has no premises")
            for premise_node_id in node.premise_node_ids:
                replay_node(premise_node_id, depth + 1)
            premises = tuple(
                claim_by_id[node_by_id[premise_id].claim_id]
                for premise_id in node.premise_node_ids
            )
            replay_failed = False
            try:
                accepted = semantic_replayer.replay(rule, premises, claim)
            except Exception:
                replay_failed = True
                accepted = False
            if replay_failed:
                raise _fail(f"rule replayer failed at node {node.id!r}")
            if accepted is not True:
                raise _fail(f"rule replay rejected node {node.id!r}")
            applied_rules.add(rule.id)
        else:
            raise _fail(f"proof node {node.id!r} has an unknown node kind")
        visiting.remove(node_id)
        verified.add(node_id)

    for root_id in proof.root_node_ids:
        replay_node(root_id, 1)

    if verified != set(node_by_id):
        orphaned = sorted(set(node_by_id) - verified)
        raise _fail(f"proof contains unreachable node(s): {orphaned}")
    root_claims = tuple(node_by_id[root].claim_id for root in proof.root_node_ids)
    if root_claims != judgement.conclusion_claim_ids:
        raise _fail("proof root conclusions do not match the judgement")
    query_by_id = {query.id: query for query in release.queries}
    query = query_by_id.get(judgement.query_id)
    if query is None:
        raise _fail("judgement query is not declared by the release")
    if judgement.status is JudgementStatus.ENTAILED:
        expected_query_claims = (query.positive_claim_id,)
    elif judgement.status is JudgementStatus.CONTRADICTED:
        if query.complement_claim_id is None:
            raise _fail("query does not declare a formal complement")
        expected_query_claims = (query.complement_claim_id,)
    elif judgement.status is JudgementStatus.BOTH:
        if query.complement_claim_id is None:
            raise _fail("query does not declare a formal complement")
        expected_query_claims = (
            query.positive_claim_id,
            query.complement_claim_id,
        )
    else:
        raise _fail("proof verification requires a proof-bearing judgement")
    if root_claims != expected_query_claims:
        raise _fail("proof conclusions do not answer the declared query")

    return VerificationResult(
        proof_digest=proof_digest(proof),
        reachable_node_ids=tuple(sorted(verified)),
        asserted_leaf_node_ids=tuple(sorted(leaves)),
        applied_rule_ids=tuple(sorted(applied_rules)),
    )


def _object(value: object, keys: set[str], location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _fail(f"{location} must be an object")
    actual = set(value)
    if actual != keys:
        raise _fail(
            f"{location} fields differ; missing={sorted(keys - actual)}, "
            f"unknown={sorted(actual - keys)}"
        )
    return value


def _array(value: object, location: str) -> list[object]:
    if not isinstance(value, list):
        raise _fail(f"{location} must be an array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(f"{location} must be a non-empty string")
    return value


def _string_array(value: object, location: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{location}[{index}]")
        for index, item in enumerate(_array(value, location))
    )


def proof_from_dict(raw: JSONValue) -> Proof:
    """Strictly decode a proof, rejecting retention or extension fields."""
    root = _object(raw, {"nodes", "release_digest", "root_node_ids"}, "proof")
    nodes: list[ProofNode] = []
    for index, value in enumerate(_array(root["nodes"], "proof.nodes")):
        location = f"proof.nodes[{index}]"
        node = _object(
            value,
            {"claim_id", "id", "kind", "premise_node_ids", "rule_id"},
            location,
        )
        try:
            kind = ProofNodeKind(_string(node["kind"], f"{location}.kind"))
        except ValueError as exc:
            raise _fail(f"{location}.kind is unknown") from exc
        rule_id_raw = node["rule_id"]
        if rule_id_raw is not None and not isinstance(rule_id_raw, str):
            raise _fail(f"{location}.rule_id must be a string or null")
        nodes.append(
            ProofNode(
                id=_string(node["id"], f"{location}.id"),
                kind=kind,
                claim_id=_string(node["claim_id"], f"{location}.claim_id"),
                rule_id=rule_id_raw,
                premise_node_ids=_string_array(
                    node["premise_node_ids"], f"{location}.premise_node_ids"
                ),
            )
        )
    return Proof(
        release_digest=_string(root["release_digest"], "proof.release_digest"),
        root_node_ids=_string_array(root["root_node_ids"], "proof.root_node_ids"),
        nodes=tuple(nodes),
    )


def judgement_from_dict(raw: JSONValue) -> Judgement:
    """Strictly decode a typed judgement without retaining user prose."""
    root = _object(
        raw,
        {
            "conclusion_claim_ids",
            "proof_root_node_ids",
            "query_id",
            "reason_code",
            "release_digest",
            "status",
        },
        "judgement",
    )
    try:
        status = JudgementStatus(_string(root["status"], "judgement.status"))
    except ValueError as exc:
        raise _fail("judgement.status is unknown") from exc
    reason_raw = root["reason_code"]
    if reason_raw is not None and not isinstance(reason_raw, str):
        raise _fail("judgement.reason_code must be a string or null")
    judgement = Judgement(
        status=status,
        query_id=_string(root["query_id"], "judgement.query_id"),
        release_digest=_string(
            root["release_digest"], "judgement.release_digest"
        ),
        conclusion_claim_ids=_string_array(
            root["conclusion_claim_ids"], "judgement.conclusion_claim_ids"
        ),
        proof_root_node_ids=_string_array(
            root["proof_root_node_ids"], "judgement.proof_root_node_ids"
        ),
        reason_code=reason_raw,
    )
    try:
        judgement.validate()
    except JudgementValidationError as exc:
        raise _fail(str(exc)) from exc
    return judgement


def load_proof(path: Path) -> Proof:
    try:
        return proof_from_dict(load_json_file(path))
    except CanonicalizationError as exc:
        raise _fail(str(exc)) from exc


def load_judgement(path: Path) -> Judgement:
    try:
        return judgement_from_dict(load_json_file(path))
    except CanonicalizationError as exc:
        raise _fail(str(exc)) from exc
