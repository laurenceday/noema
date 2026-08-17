"""Strict canonical JSON and SHA-256 helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeAlias

from noema.errors import CanonicalizationError


JSONScalar: TypeAlias = None | bool | int | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def _reject_constant(value: str) -> None:
    raise CanonicalizationError(f"non-finite JSON number is forbidden: {value}")


def _object_without_duplicate_keys(
    pairs: list[tuple[str, JSONValue]],
) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalizationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json_bytes(data: bytes) -> JSONValue:
    """Parse UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""
    try:
        value = json.loads(
            data,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except CanonicalizationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalizationError(f"invalid UTF-8 JSON: {exc}") from exc
    validate_json_value(value)
    return value


def load_json_file(path: Path) -> JSONValue:
    """Read and strictly parse a JSON file."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CanonicalizationError(f"cannot read JSON file {path}: {exc}") from exc
    return load_json_bytes(data)


def validate_json_value(value: object, path: str = "$") -> None:
    """Validate the integer-only JSON subset used by release artefacts."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CanonicalizationError(f"invalid Unicode scalar at {path}") from exc
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise CanonicalizationError(f"floating-point JSON is forbidden at {path}")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"non-string object key at {path}")
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise CanonicalizationError(f"invalid Unicode key at {path}") from exc
            validate_json_value(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            validate_json_value(child, f"{path}[{index}]")
        return
    raise CanonicalizationError(
        f"unsupported canonical JSON value {type(value).__name__} at {path}"
    )


def canonical_bytes(value: JSONValue) -> bytes:
    """Encode a value with stable key order and no insignificant whitespace."""
    validate_json_value(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(f"cannot encode canonical JSON: {exc}") from exc
    return encoded.encode("utf-8")


def digest_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact bytes."""
    return hashlib.sha256(data).hexdigest()


def digest_json(value: JSONValue) -> str:
    """Return the SHA-256 digest of a canonical JSON value."""
    return digest_bytes(canonical_bytes(value))


def digest_domain_json(domain: str, value: JSONValue) -> str:
    """Hash canonical JSON under an explicit, NUL-terminated domain."""
    if not domain or "\x00" in domain or not domain.isascii():
        raise CanonicalizationError("hash domain must be non-empty ASCII without NUL")
    return digest_bytes(domain.encode("ascii") + b"\x00" + canonical_bytes(value))
