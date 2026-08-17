# Audit log

## Step 1, round 1 -- 2026-08-17

The recorded Solidity security suite is waived because this repository contains no Solidity. This round reviewed the full `main...6919c01db9d7ea7b3854850ee72895c67b674c96` diff against the Noema risk register.

Checks performed:

- Confirmed exact direct dependency versions and package hashes in `uv.lock`.
- Ran pip-audit 2.10.1 over all eight locked third-party packages; it reported no known vulnerabilities.
- Confirmed both GitHub Actions dependencies are pinned by commit and the workflow grants only read access to repository contents.
- Searched production code for network, dynamic evaluation, deserialisation, and shell execution paths. The scaffold contains none.
- Ran all 5 smoke tests through both the system-Python entry command and the locked offline environment.
- Exercised OWL-RL materialisation and both conforming and non-conforming SHACL inputs.
- Compiled `src/` and `tests/` without errors.

| id | severity | file | finding | status |
| --- | --- | --- | --- | --- |
| -- | -- | -- | No findings | closed |

Leads not pursued: source ingestion, proof replay, resource budgets, and hostile corpus handling are not present in the scaffold. They remain audit targets for the steps that add them.

## Step 2, round 1 -- 2026-08-17

This round reviewed the release, proof, and evidence kernel at `404b8954a2afa0b3eaf78fc4c6f77580a835c8d6`. The Solidity suite remains waived. The review covered the full Step 2 diff, strict parsing, release hashing, query and semantic bindings, adapter return values, proof replay, exact source projection, resource limits, hostile text, and error privacy.

Checks performed:

- Ran all 57 pre-fix tests through locked, offline uv.
- Ran pip-audit 2.10.1 over the eight locked third-party packages; it reported no known vulnerabilities.
- Compiled `src/` and `tests/` and searched production code for network, shell, dynamic evaluation, and unsafe deserialisation paths. None are present.
- Replayed query-transplant, truthy-adapter, exception-canary, and deeply nested JSON cases against the public API.
- Checked release, judgement, and proof schemas against their runtime parsers.
- Re-ran the mutation suite after each correction.

| id | severity | file | finding | resolution |
| --- | --- | --- | --- | --- |
| N-201 | high | `src/noema/proof.py`, `src/noema/release.py` | A valid proof could be relabelled with an undeclared query ID, and `contradicted` was not tied to a release-declared formal complement. | Added digest-bound query specifications with positive and complement claims; proof replay now requires the roots to answer that specification. |
| N-202 | medium | `src/noema/proof.py` | Adapter `supports` and `replay` results used truthiness, so strings such as `"false"` were accepted. | Require the exact Boolean value `True`; every other value fails closed. |
| N-203 | medium | `src/noema/proof.py` | Adapter exception text and exception context crossed the verifier boundary and could retain private or hostile data. | Replace adapter failures with fixed messages outside the exception context; regression tests check the message, cause, and context. |
| N-204 | medium | `src/noema/canonical.py` | Deep JSON escaped as a raw `RecursionError`, and the canonical input profile had no byte or nesting limit. | Added a 16 MiB limit, a depth limit of 128, explicit BOM rejection, and canonical errors for recursive input. |
| N-205 | medium | `src/noema/model.py`, `src/noema/release.py` | The release digest bound only an opaque semantic-profile string, not the open/closed-world, unique-name, negation, monotonicity, datatype, or inconsistency assumptions. | Added structured, mandatory semantic declarations to the backend contract and release schema; assumption changes now miss the trusted digest. |

All five findings were corrected on the stacked audit branch. Round 2 must verify the fixes and the expanded suite before closure.

## Step 2, round 2 -- 2026-08-17

Round 2 reviewed `a604c9d` and repeated the complete Step 2 audit after the fixes.

Checks performed:

- Ran all 68 tests with the system Python entry command and locked, offline uv; both runs passed.
- Replayed all four round-1 demonstrations. Query transplantation and non-Boolean adapter results were rejected, adapter exceptions retained no private canary or exception context, and deep JSON returned `CanonicalizationError`.
- Confirmed that changing a query signature or a structured semantic assumption misses the trusted release digest.
- Re-ran pip-audit 2.10.1 over all eight locked third-party packages; it reported no known vulnerabilities.
- Recompiled `src/` and `tests/`, checked the complete fixes diff, and repeated the production search for network, subprocess, dynamic evaluation, and unsafe deserialisation paths. None are present.

| id | severity | file | finding | status |
| --- | --- | --- | --- | --- |
| -- | -- | -- | No new findings | closed |

Round 2 closes cleanly. The exact-ground replayer remains a synthetic test calculus; the IANA OWL adapter and its separate semantic verifier belong to Step 3.

## Step 3, round 1 -- 2026-08-17

The recorded Solidity security suite remains waived. This round reviewed the full `17bcee7c51e2bec2c0aaf33fba6ce0665051400b...d706bbd17bb72840f757266fd5e00615e0db7bff` diff. The review covered the pinned IANA/RFC source release, the bounded OWL 2 RL adapter, proof production and replay, exact evidence projection, and the subject mutation fixtures.

Checks performed:

- Ran all 112 tests with locked, offline uv and with the runbook command inside the activated environment; both runs passed. The adapter subset contains 44 direct, multi-hop, contradiction, unknown, refusal, conflict, provenance, profile, and mutation cases.
- Ran pip-audit 2.10.1 over the locked runtime dependencies; it reported no known vulnerabilities.
- Recomputed every vendored source digest, rebuilt the two IANA JSON slices from the raw CSV parents without a network request, and matched the RFC 8259 file to the RFC Editor bytes.
- Replayed every declared query, verified each proof-bearing judgement independently, and projected its evidence back to exact raw source spans.
- Exercised trust-anchor failure, undeclared graph semantics, invalid complement pairs, profile escapes, malformed expressions, asserted and derived inconsistency, stale source bytes, missing evidence, changed rules and premises, and alternate-proof root substitution.
- Confirmed SHACL runs without inference or imports, runtime validation opens no network socket, and production code contains no shell execution, dynamic evaluation, or unsafe deserialisation path.
- Compiled `src/` and `tests/`, checked the full diff, scanned for credential material, verified both implementation commits carry the required provenance trailers, and ran `git fsck`.

The implementation already contained the corrections found during its pre-receipt review. This independent round found no further defect.

| id | severity | file | finding | status |
| --- | --- | --- | --- | --- |
| -- | -- | -- | No findings | closed |

Leads not pursued: full OWL 2 RL conformance, automatic live-registry refresh, and independent authentication of SME modelling choices are outside the declared prototype. The adapter rejects unadvertised OWL constructs and uses only its pinned, offline release.

## Step 4, round 1 -- 2026-08-17

The recorded Solidity security suite remains waived. This round reviewed the full `bf92cb788582b2e2c69f1cf5a65df1a1b9e7ec62...27f6e8c1810fe62b4a4ca28c1bf9349547e235b4` diff. The review covered deterministic question mapping, compound answers, proofless and proof-bearing verification, evidence and rendering integrity, trust direction, transient-question privacy, Null-prime simulation, CLI handling, and the offline demo.

Checks performed:

- Ran all 158 tests with locked, offline uv and with the runbook command inside the activated environment; both runs passed. Ran the 46 Step 4 mapping, answer, probe, and CLI tests separately during an independent KRR review.
- Ran `scripts/demo` through build, ask, verify, and probe. The conjunctive answer carried two independently replayed proofs and evidence packets; the verifier reproduced the fixed answer digest.
- Rebuilt the two IANA slices from pinned parent bytes, compiled `src/` and `tests/`, checked the complete Step 4 diff, ran `git fsck`, and confirmed the implementation commit signature and provenance trailers.
- Ran pip-audit 2.10.1 over the locked third-party packages; it reported no known vulnerabilities. The editable local package was the only skipped entry.
- Exercised changed rendering, evidence, release digests, proof nodes, result order, answer checksum, and extension fields. Each forged certificate failed after recomputing its outer checksum.
- Confirmed proofless unknown answers are rerun rather than accepted by shape, proof-bearing answers replay and re-project exact evidence, and the answer-provided digest never becomes a trust anchor.
- Sent unsupported input and forged certificates containing a private canary through stdin and error paths. The canary appeared in neither certificate, stdout, nor stderr.
- Ran every Step 4 CLI path with socket creation and DNS disabled. Searched production code for network clients, subprocesses, shell execution, dynamic evaluation, unsafe deserialisation, and credential material; no such production path or credential was found.
- Confirmed `questions.json` and `evals.json` are byte-pinned release sources. Null-prime mutates only an in-memory theory, rejects the old proof under the hypothetical digest, and verifies the manifest and every pinned source are unchanged afterward.

| id | severity | file | finding | status |
| --- | --- | --- | --- | --- |
| -- | -- | -- | No findings | closed |

The round closes cleanly. Verification deliberately does not attest the transient sentence a user typed because neither that sentence nor its hash is retained. It attests the pinned public mapping and the resulting formal query plan, as documented in both README files.
