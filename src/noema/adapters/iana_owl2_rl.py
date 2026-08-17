"""Proof-producing adapter for Noema's bounded IANA OWL 2 RL release.

The adapter implements two OWL 2 RL rule families over release-pinned ground
claims.  RDFLib, OWL-RL, and pySHACL are reference parsing, materialisation,
and validation paths; none of them is treated as a proof-certificate source.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from owlrl import OWLRL_Semantics
from pyshacl import validate as shacl_validate
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

from noema.canonical import (
    JSONValue,
    canonical_bytes,
    digest_domain_json,
    load_json_bytes,
    load_json_file,
)
from noema.errors import (
    CanonicalizationError,
    ProofVerificationError,
    ReleaseValidationError,
)
from noema.model import (
    BackendDeclaration,
    FormalClaim,
    GroundRule,
    Judgement,
    JudgementStatus,
    Proof,
    ProofNode,
    ProofNodeKind,
    QuerySpec,
    Release,
    valid_identifier,
)
from noema.proof import VerificationResult, verify_proof
from noema.release import build_release, validate_release


SEMANTIC_PROFILE = "owl2-rl-noema/v1"
BACKEND_ID = "backend:iana-owl2-rl-fragment"
DEFAULT_TRUSTED_RELEASE_DIGEST = (
    "f35adb674b1dc026435f22b03a8a2f4c9ac7d4dbe61978640c7a9c206d919330"
)
NODE_HASH_DOMAIN = "noema:iana-owl2-rl-node:v1"
IANA = "https://noema.invalid/iana/"

RDF_TYPE = str(RDF.type)
RDFS_SUBCLASS = str(RDFS.subClassOf)

_CUSTOM_PREDICATES = frozenset(
    URIRef(IANA + local)
    for local in (
        "hasSuffix",
        "mediaTypeName",
        "suffixName",
        "suffixSyntax",
        "syntaxName",
        "usesRepresentationSyntax",
    )
)
_LABEL_PREDICATES = frozenset(
    URIRef(IANA + local)
    for local in ("mediaTypeName", "suffixName", "syntaxName")
)
_ALLOWED_PREDICATES = frozenset(
    {
        RDF.type,
        RDF.first,
        RDF.rest,
        RDFS.subClassOf,
        OWL.assertionProperty,
        OWL.complementOf,
        OWL.propertyChainAxiom,
        OWL.sourceIndividual,
        OWL.targetIndividual,
        *_CUSTOM_PREDICATES,
    }
)
_APPROVED_TYPE_OBJECTS = frozenset(
    URIRef(IANA + local)
    for local in (
        "ApplicationMediaType",
        "MediaType",
        "NotMediaType",
        "NotRegisteredApplicationMediaType",
        "NotRegisteredMediaType",
        "RegisteredApplicationMediaType",
        "RegisteredMediaType",
        "RepresentationSyntax",
        "StructuredSyntaxSuffix",
    )
)
_APPROVED_SUBCLASS_PAIRS = frozenset(
    {
        (
            URIRef(IANA + "RegisteredApplicationMediaType"),
            URIRef(IANA + "RegisteredMediaType"),
        ),
        (
            URIRef(IANA + "RegisteredApplicationMediaType"),
            URIRef(IANA + "ApplicationMediaType"),
        ),
        (
            URIRef(IANA + "RegisteredMediaType"),
            URIRef(IANA + "MediaType"),
        ),
        (
            URIRef(IANA + "ApplicationMediaType"),
            URIRef(IANA + "MediaType"),
        ),
    }
)
_APPROVED_COMPLEMENT_PAIRS = frozenset(
    {
        (
            URIRef(IANA + "NotRegisteredApplicationMediaType"),
            URIRef(IANA + "RegisteredApplicationMediaType"),
        ),
        (
            URIRef(IANA + "NotRegisteredMediaType"),
            URIRef(IANA + "RegisteredMediaType"),
        ),
        (URIRef(IANA + "NotMediaType"), URIRef(IANA + "MediaType")),
    }
)
_APPROVED_PROPERTY_CHAIN = (
    URIRef(IANA + "usesRepresentationSyntax"),
    URIRef(IANA + "hasSuffix"),
    URIRef(IANA + "suffixSyntax"),
)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Stable validation result without retaining exception or source text."""

    valid: bool
    release_digest: str | None
    errors: tuple[str, ...]
    shacl_conforms: bool
    reference_materialization_checked: bool

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "errors": list(self.errors),
            "reference_materialization_checked": self.reference_materialization_checked,
            "release_digest": self.release_digest,
            "shacl_conforms": self.shacl_conforms,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class Decision:
    """A common judgement paired with its complete proof, when one exists."""

    judgement: Judgement
    proof: Proof | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "judgement": self.judgement.to_dict(),
            "proof": self.proof.to_dict() if self.proof is not None else None,
        }


ClaimExpression = tuple[str, ...]


def _parse_claim_expression(claim: FormalClaim) -> ClaimExpression:
    """Decode the adapter's canonical IRI-only claim expression language."""
    try:
        raw = load_json_bytes(claim.expression.encode("utf-8"))
    except (CanonicalizationError, UnicodeEncodeError) as exc:
        raise ValueError("claim expression is not canonical JSON") from exc
    if not isinstance(raw, list) or not raw or any(
        not isinstance(value, str) or not value for value in raw
    ):
        raise ValueError("claim expression must be a non-empty string array")
    if claim.expression != canonical_bytes(raw).decode("utf-8"):
        raise ValueError("claim expression is not in canonical form")
    expression = tuple(raw)
    if expression[0] in {"triple", "negative-property"}:
        if len(expression) != 4:
            raise ValueError("claim expression must contain three terms")
        terms = expression[1:]
    elif expression[0] == "property-chain":
        if len(expression) != 4:
            raise ValueError("only two-property chains are supported")
        terms = expression[1:]
    else:
        raise ValueError("claim expression form is unsupported")
    for term in terms:
        parsed = urlsplit(term)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("claim terms must be absolute HTTP IRIs")
    return expression


@dataclass(frozen=True, slots=True)
class OwlRlFragmentReplayer:
    """Independent semantic replay for cax-sco and length-two prp-spo2."""

    def supports(self, backend: BackendDeclaration) -> bool:
        return (
            backend.id == BACKEND_ID
            and backend.version == "1.0.0"
            and backend.semantic_profile == SEMANTIC_PROFILE
            and backend.world_assumption == "open"
            and backend.unique_name_assumption is False
            and backend.negation == "explicit-complement"
            and backend.monotonic is True
            and backend.datatype_policy == "rdf-1.1-literals-no-entailment/v1"
            and backend.inconsistency_policy == "reject-release/v1"
        )

    def replay(
        self,
        rule: GroundRule,
        premises: tuple[FormalClaim, ...],
        conclusion: FormalClaim,
    ) -> bool:
        if tuple(claim.id for claim in premises) != rule.premise_claim_ids:
            return False
        if conclusion.id != rule.conclusion_claim_id:
            return False
        try:
            premise_expressions = tuple(_parse_claim_expression(item) for item in premises)
            result = _parse_claim_expression(conclusion)
        except ValueError:
            return False

        if rule.id.startswith("owlrl:cax-sco:"):
            if len(premise_expressions) != 2:
                return False
            membership, subclass = premise_expressions
            return (
                membership[0] == "triple"
                and membership[2] == RDF_TYPE
                and subclass[0] == "triple"
                and subclass[2] == RDFS_SUBCLASS
                and membership[3] == subclass[1]
                and result
                == ("triple", membership[1], RDF_TYPE, subclass[3])
            )

        if rule.id.startswith("owlrl:prp-spo2:"):
            if len(premise_expressions) != 3:
                return False
            left, right, chain = premise_expressions
            return (
                left[0] == "triple"
                and right[0] == "triple"
                and chain[0] == "property-chain"
                and left[3] == right[1]
                and chain[2] == left[2]
                and chain[3] == right[2]
                and result
                == ("triple", left[1], chain[1], right[3])
            )

        return False

    def validate_node_id(self, node: ProofNode) -> bool:
        """Bind adapter proof node IDs to their complete semantic payload."""
        if node.kind is ProofNodeKind.ASSERTION:
            expected = _node_id("assertion", {"claim_id": node.claim_id})
        elif node.kind is ProofNodeKind.RULE:
            if node.rule_id is None:
                return False
            expected = _node_id(
                "rule",
                {
                    "claim_id": node.claim_id,
                    "premise_node_ids": list(node.premise_node_ids),
                    "rule_id": node.rule_id,
                },
            )
        else:
            return False
        return node.id == expected


@dataclass(frozen=True, slots=True)
class _Candidate:
    root_node_id: str
    nodes: tuple[ProofNode, ...]
    depth: int
    tie_breaker: tuple[object, ...]

    @property
    def score(self) -> tuple[object, ...]:
        return (len(self.nodes), self.depth, self.tie_breaker)


def _node_id(kind: str, payload: JSONValue) -> str:
    return "node:" + kind + ":" + digest_domain_json(NODE_HASH_DOMAIN, payload)[:32]


def _assertion_candidate(claim: FormalClaim) -> _Candidate:
    node_id = _node_id("assertion", {"claim_id": claim.id})
    node = ProofNode(
        id=node_id,
        kind=ProofNodeKind.ASSERTION,
        claim_id=claim.id,
    )
    return _Candidate(node_id, (node,), 1, (claim.id,))


def _rule_candidate(
    rule: GroundRule,
    premises: tuple[_Candidate, ...],
) -> _Candidate:
    premise_ids = tuple(candidate.root_node_id for candidate in premises)
    node_id = _node_id(
        "rule",
        {
            "claim_id": rule.conclusion_claim_id,
            "premise_node_ids": list(premise_ids),
            "rule_id": rule.id,
        },
    )
    node_by_id: dict[str, ProofNode] = {}
    for candidate in premises:
        node_by_id.update((node.id, node) for node in candidate.nodes)
    node_by_id[node_id] = ProofNode(
        id=node_id,
        kind=ProofNodeKind.RULE,
        claim_id=rule.conclusion_claim_id,
        rule_id=rule.id,
        premise_node_ids=premise_ids,
    )
    return _Candidate(
        root_node_id=node_id,
        nodes=tuple(sorted(node_by_id.values(), key=lambda node: node.id)),
        depth=1 + max(candidate.depth for candidate in premises),
        tie_breaker=(rule.id, premise_ids, node_id),
    )


def _reachable_claim_ids(
    release: Release,
    replayer: OwlRlFragmentReplayer,
) -> frozenset[str]:
    claim_by_id = {claim.id: claim for claim in release.claims}
    reachable = {claim.id for claim in release.claims if claim.asserted}
    changed = True
    while changed:
        changed = False
        for rule in release.rules:
            if rule.conclusion_claim_id in reachable:
                continue
            if not all(premise in reachable for premise in rule.premise_claim_ids):
                continue
            premises = tuple(claim_by_id[item] for item in rule.premise_claim_ids)
            if replayer.replay(rule, premises, claim_by_id[rule.conclusion_claim_id]) is True:
                reachable.add(rule.conclusion_claim_id)
                changed = True
    return frozenset(reachable)


def _derive_candidates(
    release: Release,
    replayer: OwlRlFragmentReplayer,
) -> dict[str, _Candidate]:
    claim_by_id = {claim.id: claim for claim in release.claims}
    candidates = {
        claim.id: _assertion_candidate(claim)
        for claim in release.claims
        if claim.asserted
    }
    changed = True
    while changed:
        changed = False
        for rule in release.rules:
            if not all(item in candidates for item in rule.premise_claim_ids):
                continue
            premise_candidates = tuple(
                candidates[item] for item in rule.premise_claim_ids
            )
            premises = tuple(claim_by_id[item] for item in rule.premise_claim_ids)
            conclusion = claim_by_id[rule.conclusion_claim_id]
            if replayer.replay(rule, premises, conclusion) is not True:
                continue
            candidate = _rule_candidate(rule, premise_candidates)
            if (
                len(candidate.nodes) > release.backend.max_proof_nodes
                or candidate.depth > release.backend.max_proof_depth
            ):
                continue
            prior = candidates.get(rule.conclusion_claim_id)
            if prior is None or candidate.score < prior.score:
                candidates[rule.conclusion_claim_id] = candidate
                changed = True
    return candidates


def _graph_for_release(domain_root: Path) -> Graph:
    graph = Graph()
    graph.parse(domain_root / "theory" / "vocabulary.ttl", format="turtle")
    graph.parse(domain_root / "theory" / "assertions.ttl", format="turtle")
    return graph


def _strict_object(
    value: object,
    keys: set[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError("formal artefact shape differs")
    return value


def _strict_array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("formal artefact array differs")
    return value


def _validate_mirrors(domain_root: Path, release: Release) -> dict[str, str]:
    claims = _strict_object(
        load_json_file(domain_root / "theory" / "claims.json"),
        {"claims", "schema"},
    )
    if claims["schema"] != "noema.formal-claims/v1":
        raise ValueError("claim schema differs")
    if claims["claims"] != [claim.to_dict() for claim in release.claims]:
        raise ValueError("claim mirror differs")

    rules = _strict_object(
        load_json_file(domain_root / "theory" / "rules.json"),
        {"ground_rules", "schema", "supported_rule_families"},
    )
    if rules["schema"] != "noema.owl2-rl-ground-rules/v1":
        raise ValueError("rule schema differs")
    families = _strict_array(rules["supported_rule_families"])
    family_ids = []
    for value in families:
        family = _strict_object(value, {"id", "meaning"})
        if not isinstance(family["id"], str) or not isinstance(family["meaning"], str):
            raise ValueError("rule family differs")
        family_ids.append(family["id"])
    if family_ids != ["owlrl:cax-sco", "owlrl:prp-spo2"]:
        raise ValueError("rule family differs")
    if rules["ground_rules"] != [rule.to_dict() for rule in release.rules]:
        raise ValueError("rule mirror differs")

    queries = _strict_object(
        load_json_file(domain_root / "theory" / "queries.json"),
        {"queries", "schema"},
    )
    if queries["schema"] != "noema.formal-queries/v1":
        raise ValueError("query schema differs")
    if queries["queries"] != [query.to_dict() for query in release.queries]:
        raise ValueError("query mirror differs")

    mappings = _strict_object(
        load_json_file(domain_root / "theory" / "claim-maps.json"),
        {"claim_maps", "schema"},
    )
    if mappings["schema"] != "noema.claim-maps/v1":
        raise ValueError("claim-map schema differs")
    if mappings["claim_maps"] != [mapping.to_dict() for mapping in release.claim_maps]:
        raise ValueError("claim-map mirror differs")

    expected = _strict_object(
        load_json_file(domain_root / "theory" / "expected-judgements.json"),
        {"judgements", "schema"},
    )
    if expected["schema"] != "noema.expected-judgements/v1":
        raise ValueError("expected-judgement schema differs")
    result: dict[str, str] = {}
    for raw in _strict_array(expected["judgements"]):
        item = _strict_object(raw, {"query_id", "status"})
        if not isinstance(item["query_id"], str) or not isinstance(item["status"], str):
            raise ValueError("expected judgement differs")
        if item["query_id"] in result:
            raise ValueError("expected judgement repeats query")
        result[item["query_id"]] = item["status"]
    if set(result) != {query.id for query in release.queries}:
        raise ValueError("expected judgement coverage differs")
    return result


def _validate_fragment(graph: Graph) -> None:
    list_nodes: set[BNode] = set()
    negative_nodes = {
        subject
        for subject in graph.subjects(RDF.type, OWL.NegativePropertyAssertion)
        if isinstance(subject, BNode)
    }
    negative_predicates = {
        RDF.type,
        OWL.sourceIndividual,
        OWL.assertionProperty,
        OWL.targetIndividual,
    }
    negative_components = negative_predicates - {RDF.type}
    for subject, predicate, obj in graph:
        if predicate not in _ALLOWED_PREDICATES:
            raise ValueError("predicate is outside the supported fragment")
        if isinstance(subject, BNode):
            if subject in negative_nodes:
                if predicate not in negative_predicates:
                    raise ValueError("negative property assertion is malformed")
            else:
                list_nodes.add(subject)
                if predicate not in {RDF.first, RDF.rest}:
                    raise ValueError("blank node is outside an RDF collection")
        elif not isinstance(subject, URIRef) or not str(subject).startswith(IANA):
            raise ValueError("subject is outside the release namespace")

        if predicate in {RDF.first, RDF.rest} and not isinstance(subject, BNode):
            raise ValueError("RDF collection predicate has a non-blank subject")
        if predicate in negative_components and subject not in negative_nodes:
            raise ValueError("negative assertion component is outside its node")

        if predicate in _LABEL_PREDICATES:
            if not isinstance(obj, Literal) or obj.language is not None:
                raise ValueError("label must be an untagged string")
            if obj.datatype not in {None, XSD.string}:
                raise ValueError("label datatype is unsupported")
        elif predicate == RDF.type:
            if isinstance(subject, BNode):
                if obj != OWL.NegativePropertyAssertion:
                    raise ValueError("negative assertion type is unsupported")
            elif obj not in _APPROVED_TYPE_OBJECTS:
                raise ValueError("rdf:type object is outside the supported profile")
        elif predicate == RDFS.subClassOf:
            if (subject, obj) not in _APPROVED_SUBCLASS_PAIRS:
                raise ValueError("subclass axiom is outside the supported profile")
        elif predicate == OWL.complementOf:
            if (subject, obj) not in _APPROVED_COMPLEMENT_PAIRS:
                raise ValueError("class complement is outside the supported profile")
        elif predicate == OWL.assertionProperty:
            if obj not in {
                URIRef(IANA + "hasSuffix"),
                URIRef(IANA + "usesRepresentationSyntax"),
            }:
                raise ValueError("negative assertion property is unsupported")
        elif predicate == RDF.rest:
            if obj != RDF.nil and not isinstance(obj, BNode):
                raise ValueError("RDF list tail is invalid")
        elif predicate == OWL.propertyChainAxiom:
            if not isinstance(obj, BNode):
                raise ValueError("property chain must use an RDF collection")
            list_nodes.add(obj)
        elif not isinstance(obj, URIRef):
            raise ValueError("fragment object must be an IRI")

        for term in (subject, obj):
            if isinstance(term, URIRef):
                text = str(term)
                if not (
                    text.startswith(IANA)
                    or text.startswith(str(RDF))
                    or text.startswith(str(RDFS))
                    or text.startswith(str(OWL))
                ):
                    raise ValueError("IRI is outside the supported vocabulary")

    for subject in graph.subjects(OWL.propertyChainAxiom, None):
        heads = list(graph.objects(subject, OWL.propertyChainAxiom))
        if len(heads) != 1:
            raise ValueError("property chain declaration is not singular")
        values = tuple(Collection(graph, heads[0]))
        if len(values) != 2 or any(not isinstance(value, URIRef) for value in values):
            raise ValueError("only two-property chains are supported")
        if (subject, *values) != _APPROVED_PROPERTY_CHAIN:
            raise ValueError("property chain is outside the supported profile")
    for node in list_nodes:
        predicates = set(graph.predicates(node, None))
        if not predicates or not predicates.issubset({RDF.first, RDF.rest}):
            raise ValueError("RDF collection node is malformed")
        if (
            len(tuple(graph.objects(node, RDF.first))) != 1
            or len(tuple(graph.objects(node, RDF.rest))) != 1
        ):
            raise ValueError("RDF collection node is incomplete")
    for node in negative_nodes:
        for predicate in negative_predicates:
            if len(tuple(graph.objects(node, predicate))) != 1:
                raise ValueError("negative property assertion is incomplete")


def _negative_property_in_graph(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef,
) -> bool:
    for node in graph.subjects(RDF.type, OWL.NegativePropertyAssertion):
        if (
            (node, OWL.sourceIndividual, subject) in graph
            and (node, OWL.assertionProperty, predicate) in graph
            and (node, OWL.targetIndividual, obj) in graph
        ):
            return True
    return False


def _matching_negative_nodes(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef,
) -> tuple[BNode, ...]:
    return tuple(
        node
        for node in graph.subjects(RDF.type, OWL.NegativePropertyAssertion)
        if isinstance(node, BNode)
        and (node, OWL.sourceIndividual, subject) in graph
        and (node, OWL.assertionProperty, predicate) in graph
        and (node, OWL.targetIndividual, obj) in graph
    )


def _claim_in_graph(graph: Graph, claim: FormalClaim) -> bool:
    expression = _parse_claim_expression(claim)
    if expression[0] == "triple":
        return tuple(URIRef(value) for value in expression[1:]) in graph
    if expression[0] == "negative-property":
        subject, predicate, obj = (URIRef(value) for value in expression[1:])
        return _negative_property_in_graph(graph, subject, predicate, obj)
    super_property, first, second = (URIRef(value) for value in expression[1:])
    for head in graph.objects(super_property, OWL.propertyChainAxiom):
        if tuple(Collection(graph, head)) == (first, second):
            return True
    return False


def _rdf_list_scaffolding(graph: Graph, head: BNode) -> set[tuple[object, ...]]:
    triples: set[tuple[object, ...]] = set()
    node: object = head
    seen: set[BNode] = set()
    while isinstance(node, BNode):
        if node in seen:
            raise ValueError("RDF collection cycle is unsupported")
        seen.add(node)
        first = next(iter(graph.objects(node, RDF.first)))
        rest = next(iter(graph.objects(node, RDF.rest)))
        triples.add((node, RDF.first, first))
        triples.add((node, RDF.rest, rest))
        node = rest
    if node != RDF.nil:
        raise ValueError("RDF collection does not terminate at rdf:nil")
    return triples


def _validate_graph_claim_completeness(graph: Graph, release: Release) -> None:
    """Reject semantic graph material that has no asserted formal claim."""
    allowed: set[tuple[object, ...]] = {
        triple for triple in graph if triple[1] in _LABEL_PREDICATES
    }
    for claim in release.claims:
        if not claim.asserted:
            continue
        expression = _parse_claim_expression(claim)
        if expression[0] == "triple":
            allowed.add(tuple(URIRef(value) for value in expression[1:]))
            continue
        if expression[0] == "negative-property":
            subject, predicate, obj = (URIRef(value) for value in expression[1:])
            nodes = _matching_negative_nodes(graph, subject, predicate, obj)
            if not nodes:
                raise ValueError("asserted negative property claim is absent")
            for node in nodes:
                allowed.update(
                    {
                        (node, RDF.type, OWL.NegativePropertyAssertion),
                        (node, OWL.sourceIndividual, subject),
                        (node, OWL.assertionProperty, predicate),
                        (node, OWL.targetIndividual, obj),
                    }
                )
            continue
        super_property, first, second = (
            URIRef(value) for value in expression[1:]
        )
        for head in graph.objects(super_property, OWL.propertyChainAxiom):
            if isinstance(head, BNode) and tuple(Collection(graph, head)) == (
                first,
                second,
            ):
                allowed.add((super_property, OWL.propertyChainAxiom, head))
                allowed.update(_rdf_list_scaffolding(graph, head))

    if set(graph) != allowed:
        raise ValueError("graph contains undeclared semantic material")


def _validate_query_complements(release: Release, graph: Graph) -> None:
    claims = {claim.id: claim for claim in release.claims}
    for query in release.queries:
        if query.complement_claim_id is None:
            continue
        positive = _parse_claim_expression(claims[query.positive_claim_id])
        complement = _parse_claim_expression(claims[query.complement_claim_id])
        forms = {positive[0], complement[0]}
        if forms == {"triple", "negative-property"}:
            if positive[1:] != complement[1:]:
                raise ValueError("property complement does not match query")
            continue
        if positive[0] == complement[0] == "triple":
            if (
                positive[2] != RDF_TYPE
                or complement[2] != RDF_TYPE
                or positive[1] != complement[1]
            ):
                raise ValueError("class complement does not match query")
            first = URIRef(positive[3])
            second = URIRef(complement[3])
            if (
                (first, OWL.complementOf, second) not in graph
                and (second, OWL.complementOf, first) not in graph
            ):
                raise ValueError("query classes are not declared complements")
            continue
        raise ValueError("query does not declare an exact formal complement")


def _query_status(query: QuerySpec, reachable: frozenset[str]) -> JudgementStatus:
    positive = query.positive_claim_id in reachable
    complement = (
        query.complement_claim_id is not None
        and query.complement_claim_id in reachable
    )
    if positive and complement:
        return JudgementStatus.BOTH
    if positive:
        return JudgementStatus.ENTAILED
    if complement:
        return JudgementStatus.CONTRADICTED
    return JudgementStatus.UNKNOWN


def _has_formal_conflict(
    release: Release,
    graph: Graph,
    reachable: frozenset[str],
) -> bool:
    expressions = [
        _parse_claim_expression(claim)
        for claim in release.claims
        if claim.id in reachable
    ]
    triples = {expression[1:] for expression in expressions if expression[0] == "triple"}
    negatives = {
        expression[1:]
        for expression in expressions
        if expression[0] == "negative-property"
    }
    if triples.intersection(negatives):
        return True

    memberships: dict[str, set[str]] = {}
    for expression in expressions:
        if expression[0] == "triple" and expression[2] == RDF_TYPE:
            memberships.setdefault(expression[1], set()).add(expression[3])
    complement_pairs = {
        (str(first), str(second))
        for first, second in graph.subject_objects(OWL.complementOf)
    }
    return any(
        first in classes and second in classes
        for classes in memberships.values()
        for first, second in complement_pairs
    )


class IanaOwl2RlAdapter:
    """No-network adapter for the release-pinned IANA OWL 2 RL fragment."""

    def __init__(
        self,
        domain_root: Path,
        *,
        trusted_release_digest: str = DEFAULT_TRUSTED_RELEASE_DIGEST,
    ) -> None:
        self.domain_root = Path(domain_root)
        self.trusted_release_digest = trusted_release_digest
        self.replayer = OwlRlFragmentReplayer()

    def _load_release(self) -> Release:
        release = build_release(self.domain_root / "release.json")
        validate_release(
            release,
            source_root=self.domain_root,
            expected_digest=self.trusted_release_digest,
        )
        return release

    def validate(self) -> ValidationReport:
        def invalid(
            error: str,
            *,
            release_digest: str | None,
            shacl_conforms: bool = False,
            materialization_checked: bool = False,
        ) -> ValidationReport:
            return ValidationReport(
                valid=False,
                release_digest=release_digest,
                errors=(error,),
                shacl_conforms=shacl_conforms,
                reference_materialization_checked=materialization_checked,
            )

        try:
            release = build_release(self.domain_root / "release.json")
            digest = release.digest
        except (CanonicalizationError, ReleaseValidationError, OSError):
            return invalid("release-integrity", release_digest=None)

        try:
            validate_release(
                release,
                source_root=self.domain_root,
                expected_digest=self.trusted_release_digest,
            )
        except ReleaseValidationError:
            return invalid("trusted-release-digest", release_digest=digest)

        try:
            supported = self.replayer.supports(release.backend)
        except Exception:
            supported = False
        if supported is not True:
            return invalid("semantic-assumptions", release_digest=digest)

        try:
            expected = _validate_mirrors(self.domain_root, release)
        except (CanonicalizationError, OSError, ValueError):
            return invalid("formal-mirror", release_digest=digest)

        try:
            graph = _graph_for_release(self.domain_root)
        except Exception:
            return invalid("rdf-syntax", release_digest=digest)

        try:
            _validate_fragment(graph)
            for claim in release.claims:
                present = _claim_in_graph(graph, claim)
                if claim.asserted != present:
                    raise ValueError("claim assertion state differs")
            _validate_query_complements(release, graph)
            _validate_graph_claim_completeness(graph, release)
        except Exception:
            return invalid("owl-fragment", release_digest=digest)

        try:
            shape_graph = Graph().parse(
                self.domain_root / "theory" / "shapes.ttl",
                format="turtle",
            )
            conforms, _, _ = shacl_validate(
                data_graph=graph,
                shacl_graph=shape_graph,
                inference="none",
                advanced=False,
                meta_shacl=False,
                do_owl_imports=False,
                serialize_report_graph=False,
            )
            shacl_conforms = conforms is True
            if not shacl_conforms:
                return invalid("shacl-violation", release_digest=digest)
        except Exception:
            return invalid("shacl-error", release_digest=digest)

        reachable = _reachable_claim_ids(release, self.replayer)
        try:
            materialized = Graph()
            for triple in graph:
                materialized.add(triple)
            reference_semantics = OWLRL_Semantics(
                materialized,
                axioms=False,
                daxioms=False,
            )
            reference_semantics.closure()
            reference_conflict = bool(reference_semantics.error_messages)
            for claim in release.claims:
                if claim.id in reachable and not claim.asserted:
                    if not _claim_in_graph(materialized, claim):
                        raise ValueError("reference reasoner omitted reachable claim")
        except Exception:
            return invalid(
                "reference-materialization",
                release_digest=digest,
                shacl_conforms=True,
            )

        errors: list[str] = []
        statuses = {
            query.id: _query_status(query, reachable) for query in release.queries
        }
        if _has_formal_conflict(release, graph, reachable) or any(
            status is JudgementStatus.BOTH for status in statuses.values()
        ) or reference_conflict:
            errors.append("inconsistent-release")
        if any(
            expected.get(query_id) != status.value
            for query_id, status in statuses.items()
        ):
            errors.append("expected-judgement-mismatch")

        unique_errors = tuple(dict.fromkeys(errors))
        return ValidationReport(
            valid=not unique_errors,
            release_digest=digest,
            errors=unique_errors,
            shacl_conforms=True,
            reference_materialization_checked=True,
        )

    def decide(self, query_id: str) -> Decision:
        if not valid_identifier(query_id):
            raise ValueError("query ID is not a stable identifier")
        report = self.validate()
        if not report.valid:
            conflict_only = (
                "inconsistent-release" in report.errors
                and set(report.errors).issubset(
                    {"inconsistent-release", "expected-judgement-mismatch"}
                )
            )
            reason = (
                "release:inconsistent"
                if conflict_only
                else "release:invalid"
            )
            judgement = Judgement(
                status=(
                    JudgementStatus.INCONSISTENT_RELEASE
                    if conflict_only
                    else JudgementStatus.ERROR
                ),
                query_id=query_id,
                release_digest=report.release_digest or "0" * 64,
                reason_code=reason,
            )
            judgement.validate()
            return Decision(judgement=judgement, proof=None)

        release = self._load_release()
        query = next((item for item in release.queries if item.id == query_id), None)
        if query is None:
            judgement = Judgement(
                status=JudgementStatus.UNSUPPORTED,
                query_id=query_id,
                release_digest=release.digest,
                reason_code="query:not-declared",
            )
            judgement.validate()
            return Decision(judgement=judgement, proof=None)

        reachable = _reachable_claim_ids(release, self.replayer)
        candidates = _derive_candidates(release, self.replayer)
        status = _query_status(query, reachable)
        if status is JudgementStatus.BOTH:
            judgement = Judgement(
                status=JudgementStatus.INCONSISTENT_RELEASE,
                query_id=query.id,
                release_digest=release.digest,
                reason_code="release:inconsistent",
            )
            judgement.validate()
            return Decision(judgement=judgement, proof=None)
        if status is JudgementStatus.UNKNOWN:
            judgement = Judgement(
                status=status,
                query_id=query.id,
                release_digest=release.digest,
                reason_code="open-world:neither-derivable",
            )
            judgement.validate()
            return Decision(judgement=judgement, proof=None)

        claim_id = (
            query.positive_claim_id
            if status is JudgementStatus.ENTAILED
            else query.complement_claim_id
        )
        assert claim_id is not None
        candidate = candidates.get(claim_id)
        if candidate is None:
            judgement = Judgement(
                status=JudgementStatus.BUDGET_EXCEEDED,
                query_id=query.id,
                release_digest=release.digest,
                reason_code="proof:budget-exceeded",
            )
            judgement.validate()
            return Decision(judgement=judgement, proof=None)

        proof = Proof(
            release_digest=release.digest,
            root_node_ids=(candidate.root_node_id,),
            nodes=candidate.nodes,
        )
        judgement = Judgement(
            status=status,
            query_id=query.id,
            release_digest=release.digest,
            conclusion_claim_ids=(claim_id,),
            proof_root_node_ids=(candidate.root_node_id,),
        )
        judgement.validate()
        verify_proof(
            release,
            judgement,
            proof,
            trusted_release_digest=self.trusted_release_digest,
            replayer=self.replayer,
        )
        return Decision(judgement=judgement, proof=proof)

    def justify(self, query_id: str) -> Proof | None:
        return self.decide(query_id).proof

    def verify(
        self,
        judgement: Judgement,
        proof: Proof,
    ) -> VerificationResult:
        report = self.validate()
        if not report.valid:
            raise ProofVerificationError("adapter release validation failed")
        return verify_proof(
            self._load_release(),
            judgement,
            proof,
            trusted_release_digest=self.trusted_release_digest,
            replayer=self.replayer,
        )

    def capabilities(self) -> dict[str, JSONValue]:
        return {
            "backend_id": BACKEND_ID,
            "datatype_policy": "rdf-1.1-literals-no-entailment/v1",
            "inconsistency_policy": "reject-release/v1",
            "monotonic": True,
            "negation": "explicit-complement",
            "proof": "release-ground-rule-dag/v1",
            "query_form": "release-pinned-positive-complement/v1",
            "rule_families": ["owlrl:cax-sco", "owlrl:prp-spo2-length-2"],
            "semantic_profile": SEMANTIC_PROFILE,
            "shacl_inference": "none",
            "unique_name_assumption": False,
            "world_assumption": "open",
        }
