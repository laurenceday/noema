"""Build and validate deterministic Noema release manifests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath

from noema.canonical import JSONValue, digest_bytes, digest_domain_json, load_json_file
from noema.errors import CanonicalizationError, ReleaseValidationError
from noema.model import (
    BackendDeclaration,
    ClaimSupport,
    FormalClaim,
    GroundRule,
    Release,
    SourceRecord,
    SourceSpan,
    valid_digest,
    valid_identifier,
)


RELEASE_HASH_DOMAIN = "noema:release:v1"
MAX_EXPRESSION_BYTES = 16_384


def _fail(message: str) -> ReleaseValidationError:
    return ReleaseValidationError(message)


def _object(value: object, keys: set[str], location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _fail(f"{location} must be an object")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise _fail(f"{location} fields differ; missing={missing}, unknown={unknown}")
    if any(not isinstance(key, str) for key in value):
        raise _fail(f"{location} has a non-string field name")
    return value


def _array(value: object, location: str) -> list[object]:
    if not isinstance(value, list):
        raise _fail(f"{location} must be an array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(f"{location} must be a non-empty string")
    return value


def _integer(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{location} must be an integer")
    return value


def _boolean(value: object, location: str) -> bool:
    if not isinstance(value, bool):
        raise _fail(f"{location} must be a Boolean")
    return value


def _identifier(value: object, location: str) -> str:
    identifier = _string(value, location)
    if not valid_identifier(identifier):
        raise _fail(f"{location} is not a stable identifier")
    return identifier


def _digest(value: object, location: str) -> str:
    digest = _string(value, location)
    if not valid_digest(digest):
        raise _fail(f"{location} is not lowercase SHA-256")
    return digest


def _validate_relative_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise _fail("source path must use portable forward slashes")
    path = PurePosixPath(value)
    if path.is_absolute() or value != str(path):
        raise _fail(f"source path is not a canonical relative path: {value!r}")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise _fail(f"source path escapes or is empty: {value!r}")
    return path


def _source_file(root: Path, relative: str) -> Path:
    posix_path = _validate_relative_path(relative)
    root = root.resolve()
    candidate = root.joinpath(*posix_path.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise _fail(f"source path is missing or escapes its release: {relative!r}") from exc
    if not resolved.is_file():
        raise _fail(f"source path is not a regular file: {relative!r}")
    return resolved


def _normalise(release: Release) -> Release:
    return replace(
        release,
        sources=tuple(sorted(release.sources, key=lambda value: value.id)),
        claims=tuple(sorted(release.claims, key=lambda value: value.id)),
        rules=tuple(sorted(release.rules, key=lambda value: value.id)),
        claim_maps=tuple(
            sorted(
                (
                    replace(
                        mapping,
                        spans=tuple(
                            sorted(
                                mapping.spans,
                                key=lambda span: (
                                    span.source_id,
                                    span.start,
                                    span.end,
                                    span.sha256,
                                ),
                            )
                        ),
                    )
                    for mapping in release.claim_maps
                ),
                key=lambda value: (value.claim_id, value.support_id),
            )
        ),
    )


def _assert_unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise _fail(f"duplicate {name} identifier")


def _validate_structure(release: Release, source_root: Path | None) -> None:
    if (
        isinstance(release.format_version, bool)
        or not isinstance(release.format_version, int)
        or release.format_version != 1
    ):
        raise _fail("unsupported release format_version")
    if not valid_identifier(release.release_id):
        raise _fail("release_id is not a stable identifier")
    if not valid_identifier(release.backend.id):
        raise _fail("backend.id is not a stable identifier")
    if (
        not isinstance(release.backend.version, str)
        or not release.backend.version
        or not isinstance(release.backend.semantic_profile, str)
        or not release.backend.semantic_profile
    ):
        raise _fail("backend version and semantic profile must be non-empty")
    if (
        isinstance(release.backend.max_proof_nodes, bool)
        or not isinstance(release.backend.max_proof_nodes, int)
        or not 1 <= release.backend.max_proof_nodes <= 100_000
    ):
        raise _fail("backend.max_proof_nodes is outside 1..100000")
    if (
        isinstance(release.backend.max_proof_depth, bool)
        or not isinstance(release.backend.max_proof_depth, int)
        or not 1
        <= release.backend.max_proof_depth
        <= min(release.backend.max_proof_nodes, 256)
    ):
        raise _fail("backend.max_proof_depth is outside its valid range")
    if not release.sources:
        raise _fail("release must pin at least one source")
    if not release.claims:
        raise _fail("release must contain at least one formal claim")

    source_ids = [source.id for source in release.sources]
    claim_ids = [claim.id for claim in release.claims]
    rule_ids = [rule.id for rule in release.rules]
    support_ids = [mapping.support_id for mapping in release.claim_maps]
    _assert_unique(source_ids, "source")
    _assert_unique(claim_ids, "claim")
    _assert_unique(rule_ids, "rule")
    _assert_unique(support_ids, "support")

    source_by_id = {source.id: source for source in release.sources}
    claim_by_id = {claim.id: claim for claim in release.claims}
    for source in release.sources:
        if not valid_identifier(source.id):
            raise _fail("source ID is invalid")
        if not isinstance(source.path, str):
            raise _fail(f"source {source.id!r} path is not a string")
        _validate_relative_path(source.path)
        if (
            not isinstance(source.media_type, str)
            or not source.media_type
            or not isinstance(source.license_id, str)
            or not source.license_id
        ):
            raise _fail(f"source {source.id!r} lacks media type or licence")
        if not valid_digest(source.sha256):
            raise _fail(f"source {source.id!r} has an invalid digest")
        if (
            isinstance(source.byte_length, bool)
            or not isinstance(source.byte_length, int)
            or source.byte_length < 0
        ):
            raise _fail(f"source {source.id!r} has an invalid byte length")

        if source_root is not None:
            source_bytes = _source_file(source_root, source.path).read_bytes()
            if len(source_bytes) != source.byte_length:
                raise _fail(f"source {source.id!r} byte length changed")
            if digest_bytes(source_bytes) != source.sha256:
                raise _fail(f"source {source.id!r} digest changed")

    for claim in release.claims:
        if not valid_identifier(claim.id):
            raise _fail("claim ID is invalid")
        if not isinstance(claim.expression, str) or not claim.expression:
            raise _fail(f"claim {claim.id!r} has an empty expression")
        if len(claim.expression.encode("utf-8")) > MAX_EXPRESSION_BYTES:
            raise _fail(f"claim {claim.id!r} expression is too large")
        if not isinstance(claim.asserted, bool):
            raise _fail(f"claim {claim.id!r} asserted flag is not Boolean")

    for rule in release.rules:
        if not valid_identifier(rule.id):
            raise _fail("rule ID is invalid")
        if not rule.premise_claim_ids:
            raise _fail(f"ground rule {rule.id!r} has no premises")
        if any(not valid_identifier(value) for value in rule.premise_claim_ids):
            raise _fail(f"ground rule {rule.id!r} has an invalid premise ID")
        if len(rule.premise_claim_ids) != len(set(rule.premise_claim_ids)):
            raise _fail(f"ground rule {rule.id!r} repeats a premise")
        for premise in rule.premise_claim_ids:
            if premise not in claim_by_id:
                raise _fail(f"ground rule {rule.id!r} has a dangling premise")
        if not valid_identifier(rule.conclusion_claim_id):
            raise _fail(f"ground rule {rule.id!r} has an invalid conclusion ID")
        if rule.conclusion_claim_id not in claim_by_id:
            raise _fail(f"ground rule {rule.id!r} has a dangling conclusion")

    for mapping in release.claim_maps:
        if not valid_identifier(mapping.support_id):
            raise _fail("support ID is invalid")
        if not valid_identifier(mapping.claim_id):
            raise _fail(f"support {mapping.support_id!r} has an invalid claim ID")
        if mapping.claim_id not in claim_by_id:
            raise _fail(f"support {mapping.support_id!r} has a dangling claim")
        if not mapping.spans:
            raise _fail(f"support {mapping.support_id!r} has no source spans")
        span_keys = [
            (span.source_id, span.start, span.end, span.sha256)
            for span in mapping.spans
        ]
        if len(span_keys) != len(set(span_keys)):
            raise _fail(f"support {mapping.support_id!r} repeats a source span")
        for span in mapping.spans:
            if not valid_identifier(span.source_id):
                raise _fail(f"support {mapping.support_id!r} has an invalid source ID")
            source = source_by_id.get(span.source_id)
            if source is None:
                raise _fail(f"support {mapping.support_id!r} has a dangling source")
            if (
                isinstance(span.start, bool)
                or isinstance(span.end, bool)
                or not isinstance(span.start, int)
                or not isinstance(span.end, int)
                or span.start < 0
                or span.end <= span.start
                or span.end > source.byte_length
            ):
                raise _fail(f"support {mapping.support_id!r} has invalid byte bounds")
            if not valid_digest(span.sha256):
                raise _fail(f"support {mapping.support_id!r} has an invalid span digest")
            if source_root is not None:
                source_bytes = _source_file(source_root, source.path).read_bytes()
                if digest_bytes(source_bytes[span.start : span.end]) != span.sha256:
                    raise _fail(f"support {mapping.support_id!r} span digest changed")


def seal_release(release: Release, *, source_root: Path | None = None) -> Release:
    """Normalise, validate, and hash a release under the v1 release domain."""
    normalised = _normalise(replace(release, digest=""))
    _validate_structure(normalised, source_root)
    return replace(
        normalised,
        digest=digest_domain_json(RELEASE_HASH_DOMAIN, normalised.payload_dict()),
    )


def validate_release(
    release: Release,
    *,
    source_root: Path | None = None,
    expected_digest: str | None = None,
) -> None:
    """Recompute release integrity and optionally enforce a trusted digest."""
    if _normalise(release) != release:
        raise _fail("release collections are not in canonical order")
    _validate_structure(release, source_root)
    local_digest = digest_domain_json(RELEASE_HASH_DOMAIN, release.payload_dict())
    if not valid_digest(release.digest) or local_digest != release.digest:
        raise _fail("recorded release digest does not match local release content")
    if expected_digest is not None:
        if not valid_digest(expected_digest):
            raise _fail("trusted release digest is malformed")
        if local_digest != expected_digest:
            raise _fail("local release does not match the trusted release digest")


def build_release(manifest_path: Path) -> Release:
    """Build a sealed release from a strict manifest and pinned local sources."""
    try:
        raw = load_json_file(manifest_path)
    except CanonicalizationError as exc:
        raise _fail(str(exc)) from exc
    root = _object(
        raw,
        {
            "backend",
            "claim_maps",
            "claims",
            "format_version",
            "release_id",
            "rules",
            "sources",
        },
        "release",
    )
    source_root = manifest_path.parent.resolve()

    backend_raw = _object(
        root["backend"],
        {
            "id",
            "max_proof_depth",
            "max_proof_nodes",
            "semantic_profile",
            "version",
        },
        "backend",
    )
    backend = BackendDeclaration(
        id=_identifier(backend_raw["id"], "backend.id"),
        version=_string(backend_raw["version"], "backend.version"),
        semantic_profile=_string(
            backend_raw["semantic_profile"], "backend.semantic_profile"
        ),
        max_proof_nodes=_integer(
            backend_raw["max_proof_nodes"], "backend.max_proof_nodes"
        ),
        max_proof_depth=_integer(
            backend_raw["max_proof_depth"], "backend.max_proof_depth"
        ),
    )

    sources: list[SourceRecord] = []
    source_bytes_by_id: dict[str, bytes] = {}
    for index, value in enumerate(_array(root["sources"], "sources")):
        location = f"sources[{index}]"
        item = _object(
            value,
            {"id", "license", "media_type", "path", "sha256"},
            location,
        )
        source_id = _identifier(item["id"], f"{location}.id")
        relative_path = _string(item["path"], f"{location}.path")
        expected_sha256 = _digest(item["sha256"], f"{location}.sha256")
        try:
            source_bytes = _source_file(source_root, relative_path).read_bytes()
        except OSError as exc:
            raise _fail(f"cannot read source {source_id!r}: {exc}") from exc
        if digest_bytes(source_bytes) != expected_sha256:
            raise _fail(f"source {source_id!r} does not match its pinned digest")
        sources.append(
            SourceRecord(
                id=source_id,
                path=relative_path,
                media_type=_string(item["media_type"], f"{location}.media_type"),
                license_id=_string(item["license"], f"{location}.license"),
                sha256=expected_sha256,
                byte_length=len(source_bytes),
            )
        )
        source_bytes_by_id[source_id] = source_bytes

    claims: list[FormalClaim] = []
    for index, value in enumerate(_array(root["claims"], "claims")):
        location = f"claims[{index}]"
        item = _object(value, {"asserted", "expression", "id"}, location)
        claims.append(
            FormalClaim(
                id=_identifier(item["id"], f"{location}.id"),
                expression=_string(item["expression"], f"{location}.expression"),
                asserted=_boolean(item["asserted"], f"{location}.asserted"),
            )
        )

    rules: list[GroundRule] = []
    for index, value in enumerate(_array(root["rules"], "rules")):
        location = f"rules[{index}]"
        item = _object(value, {"conclusion", "id", "premises"}, location)
        rules.append(
            GroundRule(
                id=_identifier(item["id"], f"{location}.id"),
                premise_claim_ids=tuple(
                    _identifier(premise, f"{location}.premises[{premise_index}]")
                    for premise_index, premise in enumerate(
                        _array(item["premises"], f"{location}.premises")
                    )
                ),
                conclusion_claim_id=_identifier(
                    item["conclusion"], f"{location}.conclusion"
                ),
            )
        )

    claim_maps: list[ClaimSupport] = []
    for index, value in enumerate(_array(root["claim_maps"], "claim_maps")):
        location = f"claim_maps[{index}]"
        item = _object(value, {"claim_id", "spans", "support_id"}, location)
        spans: list[SourceSpan] = []
        for span_index, span_value in enumerate(
            _array(item["spans"], f"{location}.spans")
        ):
            span_location = f"{location}.spans[{span_index}]"
            span_item = _object(
                span_value,
                {"end", "sha256", "source_id", "start"},
                span_location,
            )
            source_id = _identifier(
                span_item["source_id"], f"{span_location}.source_id"
            )
            start = _integer(span_item["start"], f"{span_location}.start")
            end = _integer(span_item["end"], f"{span_location}.end")
            span_sha256 = _digest(
                span_item["sha256"], f"{span_location}.sha256"
            )
            source_bytes = source_bytes_by_id.get(source_id)
            if source_bytes is None:
                raise _fail(f"{span_location} refers to an unknown source")
            if start < 0 or end <= start or end > len(source_bytes):
                raise _fail(f"{span_location} has invalid half-open byte bounds")
            if digest_bytes(source_bytes[start:end]) != span_sha256:
                raise _fail(f"{span_location} does not match its pinned bytes")
            spans.append(
                SourceSpan(
                    source_id=source_id,
                    start=start,
                    end=end,
                    sha256=span_sha256,
                )
            )
        claim_maps.append(
            ClaimSupport(
                claim_id=_identifier(item["claim_id"], f"{location}.claim_id"),
                support_id=_identifier(item["support_id"], f"{location}.support_id"),
                spans=tuple(spans),
            )
        )

    release = Release(
        format_version=_integer(root["format_version"], "format_version"),
        release_id=_identifier(root["release_id"], "release_id"),
        backend=backend,
        sources=tuple(sources),
        claims=tuple(claims),
        rules=tuple(rules),
        claim_maps=tuple(claim_maps),
        digest="",
    )
    sealed = seal_release(release, source_root=source_root)
    validate_release(sealed, source_root=source_root, expected_digest=sealed.digest)
    return sealed
