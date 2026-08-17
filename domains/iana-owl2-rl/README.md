# IANA media types with a bounded OWL 2 RL adapter

This release contains a small, byte-pinned part of the IANA Media Types and
Structured Syntax Suffix registries. It covers `application/json`,
`application/problem+json`, and the `+json` suffix. One registry candidate is
deliberately unresolved. The release digest is
`7eaf104e41f2fdf0d1a1dc005f5c881fd813bbd2055d7425acae9d4d22fd207e`.

The official `application` registry CSV, structured-suffix CSV, RFC 6838, RFC
6839, and RFC 8259 are stored under `sources/` with their original bytes. Check
the two small JSON views offline with:

```sh
python3 domains/iana-owl2-rl/sources/extract_iana_slices.py --check
```

Claim maps point to half-open byte spans in the raw CSV, RFC, and local Turtle
files. The `application/json` syntax claim jointly requires the registry row
and RFC 8259's media-type statement. `rfc-locators.json` is provenance
metadata only; its descriptions are not used as evidence for RFC claims.

## Implemented semantics

`noema.adapters.iana_owl2_rl.IanaOwl2RlAdapter` implements `validate`,
`decide`, `justify`, `verify`, and `capabilities`. Its proof replayer accepts
only two grounded OWL 2 RL rule families:

- `cax-sco`: RDF type propagation across one `rdfs:subClassOf` axiom.
- `prp-spo2`: one `owl:propertyChainAxiom` containing exactly two properties.

The release uses open-world semantics and makes no unique-name assumption. It
has no datatype entailment, uses explicit OWL class complements and negative
property assertions, and treats formal inconsistency as fatal. Query pairs are
validated as exact class or property complements before reasoning. Semantic
graph triples must also have matching asserted formal claims. Only label
triples and OWL/RDF collection triples are exempt.

The curated class `RegisteredApplicationMediaType` covers entries that are
both registered and in IANA's `application` tree. It is a subclass of both
`RegisteredMediaType` and `ApplicationMediaType`; the release does not claim
that every registered media type belongs to the `application` tree.

SHACL runs over the asserted graph with inference disabled. OWL-RL then
materialises a separate copy for comparison. RDFLib, OWL-RL, and pySHACL
parse, materialise, and validate the graph. They do not provide Noema's
replayable proof contract. The adapter constructs the proof DAG and
independently replays every grounded rule.

## Boundaries

This is not a claim of full OWL 2 RL conformance. Imports, inverse properties,
longer property chains, datatype reasoning, unrestricted blank nodes, and
unlisted rule families are rejected. Registration and representation syntax
do not establish payload safety, validity, or trustworthiness; those questions
are outside the release signature. A declared but unasserted registry
candidate returns `unknown`, not `contradicted`, because absence from this
formal slice is not a negative registration fact.

## Question and evaluation contract

`questions.json` and `evals.json` are release-pinned sources. The mapper accepts
at most 512 printable ASCII bytes, performs lowercase and space normalisation,
then matches exact finite templates and aliases. It does not use RDF labels,
fuzzy search, a network service, or a language model. Ambiguous bindings and
out-of-profile questions return before `decide` is called.

The public demonstration maps `application/problem+json` to an `all` plan over
`query:problem-json-syntax` and `query:problem-registered`. Both judgements
need their own proof and evidence packet. The candidate
`application/unknown+json` demonstrates a genuine open-world `unknown`, while
the explicit negative property assertion for `application/json` and `+json`
demonstrates `contradicted`.

Null-prime's mutation target is a closed, release-pinned instruction. It marks
`claim:problem-has-json-suffix` unasserted only in memory, computes a
hypothetical digest, and checks that the old proof no longer verifies. The
hypothetical release is not eligible for the adapter and is never written or
promoted. Before and after the probe, Noema hashes `release.json` and every
pinned source.

Answer verification uses the adapter's compiled digest, not a digest supplied
by the certificate. It proves the recorded public template/entity route and
formal results. It does not prove which transient question was typed; raw
question text and question hashes are not retained.
