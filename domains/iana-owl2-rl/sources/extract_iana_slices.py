#!/usr/bin/env python3
"""Rebuild the small JSON views from the byte-pinned official IANA CSVs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APPLICATION_CSV = ROOT / "iana-application-2026-08-14.csv"
SUFFIX_CSV = ROOT / "iana-structured-syntax-suffix-2026-06-25.csv"
APPLICATION_SHA256 = "e8ac01c61f0741fe0b7dcfc96c1276390c41410f66588adf8bb1a450398031b0"
SUFFIX_SHA256 = "8f67c993b42ca7027dbcf108d831a8b38d38485c941efd72c8099585420547bf"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _references(value: str) -> list[str]:
    return re.findall(r"\[([^\]]+)\]", value)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_slices() -> dict[str, object]:
    if _digest(APPLICATION_CSV) != APPLICATION_SHA256:
        raise ValueError("application registry digest changed")
    if _digest(SUFFIX_CSV) != SUFFIX_SHA256:
        raise ValueError("structured-suffix registry digest changed")

    application_by_template = {
        row["Template"]: row for row in _rows(APPLICATION_CSV)
    }
    selected_templates = ("application/json", "application/problem+json")
    media = {
        "schema": "noema.iana.media-types.slice/v1",
        "generated_from": {
            "path": APPLICATION_CSV.name,
            "url": "https://www.iana.org/assignments/media-types/application.csv",
            "registry_id": "media-types/application",
            "registry_updated": "2026-08-14",
            "retrieved_at": "2026-08-17",
            "sha256": APPLICATION_SHA256,
            "selectors": list(selected_templates),
        },
        "license": {
            "id": "CC0-1.0",
            "url": "https://www.iana.org/help/licensing-terms",
        },
        "records": [
            {
                "name": application_by_template[template]["Name"],
                "template": template,
                "references": _references(
                    application_by_template[template]["Reference"]
                ),
            }
            for template in selected_templates
        ],
    }

    suffix_row = next(
        row for row in _rows(SUFFIX_CSV) if row["+suffix"] == "+json"
    )
    suffix = {
        "schema": "noema.iana.structured-suffix.slice/v1",
        "generated_from": {
            "path": SUFFIX_CSV.name,
            "url": (
                "https://www.iana.org/assignments/media-type-structured-suffix/"
                "structured-syntax-suffix.csv"
            ),
            "registry_id": "media-type-structured-suffix",
            "registry_updated": "2026-06-25",
            "retrieved_at": "2026-08-17",
            "sha256": SUFFIX_SHA256,
            "selector": "+json",
        },
        "license": {
            "id": "CC0-1.0",
            "url": "https://www.iana.org/help/licensing-terms",
        },
        "record": {
            "name": suffix_row["Name"],
            "suffix": suffix_row["+suffix"],
            "references": _references(suffix_row["References"]),
            "encoding": suffix_row["Encoding Considerations"],
            "registered": suffix_row["Registration Date"],
        },
    }
    return {"media": media, "suffix": suffix}


def _encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    slices = build_slices()
    targets = {
        ROOT / "iana-media-types-2026-08-14.json": slices["media"],
        ROOT / "iana-structured-suffix-2026-06-25.json": slices["suffix"],
    }
    if args.check:
        changed = [
            path.name
            for path, value in targets.items()
            if path.read_bytes() != _encoded(value)
        ]
        if changed:
            raise SystemExit("generated slice differs: " + ", ".join(changed))
        return 0
    for path, value in targets.items():
        print(f"# {path.name}")
        print(_encoded(value).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
