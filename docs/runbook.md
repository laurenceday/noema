# Noema prototype runbook

This runbook implements the proof-carrying backend-adapter design selected in the study. It deliberately stops before the first repository change so the user can choose the subject-matter expert and KRR pairing.

## Required user decision

Ask this question before Step 1:

> Which subject/KRR pairing should the basic Noema prototype implement?

Present exactly these choices:

1. **IANA media types + OWL 2 RL (Recommended).** An Internet media-type registration SME and a constrained RDF/OWL 2 RL release. This is the shortest test of the user's description-logic and semantic-network thesis, with official CC0 registry data and an explicit open-world boundary.
2. **SI metrology + typed Datalog.** A metrologist and a many-sorted Datalog release over SI dimensions and quantity kinds. This gives the clearest proof trees and a useful ambiguity case: equal dimensions do not establish equal quantity kinds.
3. **HTTP caching + Answer Set Programming.** An HTTP caching SME and an ASP release over a bounded part of RFC 9111. This exercises exceptions, temporal inputs, and closed-input reasoning, but it has the largest rule and explanation surface.

Record the answer in controller state before implementation:

```text
hexctl record prototype_choice '{"id":"iana-owl2-rl|si-typed-datalog|http-caching-asp","label":"<chosen label>"}'
```

The chosen receipt controls toolchain pins, adapter paths, fixture paths, demo queries, and evaluation counts. Do not mix features from the unchosen options into the prototype.

## Toolchain mapping after the decision

- `iana-owl2-rl`: use Python 3.14.6 for the release kernel. Select and pin one tested RDF/OWL validation and reasoning path during Step 1. If the chosen reasoner does not emit replayable proofs, constrain the supported OWL 2 RL fragment and add a proof-producing rule adapter; never claim full OWL 2 RL conformance without the W3C conformance evidence.
- `si-typed-datalog`: use Python 3.14.6 for the release kernel and Soufflé 2.5 for the backend if it installs and passes a local smoke test. Run deterministically with one worker on this ARM host. If Soufflé cannot be installed, stop instead of silently replacing the chosen KRR.
- `http-caching-asp`: use Python 3.14.6 for the release kernel and pin a clingo release only after a local compatibility smoke test. If no compatible clingo build is available, stop instead of replacing ASP with ad hoc Boolean code.

All options use standard-library `argparse`, `hashlib`, `json`, and `unittest` for the common kernel unless the selected adapter requires a pinned package. Runtime reasoning has no network access.

## Step 1: Scaffold the selected Noema release

**Goal.** Create the repository, toolchain pins, documentation, CI stub, and package skeleton for only the selected subject/KRR pairing.
**Entry.** Controller phase `implement`, a recorded `prototype_choice`, the empty generated workspace, no Git repository or remote, Git 2.50.1, and a GitHub CLI account that is not authenticated. Initialise local `main` with one empty baseline commit, then branch `step-1-scaffold-noema`.
**Exit.** The package imports, `python3 -m unittest discover -s tests -v` passes, the selected backend smoke test passes, and the tree contains committed copies of the linted study and runbook.
**Files.** `pyproject.toml`, a lock or backend-version manifest, `LICENSE` (Apache-2.0), `README.md`, `.gitignore`, `.github/workflows/test.yml`, `docs/study.md`, `docs/runbook.md`, `src/noema/__init__.py`, `src/noema/__main__.py`, `src/noema/cli.py`, `src/noema/adapters/__init__.py`, `domains/<selected>/README.md`, and `tests/test_smoke.py`.
**Tests.** Add at least 3 smoke tests: package import, CLI help, and selected backend version/execution. CI runs the same local test and backend smoke commands. It may remain unexecuted remotely until a target remote exists.

## Step 2: Implement the release, proof, and evidence kernel

**Goal.** Build deterministic release digests, typed judgement envelopes, replayable proof verification, and Lemma′ evidence projection without domain inference.
**Entry.** The green `step-1-scaffold-noema` commit and its exact pinned toolchain. Branch `step-2-release-proof-kernel` from Step 1.
**Exit.** A fixture release builds to a stable digest; a synthetic proof verifies; altered release digests, conclusions, premises, claim maps, source spans, and rule IDs fail closed; evidence projection contains only verified proof leaves. `python3 -m unittest discover -s tests -v` passes.
**Files.** `src/noema/model.py`, `src/noema/canonical.py`, `src/noema/release.py`, `src/noema/proof.py`, `src/noema/evidence.py`, `src/noema/errors.py`, `schemas/release.schema.json`, `schemas/judgement.schema.json`, `schemas/proof.schema.json`, `tests/fixtures/kernel/`, `tests/test_release.py`, `tests/test_proof.py`, and `tests/test_evidence.py`.
**Tests.** Add at least 15 deterministic tests covering identical-build digests, changed-input digests, release validation, every terminal judgement family, valid proof replay, missing and reordered premises, changed rule IDs, changed source spans, unmapped leaves, deterministic evidence selection, hostile source text as inert data, and no retention of user text.

## Step 3: Implement the selected KRR adapter and formal subject release

**Goal.** Turn the selected pinned corpus into a validated formal theory and return proof-bearing judgements through the common adapter contract.
**Entry.** The green `step-2-release-proof-kernel` commit. Branch `step-3-selected-krr-adapter` from Step 2.
**Exit.** `validate`, `decide`, `justify`, `verify`, and `capabilities` work for the selected backend. The release demonstrates a direct assertion, a multi-hop entailment, an explicit contradiction where expressible, a genuine unknown, an inconsistent or invalid release, and an unmapped-evidence failure. All source inputs are vendored or generated from a pinned snapshot with digests and licence metadata. The full test command passes with runtime networking disabled.
**Files.** One adapter at `src/noema/adapters/<selected>.py`; `domains/<selected>/release.json`; pinned source snapshots and licence notices under `domains/<selected>/sources/`; formal claims, rules, vocabulary, claim maps, queries, and expected judgements under `domains/<selected>/theory/`; `tests/test_adapter_<selected>.py`; and `tests/fixtures/<selected>/`. For IANA, use the two registry snapshots and RFC locators. For SI, use the bounded SI table slice and dimension rules. For HTTP, use the bounded RFC 9111 rule set and complete request/response fixtures.
**Tests.** Add at least 18 backend and subject tests. Include profile or syntax rejection, semantic-assumption checks, consistency/conflict handling, direct and multi-hop proofs, contradiction versus unknown, a changed-premise mutation, stale source digest rejection, missing source mapping, deterministic alternative-proof selection, and one backend-specific boundary from the study.

## Step 4: Demonstrate Aleph′, Null′, and Lemma′ end to end

**Goal.** Expose the selected release through deterministic question mapping, answer and evidence rendering, adversarial probes, and an independently verifiable demo.
**Entry.** The green `step-3-selected-krr-adapter` commit. Branch `step-4-noema-demo` from Step 3.
**Exit.** The four study commands run from a clean checkout: `noema build`, `noema ask`, `noema verify`, and `noema probe`. The selected demo question returns its specified judgement and proof; the ambiguity or unsupported question refuses before inference; the minimal mutation changes the expected result; a changed answer fails independent verification. `README.md` reproduces the commands and outputs without requiring an LLM.
**Files.** `src/noema/query.py`, `src/noema/answer.py`, `src/noema/probe.py`, `src/noema/render.py`, updates to `src/noema/cli.py`, `domains/<selected>/questions.json`, `domains/<selected>/evals.json`, `tests/test_query.py`, `tests/test_probe.py`, `tests/test_cli.py`, `scripts/demo`, and the completed `README.md`.
**Tests.** Add at least 15 tests for deterministic templates, entity ambiguity, unsupported symbols, out-of-profile requests, entailed/contradicted/unknown rendering, proof-to-evidence projection, hostile labels, mutation generation, evaluation coverage counts, answer tampering, release-digest mismatch, no-network execution, and all four CLI commands. Run `scripts/demo` after the full unit suite; both must exit zero.

## Delivery notes

- Each step is one stacked branch and one pull request after its audit and prose phases.
- The configured GitHub account and target remote must be repaired or supplied before the first push. Do not invent a repository or organisation.
- The Solidity security suite is waived for every step because this prototype contains no Solidity. Audit the actual boundaries instead: corpus ingestion, semantic assumptions, proof replay, untrusted text, source drift, resource limits, and privacy.
- Step 4 is the demonstration step. No later feature step is needed for the basic prototype.
