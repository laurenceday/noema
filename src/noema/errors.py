"""Fail-closed error types used by the Noema kernel."""


class NoemaError(Exception):
    """Base class for expected Noema integrity failures."""


class CanonicalizationError(NoemaError):
    """Input cannot be represented by Noema's canonical JSON profile."""


class ReleaseValidationError(NoemaError):
    """A release is malformed, stale, or internally inconsistent."""


class JudgementValidationError(NoemaError):
    """A typed judgement violates its status contract."""


class ProofVerificationError(NoemaError):
    """A proof cannot be replayed against its pinned release."""


class EvidenceProjectionError(NoemaError):
    """Verified proof leaves cannot be mapped to exact evidence."""


class QuestionMappingError(NoemaError):
    """A deterministic question catalogue or mapping is malformed."""


class AnswerVerificationError(NoemaError):
    """An answer certificate cannot be independently reconstructed."""


class ProbeValidationError(NoemaError):
    """A Null-prime evaluation or hypothetical mutation is malformed."""
