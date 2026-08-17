"""Project verified proof leaves to exact, pinned source evidence."""

from __future__ import annotations

import base64
from collections import defaultdict
from pathlib import Path

from noema.canonical import digest_bytes
from noema.errors import EvidenceProjectionError, ReleaseValidationError
from noema.model import (
    ClaimSupport,
    EvidenceItem,
    EvidencePacket,
    Judgement,
    Proof,
    Release,
)
from noema.proof import RuleReplayer, verify_proof
from noema.release import validate_release


def _fail(message: str) -> EvidenceProjectionError:
    return EvidenceProjectionError(message)


def _support_sort_key(mapping: ClaimSupport) -> tuple[object, ...]:
    span_key = tuple(
        (span.source_id, span.start, span.end, span.sha256) for span in mapping.spans
    )
    total_bytes = sum(span.end - span.start for span in mapping.spans)
    return (total_bytes, len(mapping.spans), span_key, mapping.support_id)


def _source_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = root.joinpath(*Path(relative).parts).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _fail(f"source path escaped release root: {relative!r}") from exc
    return candidate


def project_evidence(
    release: Release,
    judgement: Judgement,
    proof: Proof,
    *,
    source_root: Path,
    trusted_release_digest: str,
    replayer: RuleReplayer | None = None,
) -> EvidencePacket:
    """Verify a proof, then project only its reachable asserted leaves."""
    verification = verify_proof(
        release,
        judgement,
        proof,
        trusted_release_digest=trusted_release_digest,
        replayer=replayer,
    )
    try:
        validate_release(
            release,
            source_root=source_root,
            expected_digest=trusted_release_digest,
        )
    except ReleaseValidationError as exc:
        raise _fail(str(exc)) from exc

    node_by_id = {node.id: node for node in proof.nodes}
    source_by_id = {source.id: source for source in release.sources}
    supports_by_claim: dict[str, list[ClaimSupport]] = defaultdict(list)
    for mapping in release.claim_maps:
        supports_by_claim[mapping.claim_id].append(mapping)

    selected: list[ClaimSupport] = []
    for leaf_node_id in verification.asserted_leaf_node_ids:
        claim_id = node_by_id[leaf_node_id].claim_id
        alternatives = supports_by_claim.get(claim_id, [])
        if not alternatives:
            raise _fail(f"verified leaf {claim_id!r} has no admissible evidence map")
        selected.append(min(alternatives, key=_support_sort_key))

    source_cache: dict[str, bytes] = {}
    items: list[EvidenceItem] = []
    for mapping in selected:
        for span in mapping.spans:
            source = source_by_id[span.source_id]
            source_bytes = source_cache.get(source.id)
            if source_bytes is None:
                try:
                    source_bytes = _source_path(source_root, source.path).read_bytes()
                except OSError as exc:
                    raise _fail(f"cannot read evidence source {source.id!r}: {exc}") from exc
                if len(source_bytes) != source.byte_length:
                    raise _fail(f"evidence source {source.id!r} byte length changed")
                if digest_bytes(source_bytes) != source.sha256:
                    raise _fail(f"evidence source {source.id!r} digest changed")
                source_cache[source.id] = source_bytes
            quote = source_bytes[span.start : span.end]
            if digest_bytes(quote) != span.sha256:
                raise _fail(f"evidence span for {mapping.claim_id!r} digest changed")
            try:
                quote_text: str | None = quote.decode("utf-8")
            except UnicodeDecodeError:
                quote_text = None
            items.append(
                EvidenceItem(
                    claim_id=mapping.claim_id,
                    support_id=mapping.support_id,
                    source_id=source.id,
                    path=source.path,
                    start=span.start,
                    end=span.end,
                    span_sha256=span.sha256,
                    quote_base64=base64.b64encode(quote).decode("ascii"),
                    quote_text=quote_text,
                )
            )

    items.sort(
        key=lambda item: (
            item.source_id,
            item.start,
            item.end,
            item.claim_id,
            item.support_id,
        )
    )
    return EvidencePacket(
        release_digest=trusted_release_digest,
        proof_digest=verification.proof_digest,
        items=tuple(items),
    )
