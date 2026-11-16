"""The Mission Brief: what an Interview leaves in the Mission Manifest (``mission.brief``).

An Interview ends in a brief the user confirmed. The brief is part of the ``mission/v2``
manifest, so it is sealed with the revision the manifest produced and read back with it: the
kind of work, the request and what finished looks like in the requester's own words, the
questions asked and the answers given, what was ruled out and who asked. Nothing here is
interpreted: the text is recorded as written and quoted, never executed. The Purpose Card
every node receives quotes it (``application/authoring/purpose_card.py``).

Bounded, because the brief travels in every revision and its request reaches every node's
instructions. A credential is never part of a request: text shaped like one is refused where
the manifest is parsed, with the pattern class that matched and never the value.

Pure: no I/O. It names no application; the purpose vocabulary is about the kind of work.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from mission_control.domain.frames.body import redact_text

BRIEF_REQUEST_MAX: Final = 2_000
BRIEF_DONE_MEANS_MAX: Final = 1_000
BRIEF_ANSWERS_MAX: Final = 12
BRIEF_QUESTION_MAX: Final = 400
BRIEF_ANSWER_MAX: Final = 1_200
BRIEF_OUT_OF_SCOPE_MAX: Final = 8
BRIEF_OUT_OF_SCOPE_ITEM_MAX: Final = 400
BRIEF_ACTOR_MAX: Final = 200


class MissionPurpose(StrEnum):
    """What kind of work a mission is. Every node is told (the Purpose Card)."""

    RESEARCH = "research"
    CONTENT = "content"
    SYSTEM = "system"
    OTHER = "other"


# One line per purpose, as a node reads it.
PURPOSE_MEANINGS: Final[dict[MissionPurpose, str]] = {
    MissionPurpose.RESEARCH: "researching for the application",
    MissionPurpose.CONTENT: "building content for the application",
    MissionPurpose.SYSTEM: "improving the system itself",
    MissionPurpose.OTHER: "other work; the request says what",
}

# The frame redactor's `bearer` and `basic` shapes match ordinary prose ("basic
# authentication"), so a brief refuses them only where the value looks like a token.
_TOKEN_SHAPES: Final[dict[str, re.Pattern[str]]] = {
    "bearer_token": re.compile(r"(?i)\bbearer\s+(?=\S*\d)[A-Za-z0-9._~+/=-]{16,}"),
    "basic_auth": re.compile(r"(?i)\bbasic\s+(?=\S*\d)[A-Za-z0-9+/=]{16,}"),
}


def secret_like(text: str) -> tuple[str, ...]:
    """The credential shapes found in ``text``, by pattern class (never the value): what the
    frame redactor would remove before a transcript stores it (``domain/frames/body.py``)."""

    found = dict.fromkeys(item.pattern for item in redact_text(text)[1])
    return tuple(
        name for name in found if name not in _TOKEN_SHAPES or _TOKEN_SHAPES[name].search(text)
    )


def _words(value: str) -> str:
    if not value.strip():
        raise ValueError("must hold words, not only white space")
    shapes = secret_like(value)
    if shapes:
        raise ValueError(
            f"holds secret-like content ({', '.join(shapes)}); a brief records the user's "
            "words, never a credential"
        )
    return value


RequestText = Annotated[
    str, StringConstraints(min_length=1, max_length=BRIEF_REQUEST_MAX), AfterValidator(_words)
]
DoneMeansText = Annotated[
    str, StringConstraints(min_length=1, max_length=BRIEF_DONE_MEANS_MAX), AfterValidator(_words)
]
QuestionText = Annotated[
    str, StringConstraints(min_length=1, max_length=BRIEF_QUESTION_MAX), AfterValidator(_words)
]
AnswerText = Annotated[
    str, StringConstraints(min_length=1, max_length=BRIEF_ANSWER_MAX), AfterValidator(_words)
]
OutOfScopeText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=BRIEF_OUT_OF_SCOPE_ITEM_MAX),
    AfterValidator(_words),
]
ActorRef = Annotated[
    str, StringConstraints(min_length=1, max_length=BRIEF_ACTOR_MAX, pattern=r"^\S+$")
]


class BriefModel(BaseModel):
    """Strict and immutable, as every manifest shape is: an unknown key is refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BriefAnswer(BriefModel):
    """One question of the Interview and the user's answer, in the user's words."""

    question: QuestionText
    answer: AnswerText


class MissionBrief(BriefModel):
    """``mission.brief``: the Interview's result, recorded with the mission it produced."""

    purpose: MissionPurpose
    # The user's request in their own words.
    request: RequestText
    # The Interview, in order.
    answers: tuple[BriefAnswer, ...] = Field(default=(), max_length=BRIEF_ANSWERS_MAX)
    # What the user said finished looks like.
    done_means: DoneMeansText | None = None
    # What the user ruled out.
    out_of_scope: tuple[OutOfScopeText, ...] = Field(default=(), max_length=BRIEF_OUT_OF_SCOPE_MAX)
    # An actor reference; absent, compile records the principal it runs for (the submitting
    # principal at submit).
    requested_by: ActorRef | None = None

    def requested_by_default(self, actor_ref: str) -> MissionBrief:
        """The brief with ``requested_by`` set to ``actor_ref`` where the author left it out."""

        if self.requested_by is not None:
            return self
        return self.model_copy(update={"requested_by": actor_ref})


__all__ = [
    "BRIEF_ACTOR_MAX",
    "BRIEF_ANSWERS_MAX",
    "BRIEF_ANSWER_MAX",
    "BRIEF_DONE_MEANS_MAX",
    "BRIEF_OUT_OF_SCOPE_ITEM_MAX",
    "BRIEF_OUT_OF_SCOPE_MAX",
    "BRIEF_QUESTION_MAX",
    "BRIEF_REQUEST_MAX",
    "PURPOSE_MEANINGS",
    "BriefAnswer",
    "BriefModel",
    "MissionBrief",
    "MissionPurpose",
    "secret_like",
]
