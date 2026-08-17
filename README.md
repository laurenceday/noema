# Noema

Noema is a proof-carrying release system for knowledge-representation and
reasoning backends. This prototype follows one subject and KRR pairing: the
IANA media-type registries represented in a constrained OWL 2 RL theory.

The first scaffold pins Python 3.14.6, uv 0.12.5, RDFLib 7.6.0, OWL-RL 7.6.2,
and pySHACL 0.40.1. That stack can parse RDF, materialise OWL 2 RL entailments,
and validate RDF graphs against SHACL shapes. It does **not** itself provide
Noema's replayable proof contract. The supported rule fragment and the
proof-producing adapter belong to the later adapter step.

## Local setup

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run noema --help
```

The test suite performs a real OWL 2 RL materialisation and a real SHACL
validation. Runtime reasoning is designed to use only pinned local release
inputs; network access is not part of the reasoning contract.

The prototype design is in [`docs/study.md`](docs/study.md), and the delivery
steps are in [`docs/runbook.md`](docs/runbook.md).
