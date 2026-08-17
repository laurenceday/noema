# Noema: a proof-carrying KRR release system

Date: 2026-08-17
Controller topic: Specify and prototype a domain-general KRR-grounded successor to Berean with Aleph-prime, Null-prime, and derivable Lemma-prime.

## Decision summary

Use **Noema** as the working name. Build a small release kernel around proof-producing KRR backend adapters. Keep each backend's native logic and semantics; standardise only the release, query, judgement, proof, evidence, evaluation, and promotion envelopes. Ship one backend and one subject fixture in the prototype.

The first fixture remains a user decision. This study recommends the IANA media-type registry with OWL 2 RL because it tests the description-logic and semantic-network thesis against a compact, authoritative, machine-readable source. The two alternatives are SI metrology with typed Datalog and HTTP caching with Answer Set Programming. All three are specified below so the runbook can present them as a three-way gate.

## 1. Problem statement

### What is being built

Berean treats a pinned textual corpus as evidence units and tests whether an agent can answer, cite, refuse, and improve against that boundary. Noema moves the authoritative answering boundary from retrieved text to a pinned formal theory. The source corpus still matters: every asserted fact, axiom, and domain rule must retain its source mapping, and every delivered answer must be traceable through a reasoner's proof to those mappings.

Noema is not a general retrieval layer. It is a model-neutral release contract for subject matter that can be represented under a declared knowledge-representation and reasoning regime.

A release can be described as:

```text
N = (C, T, Sigma, R, Q, E)

C      pinned human or machine source corpus
T      formal theory: asserted facts, axioms, and domain rules
Sigma  vocabulary, types, entity aliases, and query signature
R      reasoning regime, engine, semantic assumptions, and budgets
Q      supported formal-query grammar and natural-language mappings
E      source maps, evaluations, thresholds, and release records
```

The formal theory is an SME-approved interpretation of the corpus. A sound reasoner can still produce a wrong real-world answer when `T` models `C` incorrectly. Noema can verify the derivation and source map; it cannot replace semantic review.

### Who it is for

- Agent engineers who need one evidence contract across formal subject domains.
- Subject-matter experts who need to review what an agent is permitted to infer.
- Evaluators who need to distinguish entailment, contradiction, ignorance, ambiguity, and unsupported questions without trusting model prose.
- Release operators who need immutable inputs, promotion records, rollback, and a record of capability changes.

### Roles and contracts

**Noema release kernel.** A non-agent component. It builds and verifies immutable domain releases, hashes their artefacts, enforces capability declarations, selects a backend adapter, and records promotion or rollback. It does not decide domain truth.

**Aleph′.** A read-only consumer of one active release. It maps a user question to a typed formal query and entity bindings, rejects ambiguity or out-of-signature requests, invokes the declared reasoner, and renders the resulting judgement without changing its truth conditions. A model may parse and render. It may not add facts or decide entailment.

**Null′.** A boundary investigator. It consumes the release signature, declared capabilities, evaluations, proof traces, and quarantined unanswered questions. It generates or reviews cases for entailment, explicit contradiction, unknowns, ambiguity, inconsistency, profile escape, hostile labels, stale sources, missing evidence, and compute limits. It may propose a release delta. It cannot mutate the active theory or approve its own expected answers.

**Lemma′.** An evidence compiler. At build time it canonicalises semantic units, assigns stable identifiers, and preserves the many-to-many map between source spans and formal claims. At query time it walks a proof or justification DAG to its asserted leaves and emits the smallest deterministic evidence packet permitted by the release. It does not infer a citation from lexical similarity.

**SME/curator.** The human authority for source-to-formal-claim mappings, supported scope, competency questions, and changes to the theory. This fourth role is required even though the user named three prime components.

**Backend adapter.** A logic-specific implementation of:

```text
validate(release) -> validation report
decide(query) -> typed judgement and proof roots
justify(proof_roots, budget) -> proof DAG or one bounded justification
verify(judgement, proof, release) -> independent result
capabilities() -> declared semantics and supported query forms
```

### Question eligibility

A question is answerable only when all of these checks succeed:

1. It maps unambiguously to a query admitted by `Q`.
2. Every symbol and entity binding resolves in `Sigma`.
3. The requested inference is supported by `R` under the release's compute budget.
4. The reasoner returns a judgement allowed by the backend contract.
5. The returned proof verifies against the release digest.
6. Every asserted proof leaf and every domain rule used by the proof has an admissible evidence mapping.

Failure at any check produces a typed refusal or error. It does not invite the language model to fill the gap.

### Judgement semantics

Do not reduce results to Boolean true or false. The common envelope needs these states:

- `entailed`: the release entails the formal claim.
- `contradicted`: the release entails the claim's declared formal complement or explicit negative form.
- `both`: both forms are derivable under a non-explosive regime.
- `unknown`: neither form is derivable, or the release does not declare the relevant predicate complete.
- `ambiguous`: more than one material formalisation or entity binding remains.
- `unsupported`: the query is outside the signature, grammar, profile, or declared capability.
- `inconsistent_release`: a classical theory has no model or otherwise fails its release consistency gate.
- `budget_exceeded`: the declared compute or explanation budget was exhausted.
- `error`: parsing, engine, proof, or integrity verification failed.

OWL non-entailment is not contradiction. Datalog negation-as-failure is not textual negation. A backend must state its open- or closed-world assumptions, unique-name assumption, negation form, monotonicity, datatype support, inconsistency behaviour, and completeness declarations per predicate or query family.

### Why Lemma′ is conditional rather than automatic

A formal theory is lossy. It cannot reconstruct exact human source text unless the formalisation retains that text's identity and location. The source map must therefore be bipartite: one span may yield several claims, and one claim may depend on several spans.

Three objects must remain separate:

- **Provenance** records where a claim or artefact came from.
- **Proof** records the rule-by-rule derivation of a conclusion.
- **Justification** is a subset-minimal set of axioms sufficient for an entailment.

Stable semantic addressing can fall out of a formal theory. Exact evidence does not. The prototype will require one replayable proof or one bounded, deterministic justification; it will not promise every minimal justification.

### Working-prototype test

The selected subject fixture must support this local path without an LLM:

```text
noema build <domain-release>
noema ask <domain-release> <formal-query> --out answer.json
noema verify <domain-release> answer.json
noema probe <domain-release>
```

The prototype is working when automated tests demonstrate all of the following:

1. Repeated builds from byte-identical inputs produce the same release digest.
2. One direct assertion and one multi-hop inference return `entailed` with replayable proof DAGs.
3. One formal complement returns `contradicted` where the chosen logic supports it.
4. One case returns a genuine `unknown` rather than treating absence as false.
5. One ambiguous or out-of-scope question refuses before reasoning.
6. An independent verifier accepts an unmodified answer without a model and rejects a changed proof, claim, source span, or release digest.
7. Lemma′ projects each proof leaf to the declared formal claim and exact evidence locator.
8. Null′ generates or applies at least one minimal mutation that changes the expected result and catches at least one illegal inference.
9. A hostile instruction stored in a label or source span remains inert data.
10. User-question text never enters the public theory or evaluation artefacts by default.

Natural-language mapping may be represented by deterministic templates in the first release. Formal-query correctness and natural-language-to-query correctness must remain separate evaluation groups.

## 2. Prior art

### Supplied Berean specification

The supplied `berean` text defines a release boundary for immutable corpora, byte-exact citations, typed live reads, source classes, refusal conditions, adversarial cases, and evidence-based promotion. Noema retains those release disciplines but replaces text retrieval as the authority for formal questions. Live readings, probabilistic claims, and arbitrary calculations remain outside the first prototype.

The supplied text describes Project Aleph as the answerer and Project Null as the adversarial question generator/reviewer. Their repositories were not available in this empty workspace and were not inspected. This study uses only the roles stated by the user and the supplied specification.

### Lemma 0.1.0

The installed Lemma chunker separates `display_text`, `model_text`, and `embed_text`; uses stable, source-namespaced IDs; marks synthesised evidence; makes validation fatal; and assigns provenance at pipeline level. `INVARIANTS.md` I1-I6 are directly reusable principles. Lemma's byte-sliced Markdown and Solidity chunks are not themselves a KRR proof system, so Noema adds formal-claim IDs, rule IDs, proof nodes, and many-to-many source mappings.

### Agent Skills evaluations

The Agent Skills evaluation guide defines realistic prompts, expected outputs, objective assertions, isolated runs, evidence-backed grading, comparison against a baseline, and iterative review. Noema should emit compatible cases where useful. Logical truth, proof replay, and corpus integrity must be graded by code; model graders may assess prose only.

### KRR and provenance standards

- OWL 2 provides model-theoretic semantics and three profiles. OWL 2 RL is aimed at rule-based implementations; OWL 2 EL supports polynomial-time standard reasoning tasks; OWL 2 QL is aimed at relational query answering.
- OWL 2 Conformance distinguishes syntax, profile, entailment, non-entailment, consistency, and inconsistency tests. Its tool result set also separates `True`, `False`, `Unknown`, and `Error`.
- SHACL Core, W3C Recommendation 20 July 2017, validates RDF data graphs against shapes and returns an RDF validation report. It does not replace ontology entailment or establish a global closed-world assumption.
- PROV-O records entities, activities, agents, and derivation history. It does not provide a logical proof.
- RDFC-1.0 provides canonical RDF dataset serialisation suitable for deterministic hashing. RDF 1.2 is still a Candidate Recommendation Snapshot dated 7 April 2026, so the prototype should use RDF 1.1-compatible data or raw-byte digests rather than depend on draft triple-term behaviour.
- Soufflé Datalog can emit lazy, minimal-height proof trees for derived tuples. That is useful evidence for a Datalog adapter but does not by itself map leaves to human source spans.

### Candidate implementation stacks

The current local environment has Python 3.14.6 and Pydantic 2.13.4. It does not have Java, Soufflé, RDFLib, OWL-RL, pySHACL, or clingo. No package or runtime should be installed until the subject/KRR gate is answered.

Current candidate pins, to be confirmed only for the selected branch, are:

- Soufflé 2.5 for typed Datalog and proof-tree provenance.
- Apache Jena 6.2.0 with Java 21 for custom RDF Horn rules and derivation logging; Jena's built-in OWL rule reasoner must not be presented as a complete OWL 2 reasoner.
- RDFLib 7.6.0, OWL-RL 7.1.4, and pySHACL 0.40.1 for Python RDF parsing, materialisation, and validation. These packages do not supply a portable, complete OWL-RL proof object; a proof-producing adapter remains necessary.
- ELK 0.6.0 with OWLAPI 5.5.1 for an OWL 2 EL alternative with stepwise explanations.
- clingo for the ASP option, with its exact release pin selected after compatibility checks.

## 3. Constraints and non-goals

### Starting point and delivery constraints

- The workspace was empty apart from generated `work/` and `outputs/` directories. No target repository, base commit, remote, or existing implementation was supplied.
- Git is installed. The configured GitHub CLI account failed authentication during preflight. A local prototype and local commits are possible after the subject choice, but a Fiat push and pull request cannot complete until a target repository is named and GitHub authentication works.
- The controller base is `main` because the user did not name another ref.
- The first prototype gets one domain release and one backend. Backend neutrality is demonstrated by the adapter contract and fixtures, not by implementing three reasoners.
- Every network source used for a release must be fetched at build time, pinned by digest, and unavailable to the runtime reasoner.
- Version and licence metadata are release inputs, not comments in prose.

### Non-goals for the prototype

- Universal translation between KRR systems or a shared ISO/IEC 24707 Common Logic representation.
- Automatic conversion of arbitrary prose into an approved ontology or rule set.
- General natural-language understanding. A small deterministic question grammar is enough.
- Runtime self-modification, online learning, or automatic promotion of Null′ proposals.
- Replacement of the SME who approves semantic mappings.
- Arbitrary OWL 2 DL, unrestricted recursion, probabilistic reasoning, temporal logic, belief revision, or live external reads.
- A claim that formal entailment proves real-world truth.
- Enumeration of every minimal justification.
- A chat UI, vector database, model-vendor integration, or hosted service.
- Reimplementation of a general evaluation runner when structured cases and assertions can be emitted for existing runners.

### Capability-growth discipline

Incoming questions enter a privacy-scrubbed quarantine as questions, never as facts. Null′ classifies failures as entity-linking gaps, query-template gaps, missing sources, missing formalisation, inadequate logic, inconsistency, or budget failure. The SME approves any new source mapping, fact, axiom, rule, or declared scope. A new immutable release reruns fixed holdouts and new regression cases before promotion. This keeps capability growth auditable and avoids test leakage into the active theory.

## 4. Design options

### A. RDF/OWL monolith

Put the release, theory, provenance, validation, queries, and answers in RDF; use OWL, SPARQL, SHACL, and PROV-O throughout.

**Trade.** This is a short path to one semantic-network demo and gives useful standards, but it silently treats one family of open-world logics as the universal model. Closed-world policy systems, non-monotonic rules, and solver-specific proof objects do not fit cleanly. SHACL validation can also be mistaken for logical entailment.

### B. Universal logical intermediate representation

Translate every backend into an ISO/IEC 24707 Common Logic representation, then run a single verifier.

**Trade.** The surface looks general. Semantic-preserving translation, proof translation, and executable fragments are the hard part, so this construction spends the prototype on a compiler problem instead of proving the release contract.

### C. Proof-carrying backend adapters (selected)

Standardise a small release and certificate envelope while keeping each theory and reasoner native behind `validate`, `decide`, `justify`, `verify`, and `capabilities`.

**Trade.** Each backend needs its own adapter and proof verifier. In return, Noema does not erase differences in open- versus closed-world semantics, negation, inconsistency, or query expressiveness. One backend is enough for a working prototype, and a second backend can later test whether the common envelope is genuinely portable.

This is the least complex construction that meets the user's domain-general claim without pretending that all KRR systems share one semantics.

## 5. Prototype subject/KRR choice

The runbook must present exactly these three options and pause before implementation.

### 1. IANA media types + OWL 2 RL (recommended)

**SME.** Internet media-type registration specialist.
**KRR.** RDF semantic network constrained to an explicit OWL 2 RL fragment, with stable SHACL Core validation and a proof-producing adapter.

**Demo question.** Is `application/problem+json` a registered media type whose representation follows JSON syntax?

**Formal slice.** Pin the IANA Media Types and Structured Syntax Suffix registries. Model `MediaType`, `RegisteredMediaType`, `StructuredSuffix`, and `RepresentationSyntax`, plus `hasSuffix`, `usesRepresentationSyntax`, and `definedBy`. Map the `application/problem+json` registry row and the `+json` suffix rule to separate claim IDs and source locators.

**Expected behaviour.** Entail the demo through a registry assertion and suffix rule. Refuse a question about whether a payload is safe or trustworthy because registration and suffix syntax do not support that conclusion. Keep “not found in this snapshot” distinct from “not registered” unless the snapshot's membership predicate is explicitly closed. Use `application/json` as a counterexample to the reversed claim that every JSON-syntax media type ends in `+json`.

**Sources and licence.** IANA protocol registries are published under CC0 1.0. The formal suffix rule is grounded in RFC 6839 and the current structured-suffix registry. The release pins the registry bytes and citation locators rather than making live requests at answer time.

**Main risk.** Treating syntax compatibility as an application-semantics, validity, or safety guarantee. A second risk is claiming OWL 2 RL coverage beyond the adapter's tested fragment.

**Estimated prototype effort.** Two implementation steps after the common kernel: registry slice and theory build; then query adapter, proof/evidence rendering, and 15-25 evaluations.

### 2. SI metrology + typed Datalog

**SME.** Metrologist or quantity-calculus specialist.
**KRR.** Many-sorted Datalog with integer dimension vectors and proof-tree provenance, preferably Soufflé 2.5 if installation is approved and compatible.

**Demo question.** A record contains only `12 N·m`. May Aleph′ conclude that the quantity is energy?

**Formal slice.** Pin the SI Brochure's base and derived unit tables. Represent seven base-dimension exponents, unit decompositions, quantity kinds, preferred unit names, and the distinction between energy and torque. Rules derive dimension equality and compatible units; no rule permits `sameDimension` to imply `sameQuantityKind`.

**Expected behaviour.** Entail that `N·m` and `J` share a dimension. Refuse the requested energy classification because the unit alone underdetermines quantity kind. Provide energy and torque as the boundary case: they share a dimension but are distinct quantity kinds.

**Sources and licence.** The BIPM SI Brochure, ninth edition updated in 2026, is published under CC BY 4.0.

**Main risk.** Collapsing unit compatibility into quantity-kind identity. The fixture must exclude affine and logarithmic units, measurement uncertainty, angles, and vector or tensor quantities.

**Estimated prototype effort.** Two implementation steps after the common kernel: about 20 units and 10 quantity kinds with proof traces; then question templates and ambiguity/mutation cases.

### 3. HTTP caching + Answer Set Programming

**SME.** HTTP caching specialist.
**KRR.** ASP or stratified rules with explicit negation and a closed-input declaration, using clingo if its selected release is compatible.

**Demo question.** A shared cache holds a matching `200` GET response with `Cache-Control: max-age=600, no-cache`; its age is 60 seconds and it has not been validated. May the cache reuse it?

**Formal slice.** Pin RFC 9111. Represent request and response facts, cache scope, key matching, `Vary`, age, freshness lifetime, directives, validation state, and input completeness. Rules derive freshness, storage eligibility, blockers, and reuse permission.

**Expected behaviour.** Entail `fresh` but contradict reuse without validation. Removing `no-cache`, while keeping every other reuse precondition, is the minimal mutation that changes the answer. Refuse when the clock, cache scope, header completeness, or `Vary` inputs are missing.

**Sources and licence.** RFC 9111 is the Internet Standard source and is governed by the IETF Trust Legal Provisions. Rules should be paraphrased with section locators; copied code components need their required notices.

**Main risk.** Unsafe negation-as-failure over incomplete message records, plus omitted extensions or local configuration. Proof extraction is harder than solving.

**Estimated prototype effort.** Two larger implementation steps after the common kernel: a bounded subset of storage, reuse, freshness, `Vary`, and 6-8 directives; then adapter, justification extraction, and 25-40 boundary cases.

## 6. Risk register seed

1. **Wrong formalisation.** The theory is faithful to its syntax but not to the source. Require SME review for every mapping and mutation-review samples in evaluation.
2. **Ambiguous question compilation.** A model selects the wrong entity, predicate, quantifier, or time. Return the formal query and bindings, reject material ambiguity, and grade mapping apart from reasoning.
3. **Undeclared semantics.** Open-world absence is treated as false, names as unique, or negation as uniform. Make every semantic assumption machine-readable in the release.
4. **Inconsistent theory.** Classical explosion can make any claim appear entailed. Run consistency before promotion and fail the release before answers.
5. **Reasoner/profile mismatch.** An engine is incomplete, unsound for the advertised fragment, or silently changes across versions. Pin the engine and configuration, gate allowed constructs, and run conformance plus differential cases where possible.
6. **Proof/provenance confusion.** A source map is presented as sufficient logical support, or a proof omits hidden built-ins and imports. Verify every premise and rule; keep historical provenance separate.
7. **Lossy evidence inversion.** A formal claim has no exact source mapping or a rendered citation overstates the source. Treat an unmapped proof leaf as a refusal or cite only the formal artefact as such.
8. **Untrusted content execution.** Labels, comments, IRIs, imports, or cited text contain instructions. Resolve imports at build time, disable reasoner networking, and treat all text fields as inert data.
9. **Source drift and time.** A live registry or standard changes after release. Pin bytes, digest them, record effective dates, and build a new release rather than mutating the old one.
10. **Explanation exhaustion.** Proof or justification search grows without bound. Declare compute, depth, node, and output budgets; return `budget_exceeded` rather than a partial proof presented as complete.
11. **Null′ poisoning and evaluation leakage.** Generated questions become facts or expected answers are approved by the same generator. Quarantine questions, use an independent reviewer, and keep holdouts outside authoring context.
12. **Privacy leakage.** User text or session facts enter a public theory, proof, or evaluation. Keep session facts in a separate labelled store and default to no retention.

## 7. Glossary seeds

- **Corpus:** Pinned human-readable or machine-readable source artefacts.
- **Theory:** The formal facts, axioms, and rules interpreted under one reasoning regime.
- **Domain release:** Immutable bundle of corpus, theory, mappings, engine declaration, evaluations, and release record.
- **Signature (`Sigma`):** Allowed vocabulary, types, entity aliases, and query symbols.
- **Reasoning regime:** Logic, semantics, engine, assumptions, and compute limits applied to a theory.
- **Formal claim:** Stable, canonical assertion, axiom, or rule in the theory.
- **Claim map:** Many-to-many mapping between formal claims and exact source locators or spans.
- **Judgement:** Typed outcome returned by a backend for a formal query.
- **Proof DAG:** Directed acyclic graph of rule applications and asserted leaves supporting a judgement.
- **Justification:** Subset-minimal set of axioms sufficient for an entailment.
- **Evidence packet:** Deterministic projection of proof leaves and source mappings for display or audit.
- **Completeness declaration:** Claim that a predicate or query family is closed over a named release snapshot.
- **Competency question:** Curated question that defines a supported capability of a domain release.
- **Boundary question:** Case expected to contradict, remain unknown, be ambiguous, or refuse.
- **Release delta:** Reviewed change to corpus, theory, mapping, query grammar, engine, or evaluation set.

## 8. Sources

### Supplied and local

- User-supplied `berean` specification, 2026-08-17.
- Lemma 0.1.0: `skills/chunk/SKILL.md`, `INVARIANTS.md`, and `schema.py` in the installed Wildcat Labs plugin.

### Standards and official documentation

- Agent Skills, “Evaluating skill output quality”: <https://agentskills.io/skill-creation/evaluating-skills>
- W3C, OWL 2 Direct Semantics: <https://www.w3.org/TR/owl2-direct-semantics/>
- W3C, OWL 2 Profiles: <https://www.w3.org/TR/owl2-profiles/>
- W3C, OWL 2 Conformance: <https://www.w3.org/TR/owl2-test/>
- W3C, OWL 2 Primer: <https://www.w3.org/TR/owl2-primer/>
- W3C, Shapes Constraint Language (SHACL), Recommendation 20 July 2017: <https://www.w3.org/TR/shacl/>
- W3C, PROV-O: <https://www.w3.org/TR/prov-o/>
- W3C, RDF Dataset Canonicalization: <https://www.w3.org/TR/rdf-canon/>
- W3C, RDF 1.2 Semantics, Candidate Recommendation Snapshot 7 April 2026: <https://www.w3.org/TR/rdf12-semantics/>
- Soufflé, “Provenance”: <https://www.souffle-lang.com/provenance>
- IANA, Media Types registry: <https://www.iana.org/assignments/media-types/media-types.xhtml>
- IANA, Structured Syntax Suffixes registry: <https://www.iana.org/assignments/media-type-structured-suffix/media-type-structured-suffix.xhtml>
- IANA, Licensing Terms: <https://www.iana.org/help/licensing-terms>
- RFC 6839, “Additional Media Type Structured Syntax Suffixes”: <https://www.rfc-editor.org/rfc/rfc6839.html>
- BIPM, SI Brochure: <https://www.bipm.org/en/publications/si-brochure>
- RFC 9111, “HTTP Caching”: <https://www.rfc-editor.org/rfc/rfc9111.html>

### Candidate engine documentation

- Soufflé releases: <https://github.com/souffle-lang/souffle/releases>
- Apache Jena inference and derivations: <https://jena.apache.org/documentation/inference/>
- Apache Jena releases: <https://jena.apache.org/download/>
- RDFLib: <https://github.com/RDFLib/rdflib>
- RDFLib OWL-RL: <https://github.com/RDFLib/OWL-RL>
- pySHACL: <https://github.com/RDFLib/pySHACL/releases>
- ELK reasoner: <https://github.com/liveontologies/elk-reasoner>
- OWLAPI: <https://github.com/owlcs/owlapi>
- clingo: <https://github.com/potassco/clingo>
