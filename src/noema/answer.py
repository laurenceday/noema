"""Build and independently verify proof-carrying Aleph-prime answers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from noema.adapters.iana_owl2_rl import IanaOwl2RlAdapter
from noema.canonical import (
    JSONValue,
    canonical_bytes,
    digest_domain_json,
    load_json_file,
)
from noema.evidence import project_evidence
from noema.errors import (
    AnswerVerificationError,
    CanonicalizationError,
    QuestionMappingError,
)
from noema.model import Judgement, Proof, Release, valid_digest, valid_identifier
from noema.proof import judgement_from_dict, proof_from_dict
from noema.query import (
    MappingStatus,
    QuestionMapping,
    load_question_catalogue,
    map_question,
    mapping_from_dict,
    validate_mapping,
)
from noema.release import build_release
from noema.render import RenderedAnswer, render_answer


ANSWER_HASH_DOMAIN = "noema:answer:v1"


def _fail(message: str) -> AnswerVerificationError:
    return AnswerVerificationError(message)


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


def _strict_evidence(raw: object, location: str) -> dict[str, JSONValue]:
    root = _object(raw, {"items", "proof_digest", "release_digest"}, location)
    release_digest = _string(root["release_digest"], f"{location}.release_digest")
    proof_digest = _string(root["proof_digest"], f"{location}.proof_digest")
    if not valid_digest(release_digest) or not valid_digest(proof_digest):
        raise _fail(f"{location} contains a malformed digest")
    items: list[dict[str, JSONValue]] = []
    for index, value in enumerate(_array(root["items"], f"{location}.items")):
        item_location = f"{location}.items[{index}]"
        item = _object(
            value,
            {
                "claim_id",
                "end",
                "path",
                "quote_base64",
                "quote_text",
                "source_id",
                "span_sha256",
                "start",
                "support_id",
            },
            item_location,
        )
        start = item["start"]
        end = item["end"]
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise _fail(f"{item_location} has invalid byte bounds")
        quote_text = item["quote_text"]
        if quote_text is not None and not isinstance(quote_text, str):
            raise _fail(f"{item_location}.quote_text must be a string or null")
        span_digest = _string(item["span_sha256"], f"{item_location}.span_sha256")
        if not valid_digest(span_digest):
            raise _fail(f"{item_location} has a malformed span digest")
        for field in ("claim_id", "source_id", "support_id"):
            if not valid_identifier(item[field]):
                raise _fail(f"{item_location}.{field} is invalid")
        items.append(
            {
                "claim_id": item["claim_id"],
                "end": end,
                "path": _string(item["path"], f"{item_location}.path"),
                "quote_base64": _string(
                    item["quote_base64"], f"{item_location}.quote_base64"
                ),
                "quote_text": quote_text,
                "source_id": item["source_id"],
                "span_sha256": span_digest,
                "start": start,
                "support_id": item["support_id"],
            }
        )
    return {
        "items": items,
        "proof_digest": proof_digest,
        "release_digest": release_digest,
    }


@dataclass(frozen=True, slots=True)
class AnswerResult:
    query_id: str
    judgement: Judgement
    proof: Proof | None
    evidence: dict[str, JSONValue] | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "evidence": self.evidence,
            "judgement": self.judgement.to_dict(),
            "proof": self.proof.to_dict() if self.proof is not None else None,
            "query_id": self.query_id,
        }


@dataclass(frozen=True, slots=True)
class AnswerEnvelope:
    answer_digest: str
    release_digest: str
    mapping: QuestionMapping
    status: str
    results: tuple[AnswerResult, ...]
    rendering: RenderedAnswer

    def payload_dict(self) -> dict[str, JSONValue]:
        return {
            "mapping": self.mapping.to_dict(),
            "release_digest": self.release_digest,
            "rendering": self.rendering.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "schema": "noema.answer/v1",
            "status": self.status,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        result = self.payload_dict()
        result["answer_digest"] = self.answer_digest
        return result


@dataclass(frozen=True, slots=True)
class AnswerVerificationReceipt:
    answer_digest: str
    release_digest: str
    result_count: int
    valid: bool = True

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "answer_digest": self.answer_digest,
            "release_digest": self.release_digest,
            "result_count": self.result_count,
            "valid": self.valid,
        }


def seal_answer(answer: AnswerEnvelope) -> AnswerEnvelope:
    digest = digest_domain_json(ANSWER_HASH_DOMAIN, answer.payload_dict())
    return replace(answer, answer_digest=digest)


def _release_and_adapter(
    domain_root: Path,
    adapter: IanaOwl2RlAdapter | None,
) -> tuple[Release, IanaOwl2RlAdapter]:
    root = Path(domain_root)
    selected = adapter or IanaOwl2RlAdapter(root)
    report = selected.validate()
    if not report.valid:
        raise _fail("domain release validation failed")
    release = build_release(root / "release.json")
    if release.digest != selected.trusted_release_digest:
        raise _fail("domain release does not match the compiled trust anchor")
    return release, selected


def answer_question(
    domain_root: Path,
    question: str,
    *,
    adapter: IanaOwl2RlAdapter | None = None,
) -> AnswerEnvelope:
    """Map and answer without placing the transient question in the certificate."""
    root = Path(domain_root)
    release, selected = _release_and_adapter(root, adapter)
    catalogue = load_question_catalogue(root / "questions.json", release)
    mapping = map_question(question, catalogue, release)
    results: list[AnswerResult] = []
    if mapping.status is MappingStatus.MAPPED:
        for query_id in mapping.query_ids:
            decision = selected.decide(query_id)
            evidence: dict[str, JSONValue] | None = None
            if decision.proof is not None:
                packet = project_evidence(
                    release,
                    decision.judgement,
                    decision.proof,
                    source_root=root,
                    trusted_release_digest=selected.trusted_release_digest,
                    replayer=selected.replayer,
                )
                evidence = packet.to_dict()
            results.append(
                AnswerResult(
                    query_id=query_id,
                    judgement=decision.judgement,
                    proof=decision.proof,
                    evidence=evidence,
                )
            )
    rendering = render_answer(
        mapping,
        tuple(result.judgement for result in results),
    )
    return seal_answer(
        AnswerEnvelope(
            answer_digest="",
            release_digest=release.digest,
            mapping=mapping,
            status=rendering.status,
            results=tuple(results),
            rendering=rendering,
        )
    )


def answer_from_dict(raw: JSONValue) -> AnswerEnvelope:
    """Strictly parse an answer and reject retention or extension fields."""
    root = _object(
        raw,
        {
            "answer_digest",
            "mapping",
            "release_digest",
            "rendering",
            "results",
            "schema",
            "status",
        },
        "answer",
    )
    if root["schema"] != "noema.answer/v1":
        raise _fail("answer schema differs")
    answer_digest = _string(root["answer_digest"], "answer.answer_digest")
    release_digest = _string(root["release_digest"], "answer.release_digest")
    if not valid_digest(answer_digest) or not valid_digest(release_digest):
        raise _fail("answer contains a malformed digest")
    try:
        mapping = mapping_from_dict(root["mapping"])
    except QuestionMappingError as exc:
        raise _fail("answer mapping is malformed") from exc
    rendering_raw = _object(
        root["rendering"],
        {"code", "status", "text"},
        "answer.rendering",
    )
    rendering = RenderedAnswer(
        code=_string(rendering_raw["code"], "answer.rendering.code"),
        status=_string(rendering_raw["status"], "answer.rendering.status"),
        text=_string(rendering_raw["text"], "answer.rendering.text"),
    )
    results: list[AnswerResult] = []
    for index, value in enumerate(_array(root["results"], "answer.results")):
        location = f"answer.results[{index}]"
        item = _object(
            value,
            {"evidence", "judgement", "proof", "query_id"},
            location,
        )
        query_id = _string(item["query_id"], f"{location}.query_id")
        if not valid_identifier(query_id):
            raise _fail(f"{location}.query_id is invalid")
        try:
            judgement = judgement_from_dict(item["judgement"])
            proof = (
                proof_from_dict(item["proof"])
                if item["proof"] is not None
                else None
            )
        except Exception as exc:
            raise _fail(f"{location} has a malformed decision") from exc
        evidence = (
            _strict_evidence(item["evidence"], f"{location}.evidence")
            if item["evidence"] is not None
            else None
        )
        if judgement.query_id != query_id:
            raise _fail(f"{location} query IDs differ")
        results.append(AnswerResult(query_id, judgement, proof, evidence))
    answer = AnswerEnvelope(
        answer_digest=answer_digest,
        release_digest=release_digest,
        mapping=mapping,
        status=_string(root["status"], "answer.status"),
        results=tuple(results),
        rendering=rendering,
    )
    expected_digest = digest_domain_json(ANSWER_HASH_DOMAIN, answer.payload_dict())
    if answer.answer_digest != expected_digest:
        raise _fail("answer digest does not match its payload")
    return answer


def load_answer(path: Path) -> AnswerEnvelope:
    try:
        return answer_from_dict(load_json_file(path))
    except (CanonicalizationError, OSError) as exc:
        raise _fail("answer file cannot be loaded") from exc


def write_answer(path: Path, answer: AnswerEnvelope) -> None:
    """Create, but never overwrite, a canonical answer certificate."""
    data = canonical_bytes(answer.to_dict()) + b"\n"
    try:
        with Path(path).open("xb") as handle:
            handle.write(data)
    except OSError as exc:
        raise _fail("answer output cannot be created") from exc


def verify_answer(
    domain_root: Path,
    answer: AnswerEnvelope,
    *,
    adapter: IanaOwl2RlAdapter | None = None,
) -> AnswerVerificationReceipt:
    """Recompute mapping plan, decisions, proofs, evidence, and rendering."""
    root = Path(domain_root)
    release, selected = _release_and_adapter(root, adapter)
    expected_answer_digest = digest_domain_json(ANSWER_HASH_DOMAIN, answer.payload_dict())
    if (
        not valid_digest(answer.answer_digest)
        or answer.answer_digest != expected_answer_digest
    ):
        raise _fail("answer digest does not match its payload")
    if answer.release_digest != selected.trusted_release_digest:
        raise _fail("answer targets a different release")
    catalogue = load_question_catalogue(root / "questions.json", release)
    try:
        validate_mapping(answer.mapping, catalogue, release)
    except QuestionMappingError as exc:
        raise _fail("answer mapping differs from the pinned catalogue") from exc

    if answer.mapping.status is MappingStatus.MAPPED:
        if tuple(result.query_id for result in answer.results) != answer.mapping.query_ids:
            raise _fail("answer results differ from the all-query plan")
        for result in answer.results:
            recomputed = selected.decide(result.query_id)
            if result.judgement != recomputed.judgement or result.proof != recomputed.proof:
                raise _fail("answer decision differs from deterministic recomputation")
            if result.proof is None:
                if result.evidence is not None:
                    raise _fail("proofless answer result carries evidence")
            else:
                selected.verify(result.judgement, result.proof)
                expected_evidence = project_evidence(
                    release,
                    result.judgement,
                    result.proof,
                    source_root=root,
                    trusted_release_digest=selected.trusted_release_digest,
                    replayer=selected.replayer,
                ).to_dict()
                if result.evidence != expected_evidence:
                    raise _fail("answer evidence differs from deterministic projection")
    elif answer.results:
        raise _fail("refused answer carries formal results")

    expected_rendering = render_answer(
        answer.mapping,
        tuple(result.judgement for result in answer.results),
    )
    if answer.rendering != expected_rendering or answer.status != expected_rendering.status:
        raise _fail("answer rendering differs from deterministic recomputation")
    return AnswerVerificationReceipt(
        answer_digest=answer.answer_digest,
        release_digest=release.digest,
        result_count=len(answer.results),
    )
