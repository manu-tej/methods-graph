"""Error codes and the error record every rejection carries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class Code:
    MALFORMED = "MALFORMED"
    UNKNOWN_RULE = "UNKNOWN_RULE"
    DUPLICATE_STEP = "DUPLICATE_STEP"
    UNKNOWN_STEP_REF = "UNKNOWN_STEP_REF"
    STEP_ORDER = "STEP_ORDER"
    PREMISE_ARITY = "PREMISE_ARITY"
    ROOT_MISMATCH = "ROOT_MISMATCH"
    UNKNOWN_TERM = "UNKNOWN_TERM"
    OBSOLETE_TERM = "OBSOLETE_TERM"
    ALT_ID_IN_KERNEL = "ALT_ID_IN_KERNEL"
    UNKNOWN_SUBJECT = "UNKNOWN_SUBJECT"
    UNKNOWN_QUALIFIER = "UNKNOWN_QUALIFIER"
    QUALIFIER_ASPECT_MISMATCH = "QUALIFIER_ASPECT_MISMATCH"
    AXIOM_NOT_FOUND = "AXIOM_NOT_FOUND"
    EDGE_NOT_FOUND = "EDGE_NOT_FOUND"
    NAMESPACE_CROSSED = "NAMESPACE_CROSSED"
    NEGATED_PREMISE = "NEGATED_PREMISE"
    PREMISE_MISMATCH = "PREMISE_MISMATCH"
    CONCLUSION_MISMATCH = "CONCLUSION_MISMATCH"
    SORRY_MALFORMED = "SORRY_MALFORMED"
    SORRY_NEGATED = "SORRY_NEGATED"


ALL_CODES: frozenset[str] = frozenset(
    v for k, v in vars(Code).items() if k.isupper() and isinstance(v, str))


@dataclass(frozen=True)
class Error:
    code: str
    message: str
    step: str | None = None
    # The step's position in the derivation (-1 for a goal-level error), used only to sort
    # the verdict's error list. Never serialized: `to_dict()` keeps exactly the six
    # documented keys, so a step id that happens to look like "#3" can't be mistaken for one.
    position: int = -1
    expected: Any = None
    actual: Any = None
    suggestions: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "code": self.code, "message": self.message,
                "expected": self.expected, "actual": self.actual,
                "suggestions": list(self.suggestions)}
