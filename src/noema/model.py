"""Immutable data contracts for releases, judgements, proofs, and evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from noema.canonical import JSONValue
from noema.errors import JudgementValidationError


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+#-]{0,127}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def valid_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(IDENTIFIER_PATTERN.fullmatch(value))


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and bool(DIGEST_PATTERN.fullmatch(value))


@dataclass(frozen=True, slots=True)
class BackendDeclaration:
    id: str
    version: str
    semantic_profile: str
    max_proof_nodes: int
    max_proof_depth: int

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "max_proof_depth": self.max_proof_depth,
            "max_proof_nodes": self.max_proof_nodes,
            "semantic_profile": self.semantic_profile,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: str
    path: str
    media_type: str
    license_id: str
    sha256: str
    byte_length: int

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "byte_length": self.byte_length,
            "id": self.id,
            "license": self.license_id,
            "media_type": self.media_type,
            "path": self.path,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class FormalClaim:
    id: str
    expression: str
    asserted: bool

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "asserted": self.asserted,
            "expression": self.expression,
            "id": self.id,
        }


@dataclass(frozen=True, slots=True)
class GroundRule:
    """One release-pinned, fully grounded rule application pattern."""

    id: str
    premise_claim_ids: tuple[str, ...]
    conclusion_claim_id: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "conclusion": self.conclusion_claim_id,
            "id": self.id,
            "premises": list(self.premise_claim_ids),
        }


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A half-open byte range in a pinned source."""

    source_id: str
    start: int
    end: int
    sha256: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "end": self.end,
            "sha256": self.sha256,
            "source_id": self.source_id,
            "start": self.start,
        }


@dataclass(frozen=True, slots=True)
class ClaimSupport:
    """One alternative support set; every member span is jointly required."""

    claim_id: str
    support_id: str
    spans: tuple[SourceSpan, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "claim_id": self.claim_id,
            "spans": [span.to_dict() for span in self.spans],
            "support_id": self.support_id,
        }


@dataclass(frozen=True, slots=True)
class Release:
    format_version: int
    release_id: str
    backend: BackendDeclaration
    sources: tuple[SourceRecord, ...]
    claims: tuple[FormalClaim, ...]
    rules: tuple[GroundRule, ...]
    claim_maps: tuple[ClaimSupport, ...]
    digest: str

    def payload_dict(self) -> dict[str, JSONValue]:
        return {
            "backend": self.backend.to_dict(),
            "claim_maps": [mapping.to_dict() for mapping in self.claim_maps],
            "claims": [claim.to_dict() for claim in self.claims],
            "format_version": self.format_version,
            "release_id": self.release_id,
            "rules": [rule.to_dict() for rule in self.rules],
            "sources": [source.to_dict() for source in self.sources],
        }

    def to_dict(self) -> dict[str, JSONValue]:
        result = self.payload_dict()
        result["digest"] = self.digest
        return result


class JudgementStatus(StrEnum):
    ENTAILED = "entailed"
    CONTRADICTED = "contradicted"
    BOTH = "both"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    INCONSISTENT_RELEASE = "inconsistent_release"
    BUDGET_EXCEEDED = "budget_exceeded"
    ERROR = "error"


SINGLE_PROOF_STATUSES = frozenset(
    {JudgementStatus.ENTAILED, JudgementStatus.CONTRADICTED}
)
NO_PROOF_STATUSES = frozenset(JudgementStatus) - SINGLE_PROOF_STATUSES - {
    JudgementStatus.BOTH
}


@dataclass(frozen=True, slots=True)
class Judgement:
    status: JudgementStatus
    query_id: str
    release_digest: str
    conclusion_claim_ids: tuple[str, ...] = ()
    proof_root_node_ids: tuple[str, ...] = ()
    reason_code: str | None = None

    def validate(self) -> None:
        if not isinstance(self.status, JudgementStatus):
            raise JudgementValidationError("status is not a recognised judgement family")
        if not valid_identifier(self.query_id):
            raise JudgementValidationError("query_id is not a stable identifier")
        if not valid_digest(self.release_digest):
            raise JudgementValidationError("release_digest is not lowercase SHA-256")
        if any(not valid_identifier(value) for value in self.conclusion_claim_ids):
            raise JudgementValidationError("conclusion claim ID is invalid")
        if any(not valid_identifier(value) for value in self.proof_root_node_ids):
            raise JudgementValidationError("proof root node ID is invalid")

        if self.status in SINGLE_PROOF_STATUSES:
            expected = 1
        elif self.status is JudgementStatus.BOTH:
            expected = 2
        else:
            expected = 0

        if len(self.conclusion_claim_ids) != expected:
            raise JudgementValidationError(
                f"{self.status.value} requires {expected} conclusion claim(s)"
            )
        if len(self.proof_root_node_ids) != expected:
            raise JudgementValidationError(
                f"{self.status.value} requires {expected} proof root(s)"
            )
        if len(set(self.conclusion_claim_ids)) != len(self.conclusion_claim_ids):
            raise JudgementValidationError("conclusion claims must be distinct")
        if len(set(self.proof_root_node_ids)) != len(self.proof_root_node_ids):
            raise JudgementValidationError("proof roots must be distinct")
        if self.status in NO_PROOF_STATUSES:
            if self.reason_code is None or not valid_identifier(self.reason_code):
                raise JudgementValidationError(
                    f"{self.status.value} requires a stable reason_code"
                )
        elif self.reason_code is not None:
            raise JudgementValidationError(
                f"{self.status.value} cannot carry a reason_code"
            )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "conclusion_claim_ids": list(self.conclusion_claim_ids),
            "proof_root_node_ids": list(self.proof_root_node_ids),
            "query_id": self.query_id,
            "reason_code": self.reason_code,
            "release_digest": self.release_digest,
            "status": self.status.value,
        }


class ProofNodeKind(StrEnum):
    ASSERTION = "assertion"
    RULE = "rule"


@dataclass(frozen=True, slots=True)
class ProofNode:
    id: str
    kind: ProofNodeKind
    claim_id: str
    rule_id: str | None = None
    premise_node_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "claim_id": self.claim_id,
            "id": self.id,
            "kind": self.kind.value,
            "premise_node_ids": list(self.premise_node_ids),
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True, slots=True)
class Proof:
    release_digest: str
    root_node_ids: tuple[str, ...]
    nodes: tuple[ProofNode, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "release_digest": self.release_digest,
            "root_node_ids": list(self.root_node_ids),
        }


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    claim_id: str
    support_id: str
    source_id: str
    path: str
    start: int
    end: int
    span_sha256: str
    quote_base64: str
    quote_text: str | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "claim_id": self.claim_id,
            "end": self.end,
            "path": self.path,
            "quote_base64": self.quote_base64,
            "quote_text": self.quote_text,
            "source_id": self.source_id,
            "span_sha256": self.span_sha256,
            "start": self.start,
            "support_id": self.support_id,
        }


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    release_digest: str
    proof_digest: str
    items: tuple[EvidenceItem, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "items": [item.to_dict() for item in self.items],
            "proof_digest": self.proof_digest,
            "release_digest": self.release_digest,
        }
