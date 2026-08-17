"""Null-prime evaluations and simulation-only release mutations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from noema.adapters.iana_owl2_rl import IanaOwl2RlAdapter, OwlRlFragmentReplayer
from noema.answer import answer_question
from noema.canonical import JSONValue, digest_bytes, load_json_bytes
from noema.errors import (
    CanonicalizationError,
    NoemaError,
    ProbeValidationError,
    ProofVerificationError,
)
from noema.model import (
    JudgementStatus,
    ProofNodeKind,
    QuerySpec,
    Release,
    valid_identifier,
)
from noema.proof import verify_proof
from noema.query import MAX_QUESTION_BYTES, MappingStatus, load_question_catalogue
from noema.release import build_release, seal_release


_COVERAGE = frozenset(
    {"ambiguous", "contradicted", "entailed", "unknown", "unsupported"}
)


def _fail(message: str) -> ProbeValidationError:
    return ProbeValidationError(message)


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


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: str
    category: str
    question: str
    expected_mapping_status: str
    expected_answer_status: str


@dataclass(frozen=True, slots=True)
class MutationTarget:
    id: str
    kind: str
    simulation_only: bool
    query_id: str
    candidate_claim_ids: tuple[str, ...]
    expected_before: str
    expected_after: str


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    cases: tuple[EvaluationCase, ...]
    mutation_targets: tuple[MutationTarget, ...]


def load_evaluation_suite(path: Path, release: Release) -> EvaluationSuite:
    """Load strict, pinned evaluation cases; never append runtime questions."""
    sources = tuple(source for source in release.sources if source.path == "evals.json")
    if len(sources) != 1:
        raise _fail("evaluation suite is not uniquely pinned by the release")
    try:
        data = Path(path).read_bytes()
        if len(data) != sources[0].byte_length or digest_bytes(data) != sources[0].sha256:
            raise _fail("evaluation suite bytes differ from the pinned source")
        raw = load_json_bytes(data)
    except (CanonicalizationError, OSError) as exc:
        raise _fail("evaluation suite cannot be loaded") from exc
    root = _object(
        raw,
        {"cases", "mutation_targets", "release_id", "schema"},
        "evaluations",
    )
    if root["schema"] != "noema.evals/v1":
        raise _fail("evaluation suite schema differs")
    if root["release_id"] != release.release_id:
        raise _fail("evaluation suite targets a different release")
    cases: list[EvaluationCase] = []
    case_ids: set[str] = set()
    for index, value in enumerate(_array(root["cases"], "evaluations.cases")):
        item = _object(
            value,
            {
                "category",
                "expected_answer_status",
                "expected_mapping_status",
                "id",
                "question",
            },
            f"cases[{index}]",
        )
        case_id = _identifier(item["id"], f"cases[{index}].id")
        category = _string(item["category"], f"cases[{index}].category")
        mapping_status = _string(
            item["expected_mapping_status"],
            f"cases[{index}].expected_mapping_status",
        )
        answer_status = _string(
            item["expected_answer_status"],
            f"cases[{index}].expected_answer_status",
        )
        question = _string(item["question"], f"cases[{index}].question")
        if case_id in case_ids:
            raise _fail("evaluation suite repeats a case")
        if category not in _COVERAGE or answer_status != category:
            raise _fail("evaluation category does not match its answer status")
        if mapping_status not in {status.value for status in MappingStatus}:
            raise _fail("evaluation mapping status is unknown")
        expected_mapping = {
            "ambiguous": MappingStatus.AMBIGUOUS.value,
            "contradicted": MappingStatus.MAPPED.value,
            "entailed": MappingStatus.MAPPED.value,
            "unknown": MappingStatus.MAPPED.value,
            "unsupported": MappingStatus.UNSUPPORTED.value,
        }
        if mapping_status != expected_mapping[category]:
            raise _fail("evaluation mapping status conflicts with its category")
        try:
            question_bytes = question.encode("ascii")
        except UnicodeEncodeError:
            question_bytes = b""
        if (
            not question_bytes
            or len(question_bytes) > MAX_QUESTION_BYTES
            or any(byte < 0x20 or byte > 0x7E for byte in question_bytes)
        ):
            raise _fail("evaluation question is not bounded printable ASCII")
        cases.append(
            EvaluationCase(
                case_id,
                category,
                question,
                mapping_status,
                answer_status,
            )
        )
        case_ids.add(case_id)
    if {case.category for case in cases} != _COVERAGE:
        raise _fail("evaluation suite lacks required boundary coverage")
    if tuple(case.id for case in cases) != tuple(sorted(case_ids)):
        raise _fail("evaluation cases are not ID-sorted")

    claim_by_id = {claim.id: claim for claim in release.claims}
    query_ids = {query.id for query in release.queries}
    targets: list[MutationTarget] = []
    target_ids: set[str] = set()
    for index, value in enumerate(
        _array(root["mutation_targets"], "evaluations.mutation_targets")
    ):
        item = _object(
            value,
            {
                "candidate_claim_ids",
                "expected_after",
                "expected_before",
                "id",
                "kind",
                "query_id",
                "simulation_only",
            },
            f"mutation_targets[{index}]",
        )
        target_id = _identifier(item["id"], f"mutation_targets[{index}].id")
        query_id = _identifier(item["query_id"], f"mutation_targets[{index}].query_id")
        kind = _string(item["kind"], f"mutation_targets[{index}].kind")
        simulation_only = item["simulation_only"]
        before = _string(item["expected_before"], "mutation.expected_before")
        after = _string(item["expected_after"], "mutation.expected_after")
        candidates = tuple(
            _identifier(claim_id, "mutation.candidate_claim_id")
            for claim_id in _array(
                item["candidate_claim_ids"], "mutation.candidate_claim_ids"
            )
        )
        if target_id in target_ids or query_id not in query_ids:
            raise _fail("mutation target repeats or names an unknown query")
        if kind != "remove-assertion" or simulation_only is not True:
            raise _fail("mutation target is not simulation-only and allowlisted")
        if (
            not candidates
            or candidates != tuple(sorted(set(candidates)))
            or any(
                claim_id not in claim_by_id or not claim_by_id[claim_id].asserted
                for claim_id in candidates
            )
        ):
            raise _fail("mutation candidate claims are invalid")
        allowed_statuses = {
            JudgementStatus.CONTRADICTED.value,
            JudgementStatus.ENTAILED.value,
            JudgementStatus.UNKNOWN.value,
        }
        if before not in allowed_statuses or after not in allowed_statuses or before == after:
            raise _fail("mutation expected statuses are invalid")
        targets.append(
            MutationTarget(
                target_id,
                kind,
                True,
                query_id,
                candidates,
                before,
                after,
            )
        )
        target_ids.add(target_id)
    if not targets or tuple(target.id for target in targets) != tuple(sorted(target_ids)):
        raise _fail("mutation targets are missing or not ID-sorted")
    return EvaluationSuite(tuple(cases), tuple(targets))


def _reachable_claims(
    release: Release,
    replayer: OwlRlFragmentReplayer,
) -> frozenset[str]:
    claims = {claim.id: claim for claim in release.claims}
    reachable = {claim.id for claim in release.claims if claim.asserted}
    changed = True
    while changed:
        changed = False
        for rule in release.rules:
            if rule.conclusion_claim_id in reachable:
                continue
            if not all(premise in reachable for premise in rule.premise_claim_ids):
                continue
            premises = tuple(claims[premise] for premise in rule.premise_claim_ids)
            if replayer.replay(rule, premises, claims[rule.conclusion_claim_id]) is True:
                reachable.add(rule.conclusion_claim_id)
                changed = True
    return frozenset(reachable)


def _query_status(query: QuerySpec, reachable: frozenset[str]) -> str:
    positive = query.positive_claim_id in reachable
    complement = (
        query.complement_claim_id is not None
        and query.complement_claim_id in reachable
    )
    if positive and complement:
        return JudgementStatus.BOTH.value
    if positive:
        return JudgementStatus.ENTAILED.value
    if complement:
        return JudgementStatus.CONTRADICTED.value
    return JudgementStatus.UNKNOWN.value


def _remove_assertion(release: Release, claim_id: str) -> Release:
    return replace(
        release,
        claims=tuple(
            replace(claim, asserted=False) if claim.id == claim_id else claim
            for claim in release.claims
        ),
        digest="",
    )


def _run_mutation(
    release: Release,
    adapter: IanaOwl2RlAdapter,
    target: MutationTarget,
) -> dict[str, JSONValue]:
    query = next(query for query in release.queries if query.id == target.query_id)
    baseline = adapter.decide(target.query_id)
    baseline_status = baseline.judgement.status.value
    proof_leaf_claims = {
        node.claim_id
        for node in (baseline.proof.nodes if baseline.proof is not None else ())
        if node.kind is ProofNodeKind.ASSERTION
    }
    selected: tuple[str, str, Release] | None = None
    for claim_id in target.candidate_claim_ids:
        if claim_id not in proof_leaf_claims:
            continue
        hypothetical = _remove_assertion(release, claim_id)
        after = _query_status(
            query,
            _reachable_claims(hypothetical, adapter.replayer),
        )
        if after == target.expected_after:
            selected = (claim_id, after, hypothetical)
            break

    if selected is None:
        return {
            "after": baseline_status,
            "before": baseline_status,
            "changed_assertions": 0,
            "claim_id": None,
            "failure_code": "probe:no-minimal-mutation",
            "hypothetical_adapter_eligible": False,
            "hypothetical_release_digest": None,
            "id": target.id,
            "kind": target.kind,
            "old_certificate_rejected": False,
            "passed": False,
            "simulation_only": True,
        }

    claim_id, after, hypothetical = selected
    sealed = seal_release(hypothetical)
    old_certificate_rejected = False
    if baseline.proof is not None:
        try:
            verify_proof(
                sealed,
                baseline.judgement,
                baseline.proof,
                trusted_release_digest=sealed.digest,
                replayer=adapter.replayer,
            )
        except ProofVerificationError:
            old_certificate_rejected = True
        if old_certificate_rejected:
            try:
                verify_proof(
                    sealed,
                    replace(baseline.judgement, release_digest=sealed.digest),
                    replace(baseline.proof, release_digest=sealed.digest),
                    trusted_release_digest=sealed.digest,
                    replayer=adapter.replayer,
                )
            except ProofVerificationError:
                pass
            else:
                old_certificate_rejected = False
    passed = (
        baseline_status == target.expected_before
        and after == target.expected_after
        and old_certificate_rejected
    )
    return {
        "after": after,
        "before": baseline_status,
        "changed_assertions": 1,
        "claim_id": claim_id,
        "failure_code": None if passed else "probe:mutation-expectation",
        "hypothetical_adapter_eligible": False,
        "hypothetical_release_digest": sealed.digest,
        "id": target.id,
        "kind": target.kind,
        "old_certificate_rejected": old_certificate_rejected,
        "passed": passed,
        "simulation_only": True,
    }


def _domain_snapshot(root: Path, release: Release) -> tuple[tuple[str, str], ...] | None:
    """Hash the manifest and every release-pinned source without following new input."""
    paths = ("release.json", *(source.path for source in release.sources))
    try:
        return tuple(
            (relative, digest_bytes((root / relative).read_bytes()))
            for relative in sorted(set(paths))
        )
    except OSError:
        return None


def run_probe(
    domain_root: Path,
    *,
    adapter: IanaOwl2RlAdapter | None = None,
) -> dict[str, JSONValue]:
    """Run pinned cases and in-memory mutations without retaining new questions."""
    root = Path(domain_root)
    selected = adapter or IanaOwl2RlAdapter(root)
    report = selected.validate()
    if not report.valid:
        raise _fail("domain release validation failed")
    release = build_release(root / "release.json")
    if release.digest != selected.trusted_release_digest:
        raise _fail("domain release does not match the compiled trust anchor")
    load_question_catalogue(root / "questions.json", release)
    suite = load_evaluation_suite(root / "evals.json", release)
    before_snapshot = _domain_snapshot(root, release)
    if before_snapshot is None:
        raise _fail("active domain snapshot cannot be read")

    case_reports: list[dict[str, JSONValue]] = []
    for case in suite.cases:
        failure_code: str | None = None
        try:
            answer = answer_question(root, case.question, adapter=selected)
            mapping_status = answer.mapping.status.value
            answer_status = answer.status
            passed = (
                mapping_status == case.expected_mapping_status
                and answer_status == case.expected_answer_status
            )
            if not passed:
                failure_code = "probe:case-expectation"
        except NoemaError:
            mapping_status = "error"
            answer_status = "error"
            passed = False
            failure_code = "probe:case-error"
        case_reports.append(
            {
                "answer_status": answer_status,
                "failure_code": failure_code,
                "id": case.id,
                "mapping_status": mapping_status,
                "passed": passed,
            }
        )

    mutation_reports = [
        _run_mutation(release, selected, target)
        for target in suite.mutation_targets
    ]
    active_release_unchanged = before_snapshot == _domain_snapshot(root, release)
    for item in mutation_reports:
        item["active_release_unchanged"] = active_release_unchanged
        if not active_release_unchanged:
            item["failure_code"] = "probe:active-release-mutated"
            item["passed"] = False
    coverage = dict(sorted(Counter(case.category for case in suite.cases).items()))
    passed = all(item["passed"] is True for item in case_reports) and all(
        item["passed"] is True for item in mutation_reports
    )
    return {
        "cases": case_reports,
        "coverage": coverage,
        "mutations": mutation_reports,
        "passed": passed,
        "release_digest": release.digest,
        "schema": "noema.probe-report/v1",
    }
