# IANA adapter mutation fixtures

The tests append these small Turtle fragments to a temporary copy of the
pinned domain release. They update the copied source digest and compute a new
trust anchor, which lets each test reach the semantic check instead of failing
early on an intentionally stale hash.

The rogue fixtures cover undeclared graph material, unsupported OWL profile
shapes, and conflicts derived by the reference reasoner without a matching
ground rule.
