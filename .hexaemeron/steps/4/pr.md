# Demonstrate Aleph-prime, Null-prime, and Lemma-prime

This is stacked on [PR #3](https://github.com/laurenceday/noema/pull/3). It completes the IANA prototype with a release-pinned question catalogue, proof-carrying answer certificates, independent verification, and a simulation-only boundary probe.

The public question about `application/problem+json` maps to two formal queries under an `all` plan. Aleph-prime answers each query separately. Lemma-prime projects both proofs to exact IANA and RFC byte spans. `noema verify` reloads the trusted release, validates the mapping, reruns both decisions, replays the proofs, projects the evidence again, and reproduces the fixed rendering and answer checksum.

Null-prime runs six pinned cases across entailed, contradicted, unknown, ambiguous, and unsupported outcomes. Its mutation removes one asserted suffix claim from an in-memory theory, changes the answer from `entailed` to `unknown`, and proves the old certificate fails against the hypothetical release. It does not write or promote that release.

The mapper is a finite, deterministic grammar. Runtime question text and its hash are not stored. Verification therefore attests the pinned public mapping and formal query plan, not the transient wording typed by a user. The release digest is `7eaf104e41f2fdf0d1a1dc005f5c881fd813bbd2055d7425acae9d4d22fd207e`.

Run the demonstration and checks with:

```sh
uv sync --locked
scripts/demo
uv run --offline --locked python -m unittest discover -s tests -v
uv run --offline --locked python domains/iana-owl2-rl/sources/extract_iana_slices.py --check
```

All 158 tests pass. The Step 4 audit is recorded in `audit/AUDIT.md`; it found no issues after checking certificate tampering, trust direction, private-input handling, release immutability, dependency vulnerabilities, and offline execution.

<!-- wildcat-origin: shoggoth -->
