# IANA adapter mutation fixtures

The tests append these small Turtle fragments to a temporary copy of the
pinned domain release. They then update the copied source digest and compute a
new trust anchor. This makes the tests reach the semantic gates instead of
failing early on an intentionally stale hash.

The rogue fixtures cover undeclared graph material, unsupported OWL profile
shapes, and conflicts derived by the reference reasoner without a matching
ground rule.
