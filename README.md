# Noema

Noema is a proof-carrying release system for formal knowledge bases. This
prototype represents a byte-pinned part of the IANA media-type registries in a
small OWL 2 RL profile.

Aleph-prime validates the release, maps a finite set of questions to declared
queries, and returns formal judgements. Lemma-prime projects the proof leaves
back to exact source-byte spans. Null-prime runs public boundary cases and a
simulation-only mutation without changing or promoting the active release.

No language model participates in mapping, reasoning, proof replay, evidence
selection, or rendering. RDFLib 7.6.0, OWL-RL 7.6.2, and pySHACL 0.40.1 parse,
materialise, and validate RDF. The Noema adapter supplies the separate
replayable proof contract for two grounded rule families. This is a bounded
profile, not an implementation of full OWL 2 RL.

## Run the demonstration

Install the exact Python 3.14.6 environment with uv 0.12.5, then run the four
commands offline:

```sh
uv sync --locked
scripts/demo
```

`scripts/demo` invokes these commands:

```sh
uv run --offline --locked noema build domains/iana-owl2-rl
uv run --offline --locked noema ask domains/iana-owl2-rl --stdin --out answer.json
uv run --offline --locked noema verify domains/iana-owl2-rl answer.json
uv run --offline --locked noema probe domains/iana-owl2-rl
```

The `ask` command waits for a question on standard input. Paste this public demo
question, then send end-of-file:

```text
Is application/problem+json a registered media type whose representation follows JSON syntax?
```

Using `--stdin` keeps a transient question out of process arguments and shell
history. A positional question is also accepted, but has weaker local privacy.
Neither path stores the raw question in the answer certificate.

The deterministic output is:

```text
{"backend_id":"backend:iana-owl2-rl-fragment","eval_cases":6,"mutation_targets":1,"question_templates":4,"release_digest":"7eaf104e41f2fdf0d1a1dc005f5c881fd813bbd2055d7425acae9d4d22fd207e","schema":"noema.build-report/v1","valid":true}
Yes. Every required claim is entailed by the pinned release.
{"answer_digest":"6643962289f1253e0038bad15ce204ac2b8651abb1bf7cf2cefffc390c351390","release_digest":"7eaf104e41f2fdf0d1a1dc005f5c881fd813bbd2055d7425acae9d4d22fd207e","result_count":2,"valid":true}
```

The probe's final record has `"passed":true`. Its six public cases cover
entailed, contradicted, unknown, ambiguous, and unsupported answers. Its one
mutation removes `claim:problem-has-json-suffix` from an in-memory theory. The
result changes from `entailed` to `unknown`, the old certificate fails against
the hypothetical digest, and hashes of the manifest and every pinned source
remain unchanged.

## What the certificate proves

The demo question is a conjunction. Its mapping names the `all` operator and
two sorted queries:

```text
query:problem-json-syntax
query:problem-registered
```

The answer carries a separate judgement, proof DAG, and evidence packet for
each query. `noema verify` uses the release digest compiled into the selected
adapter. It reloads the pinned question catalogue, checks the formal route,
reruns both decisions, replays each proof, projects the source spans again,
and compares the result order, evidence, aggregate status, terminal text, and
answer checksum.

The checksum identifies an answer; it is not a trust anchor. Verification
attests that the pinned public template and entity binding select the recorded
formal plan. It cannot attest which transient sentence a user typed, because
that sentence and its hash are deliberately absent from the certificate.
Public questions in `evals.json` are test fixtures and are never extended with
runtime input.

Terminal prose is selected from fixed status messages. RDF labels and evidence
quotes remain inert JSON data and cannot alter the rendered answer.

## Check the release

Run the complete locked test suite and the source-slice replay:

```sh
uv run --offline --locked python -m unittest discover -s tests -v
uv run --offline --locked python domains/iana-owl2-rl/sources/extract_iana_slices.py --check
```

The formal profile, vendored-source provenance, and open-world limits are in
[`domains/iana-owl2-rl/README.md`](domains/iana-owl2-rl/README.md). The design
study and delivery contract are in [`docs/study.md`](docs/study.md) and
[`docs/runbook.md`](docs/runbook.md).
