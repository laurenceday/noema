# IANA adapter mutation fixtures

The tests append these small Turtle fragments to a temporary copy of the
pinned domain release. They then update the copied source digest and compute a
new trust anchor. This makes the tests reach the semantic gates instead of
failing early on an intentionally stale hash.
