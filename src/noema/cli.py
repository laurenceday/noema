"""Offline command line for Noema's proof-carrying IANA demonstration."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from noema import __version__
from noema.adapters.iana_owl2_rl import IanaOwl2RlAdapter
from noema.answer import answer_question, load_answer, verify_answer, write_answer
from noema.canonical import JSONValue, canonical_bytes
from noema.errors import NoemaError
from noema.probe import load_evaluation_suite, run_probe
from noema.query import MAX_QUESTION_BYTES, load_question_catalogue
from noema.release import build_release


def build_parser() -> argparse.ArgumentParser:
    """Build the four-command parser without performing domain work."""
    parser = argparse.ArgumentParser(
        prog="noema",
        description="Build and verify proof-carrying KRR releases.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="validate a pinned domain release")
    build.add_argument("domain", type=Path)

    ask = subparsers.add_parser("ask", help="map and answer one question")
    ask.add_argument("domain", type=Path)
    ask.add_argument("question", nargs="?")
    ask.add_argument(
        "--stdin",
        action="store_true",
        help="read the transient question from standard input",
    )
    ask.add_argument("--out", type=Path, required=True)

    verify = subparsers.add_parser(
        "verify",
        help="independently verify an answer certificate",
    )
    verify.add_argument("domain", type=Path)
    verify.add_argument("answer", type=Path)

    probe = subparsers.add_parser("probe", help="run pinned Null-prime probes")
    probe.add_argument("domain", type=Path)
    return parser


def _emit_json(value: JSONValue) -> None:
    print(canonical_bytes(value).decode("utf-8"))


def _build_report(domain: Path) -> dict[str, JSONValue]:
    adapter = IanaOwl2RlAdapter(domain)
    report = adapter.validate()
    if not report.valid:
        raise NoemaError("domain release validation failed")
    release = build_release(domain / "release.json")
    if release.digest != adapter.trusted_release_digest:
        raise NoemaError("domain release does not match the compiled trust anchor")
    catalogue = load_question_catalogue(domain / "questions.json", release)
    evaluations = load_evaluation_suite(domain / "evals.json", release)
    return {
        "backend_id": release.backend.id,
        "eval_cases": len(evaluations.cases),
        "mutation_targets": len(evaluations.mutation_targets),
        "question_templates": len(catalogue.templates),
        "release_digest": release.digest,
        "schema": "noema.build-report/v1",
        "valid": True,
    }


def _stdin_question() -> str:
    """Read a bounded question without copying it into argv or diagnostics."""
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    value = stream.read(MAX_QUESTION_BYTES + 1)
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return "\x00"
    else:
        text = value
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n"):
        return text[:-1]
    return text


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one offline command and return a stable process status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ask" and ((args.question is None) == (not args.stdin)):
        parser.error("ask requires exactly one of QUESTION or --stdin")
    try:
        if args.command == "build":
            _emit_json(_build_report(args.domain))
            return 0
        if args.command == "ask":
            question = _stdin_question() if args.stdin else args.question
            answer = answer_question(args.domain, question)
            write_answer(args.out, answer)
            print(answer.rendering.text)
            return 0
        if args.command == "verify":
            receipt = verify_answer(args.domain, load_answer(args.answer))
            _emit_json(receipt.to_dict())
            return 0
        if args.command == "probe":
            report = run_probe(args.domain)
            _emit_json(report)
            return 0 if report["passed"] is True else 1
    except NoemaError as exc:
        print(f"noema: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("noema: command failed", file=sys.stderr)
        return 1
    print("noema: unknown command", file=sys.stderr)
    return 1
