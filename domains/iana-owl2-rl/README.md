# IANA media types with a bounded OWL 2 RL adapter

This release contains a small, byte-pinned part of the IANA Media Types and
Structured Syntax Suffix registries. It covers `application/json`,
`application/problem+json`, and the `+json` suffix. One registry candidate is
deliberately unresolved. The release digest is
`f35adb674b1dc026435f22b03a8a2f4c9ac7d4dbe61978640c7a9c206d919330`.

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
