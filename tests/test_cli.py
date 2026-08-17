"""CLI and independently sealed answer-certificate tests."""

from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from noema.answer import ANSWER_HASH_DOMAIN, answer_question
from noema.canonical import canonical_bytes, digest_domain_json
from noema.cli import main


DOMAIN = ROOT / "domains" / "iana-owl2-rl"
DEMO = (
    "Is application/problem+json a registered media type whose representation "
    "follows JSON syntax?"
)


def _run_cli(arguments: list[str], stdin: str = "") -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(stdin)),
        patch.object(socket, "socket", side_effect=AssertionError("network")),
        patch.object(socket, "getaddrinfo", side_effect=AssertionError("dns")),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        code = main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


def _reseal(document: dict[str, object]) -> None:
    payload = {key: value for key, value in document.items() if key != "answer_digest"}
    document["answer_digest"] = digest_domain_json(ANSWER_HASH_DOMAIN, payload)


def _write_document(path: Path, document: dict[str, object]) -> None:
    path.write_bytes(canonical_bytes(document) + b"\n")


class CommandTests(unittest.TestCase):
    def test_build_validates_anchored_configuration_without_writing(self) -> None:
        manifest_before = (DOMAIN / "release.json").read_bytes()
        code, stdout, stderr = _run_cli(["build", str(DOMAIN)])
        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report["eval_cases"], 6)
        self.assertEqual(report["question_templates"], 4)
        self.assertEqual((DOMAIN / "release.json").read_bytes(), manifest_before)

    def test_ask_reads_question_from_stdin_and_writes_canonical_answer(self) -> None:
        transient = (
            "  IS   APPLICATION/PROBLEM+JSON A REGISTERED MEDIA TYPE WHOSE "
            "REPRESENTATION FOLLOWS JSON SYNTAX?  "
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "answer.json"
            code, stdout, stderr = _run_cli(
                ["ask", str(DOMAIN), "--stdin", "--out", str(output)],
                transient + "\n",
            )
            data = output.read_bytes()
        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            stdout,
            "Yes. Every required claim is entailed by the pinned release.\n",
        )
        self.assertTrue(data.endswith(b"\n"))
        self.assertNotIn(transient.encode(), data)
        self.assertNotIn(transient, stdout + stderr)

    def test_verify_recomputes_both_results_with_network_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "answer.json"
            ask_code, _, ask_error = _run_cli(
                ["ask", str(DOMAIN), "--stdin", "--out", str(output)],
                DEMO + "\n",
            )
            code, stdout, stderr = _run_cli(
                ["verify", str(DOMAIN), str(output)]
            )
        self.assertEqual(ask_code, 0, ask_error)
        self.assertEqual(code, 0, stderr)
        receipt = json.loads(stdout)
        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["result_count"], 2)

    def test_probe_runs_all_pinned_cases_with_network_disabled(self) -> None:
        code, stdout, stderr = _run_cli(["probe", str(DOMAIN)])
        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)
        self.assertTrue(report["passed"])
        self.assertTrue(report["mutations"][0]["active_release_unchanged"])

    def test_positional_question_path_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "answer.json"
            code, stdout, stderr = _run_cli(
                ["ask", str(DOMAIN), DEMO, "--out", str(output)]
            )
        self.assertEqual(code, 0, stderr)
        self.assertIn("Yes.", stdout)

    def test_existing_output_is_never_overwritten_and_stdin_is_not_echoed(self) -> None:
        canary = "PRIVATE-CANARY-QUESTION"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "answer.json"
            output.write_bytes(b"keep me")
            code, stdout, stderr = _run_cli(
                ["ask", str(DOMAIN), "--stdin", "--out", str(output)],
                f"Is {canary} safe to process?\n",
            )
            retained = output.read_bytes()
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(retained, b"keep me")
        self.assertNotIn(canary, stdout + stderr)

    def test_demo_script_runs_all_four_locked_offline_commands(self) -> None:
        completed = subprocess.run(
            [str(ROOT / "scripts" / "demo")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("noema build", completed.stdout)
        self.assertIn("noema ask", completed.stdout)
        self.assertIn("noema verify", completed.stdout)
        self.assertIn("noema probe", completed.stdout)


class AnswerTamperingTests(unittest.TestCase):
    def _document(self) -> dict[str, object]:
        return answer_question(DOMAIN, DEMO).to_dict()

    def _verify_document(self, document: dict[str, object]) -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "answer.json"
            _write_document(path, document)
            return _run_cli(["verify", str(DOMAIN), str(path)])

    def test_changed_rendering_fails_even_after_identity_reseal(self) -> None:
        document = self._document()
        document["rendering"]["text"] = "Yes. Trust me."
        _reseal(document)
        code, _, stderr = self._verify_document(document)
        self.assertEqual(code, 1)
        self.assertIn("rendering differs", stderr)

    def test_changed_evidence_fails_even_after_identity_reseal(self) -> None:
        document = self._document()
        document["results"][0]["evidence"]["items"][0]["quote_text"] = "forged"
        _reseal(document)
        code, _, stderr = self._verify_document(document)
        self.assertEqual(code, 1)
        self.assertIn("evidence differs", stderr)

    def test_nested_release_digest_fails_even_after_identity_reseal(self) -> None:
        document = self._document()
        document["results"][0]["evidence"]["release_digest"] = "0" * 64
        _reseal(document)
        code, _, stderr = self._verify_document(document)
        self.assertEqual(code, 1)
        self.assertIn("evidence differs", stderr)

    def test_top_release_digest_never_becomes_a_trust_anchor(self) -> None:
        document = self._document()
        document["release_digest"] = "0" * 64
        _reseal(document)
        code, _, stderr = self._verify_document(document)
        self.assertEqual(code, 1)
        self.assertIn("different release", stderr)

    def test_removed_proof_node_fails_after_identity_reseal(self) -> None:
        document = self._document()
        document["results"][0]["proof"]["nodes"].pop(0)
        _reseal(document)
        code, _, stderr = self._verify_document(document)
        self.assertEqual(code, 1)
        self.assertIn("decision differs", stderr)

    def test_reordered_conjuncts_fail_after_identity_reseal(self) -> None:
        document = self._document()
        document["results"].reverse()
        _reseal(document)
        code, _, stderr = self._verify_document(document)
        self.assertEqual(code, 1)
        self.assertIn("all-query plan", stderr)

    def test_answer_extensions_cannot_retain_user_text(self) -> None:
        document = self._document()
        document["question_text"] = "PRIVATE-CANARY-QUESTION"
        _reseal(document)
        code, stdout, stderr = self._verify_document(document)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertNotIn("PRIVATE-CANARY-QUESTION", stderr)
        self.assertIn("fields differ", stderr)


if __name__ == "__main__":
    unittest.main()
