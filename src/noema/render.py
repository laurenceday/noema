"""Controlled answer rendering that never consumes corpus labels."""

from __future__ import annotations

from dataclasses import dataclass

from noema.canonical import JSONValue
from noema.model import Judgement, JudgementStatus
from noema.query import MappingStatus, QuestionMapping


@dataclass(frozen=True, slots=True)
class RenderedAnswer:
    code: str
    status: str
    text: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {"code": self.code, "status": self.status, "text": self.text}


def render_answer(
    mapping: QuestionMapping,
    judgements: tuple[Judgement, ...],
) -> RenderedAnswer:
    """Render only typed statuses; source and entity labels are never inputs."""
    if mapping.status is MappingStatus.AMBIGUOUS:
        return RenderedAnswer(
            code="refused",
            status="ambiguous",
            text="Refused. More than one formal entity binding remains.",
        )
    if mapping.status is MappingStatus.UNSUPPORTED:
        return RenderedAnswer(
            code="refused",
            status="unsupported",
            text="Refused. The question is outside this release's declared scope.",
        )
    if mapping.operator != "all" or len(judgements) != len(mapping.query_ids):
        return RenderedAnswer(
            code="error",
            status="error",
            text="Error. The answer plan is incomplete.",
        )

    statuses = tuple(judgement.status for judgement in judgements)
    error_statuses = {
        JudgementStatus.AMBIGUOUS,
        JudgementStatus.BOTH,
        JudgementStatus.BUDGET_EXCEEDED,
        JudgementStatus.ERROR,
        JudgementStatus.INCONSISTENT_RELEASE,
        JudgementStatus.UNSUPPORTED,
    }
    if any(status in error_statuses for status in statuses):
        return RenderedAnswer(
            code="error",
            status="error",
            text="Error. A required formal judgement could not be certified.",
        )
    if any(status is JudgementStatus.CONTRADICTED for status in statuses):
        return RenderedAnswer(
            code="no",
            status="contradicted",
            text="No. An explicit complement of a required claim is entailed.",
        )
    if any(status is JudgementStatus.UNKNOWN for status in statuses):
        return RenderedAnswer(
            code="unknown",
            status="unknown",
            text="Unknown. At least one required claim is not derivable either way.",
        )
    if statuses and all(status is JudgementStatus.ENTAILED for status in statuses):
        return RenderedAnswer(
            code="yes",
            status="entailed",
            text="Yes. Every required claim is entailed by the pinned release.",
        )
    return RenderedAnswer(
        code="error",
        status="error",
        text="Error. The answer statuses do not satisfy the all-query plan.",
    )
