# IANA media types with OWL 2 RL

This domain will model a pinned slice of the IANA Media Types and Structured
Syntax Suffix registries as RDF and a constrained OWL 2 RL theory. Its first
competency question asks whether `application/problem+json` is registered and
uses JSON representation syntax.

The release will preserve separate evidence mappings for the media-type row
and the `+json` suffix rule. It will also keep open-world absence distinct
from an explicit negative claim and will reject conclusions about payload
safety or validity.

RDFLib 7.6.0 parses the graphs, OWL-RL 7.6.2 materialises the selected rule
fragment, and pySHACL 0.40.1 validates graph shape. These libraries do not
emit the replayable proof certificates Noema requires. A later adapter will
implement the declared fragment, proof production, and independent replay.
