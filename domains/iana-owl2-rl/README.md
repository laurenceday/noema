# IANA media types with a bounded OWL 2 RL adapter

This release models a small, byte-pinned part of the IANA Media Types and
Structured Syntax Suffix registries. It covers `application/json`,
`application/problem+json`, the `+json` suffix, and one deliberately unresolved
registry candidate. The release digest is
`d328dea78ccb03c8dd785c333b8d65978adb06cc46c8f0e4f7170ab210ede76e`.

The official `application` registry CSV, structured-suffix CSV, RFC 6838, and
RFC 6839 are stored under `sources/` with their original bytes. The two small
JSON views can be checked offline with:

```sh
python3 domains/iana-owl2-rl/sources/extract_iana_slices.py --check
```

Claim maps point to half-open byte spans in the raw CSV, RFC, and local Turtle
files. `rfc-locators.json` is provenance metadata only; its descriptions are
not used as evidence for RFC claims.

## Implemented semantics

`noema.adapters.iana_owl2_rl.IanaOwl2RlAdapter` implements `validate`,
`decide`, `justify`, `verify`, and `capabilities`. Its proof replayer accepts
only two grounded OWL 2 RL rule families:

- `cax-sco`: RDF type propagation across one `rdfs:subClassOf` axiom.
- `prp-spo2`: one `owl:propertyChainAxiom` containing exactly two properties.

The release uses open-world semantics, no unique-name assumption, no datatype
entailment, explicit OWL class complements and negative property assertions,
and release-fatal formal inconsistency. Query pairs are validated as exact
class or property complements before reasoning.

The class `RegisteredApplicationMediaType` is the curated intersection-like
slice for a registered entry in the IANA `application` tree. It is a subclass
of both `RegisteredMediaType` and `ApplicationMediaType`; the release does not
claim that every registered media type belongs to the `application` tree.

SHACL runs over the asserted graph with inference disabled. OWL-RL then
materialises a separate copy as a differential reference check. RDFLib,
OWL-RL, and pySHACL parse, materialise, and validate, but do not provide
Noema's replayable proof contract. The adapter constructs the proof DAG and
independently replays every grounded rule.

## Boundaries

This is not a claim of full OWL 2 RL conformance. Imports, inverse properties,
longer property chains, datatype reasoning, unrestricted blank nodes, and
unlisted rule families are rejected. Registration and representation syntax
do not establish payload safety, validity, or trustworthiness; those questions
are outside the release signature. A declared but unasserted registry
candidate returns `unknown`, not `contradicted`, because absence from this
formal slice is not a negative registration fact.
