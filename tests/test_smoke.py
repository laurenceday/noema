"""Smoke tests for the selected IANA and OWL 2 RL scaffold."""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
UV = shutil.which("uv")

sys.path.insert(0, str(SRC))
import noema  # noqa: E402


def run_pinned_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run a smoke assertion inside the locked project environment."""
    if UV is None:
        raise AssertionError("uv is required to run the pinned backend smoke tests")
    return subprocess.run(
        [UV, "run", "--offline", "python", "-c", code],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class PackageSmokeTests(unittest.TestCase):
    def test_package_imports(self) -> None:
        self.assertEqual(noema.__version__, "0.1.0")

    def test_cli_help(self) -> None:
        self.assertIsNotNone(UV, "uv is required to run the pinned CLI")
        result = subprocess.run(
            [UV, "run", "--offline", "python", "-m", "noema", "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("proof-carrying KRR releases", result.stdout)


class BackendSmokeTests(unittest.TestCase):
    def test_backend_versions_are_pinned(self) -> None:
        result = run_pinned_python(
            """
from importlib.metadata import version

assert version("rdflib") == "7.6.0"
assert version("owlrl") == "7.6.2"
assert version("pyshacl") == "0.40.1"
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_owl_rl_materialises_an_inverse_property(self) -> None:
        result = run_pinned_python(
            """
from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import Graph, Namespace, OWL

ex = Namespace("https://example.test/noema/")
graph = Graph()
graph.add((ex.usesRepresentationSyntax, OWL.inverseOf, ex.syntaxUsedBy))
graph.add((ex.problemJson, ex.usesRepresentationSyntax, ex.jsonSyntax))
DeductiveClosure(
    OWLRL_Semantics,
    axiomatic_triples=False,
    datatype_axioms=False,
).expand(graph)
assert (ex.jsonSyntax, ex.syntaxUsedBy, ex.problemJson) in graph
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shacl_executes_for_valid_and_invalid_graphs(self) -> None:
        result = run_pinned_python(
            '''
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, RDF

ex = Namespace("https://example.test/noema/")
shape_graph = Graph().parse(
    data="""
        @prefix ex: <https://example.test/noema/> .
        @prefix sh: <http://www.w3.org/ns/shacl#> .

        ex:MediaTypeShape a sh:NodeShape ;
            sh:targetClass ex:RegisteredMediaType ;
            sh:property [
                sh:path ex:mediaTypeName ;
                sh:minCount 1 ;
                sh:maxCount 1
            ] .
    """,
    format="turtle",
)
valid_graph = Graph()
valid_graph.add((ex.problemJson, RDF.type, ex.RegisteredMediaType))
valid_graph.add(
    (ex.problemJson, ex.mediaTypeName, Literal("application/problem+json"))
)
invalid_graph = Graph()
invalid_graph.add((ex.problemJson, RDF.type, ex.RegisteredMediaType))
valid_conforms, _, _ = validate(
    data_graph=valid_graph,
    shacl_graph=shape_graph,
    inference="none",
)
invalid_conforms, _, _ = validate(
    data_graph=invalid_graph,
    shacl_graph=shape_graph,
    inference="none",
)
assert valid_conforms
assert not invalid_conforms
'''
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
