"""Ledger error codes and the seven-key error object every ledger rejection carries (spec §7).

This is not the kernel's six-key ``Error``; no kernel error is ever passed through. ``fix``
is ``None`` or exactly one JSON value that clears the error when written at ``field``;
``options`` lists complete candidate values for ``field``; ``context`` is never substituted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class LedgerCode:
    # body faults: exit 3, the caller can change the body
    LEDGER_BAD_BODY = "LEDGER_BAD_BODY"
    LEDGER_BAD_COLUMNS = "LEDGER_BAD_COLUMNS"
    LEDGER_VERSION = "LEDGER_VERSION"
    LEDGER_BAD_KIND = "LEDGER_BAD_KIND"
    LEDGER_BAD_CHARACTER = "LEDGER_BAD_CHARACTER"
    LEDGER_BAD_SUBJECT = "LEDGER_BAD_SUBJECT"
    UNKNOWN_TERM = "UNKNOWN_TERM"
    LEDGER_ALT_ID = "LEDGER_ALT_ID"
    OBSOLETE_TERM = "OBSOLETE_TERM"
    LEDGER_ASPECT_MISMATCH = "LEDGER_ASPECT_MISMATCH"
    UNKNOWN_QUALIFIER = "UNKNOWN_QUALIFIER"
    QUALIFIER_ASPECT_MISMATCH = "QUALIFIER_ASPECT_MISMATCH"
    LEDGER_ECO_UNMAPPED = "LEDGER_ECO_UNMAPPED"
    LEDGER_BAD_REFERENCE = "LEDGER_BAD_REFERENCE"
    LEDGER_REFERENCE_REQUIRED = "LEDGER_REFERENCE_REQUIRED"
    LEDGER_BAD_TAXON = "LEDGER_BAD_TAXON"
    LEDGER_BAD_DATE = "LEDGER_BAD_DATE"
    LEDGER_BAD_OBJECT_TYPE = "LEDGER_BAD_OBJECT_TYPE"
    LEDGER_ASSIGNED_BY = "LEDGER_ASSIGNED_BY"
    LEDGER_MALFORMED = "LEDGER_MALFORMED"
    LEDGER_DUPLICATE = "LEDGER_DUPLICATE"
    LEDGER_DERIVATION_REJECTED = "LEDGER_DERIVATION_REJECTED"
    LEDGER_SORRY_USED = "LEDGER_SORRY_USED"
    LEDGER_SORRY_UNUSED = "LEDGER_SORRY_UNUSED"
    LEDGER_CONCLUSION_MISMATCH = "LEDGER_CONCLUSION_MISMATCH"
    NOT_YET_DISCHARGEABLE = "NOT_YET_DISCHARGEABLE"
    LEDGER_BAD_COMPUTED = "LEDGER_BAD_COMPUTED"
    # integrity and environment: exit 2, raised inside LedgerIntegrityError
    LEDGER_BASE_MISMATCH = "LEDGER_BASE_MISMATCH"
    LEDGER_SIGNERS_MISMATCH = "LEDGER_SIGNERS_MISMATCH"
    LEDGER_WRONG_LEDGER = "LEDGER_WRONG_LEDGER"
    LEDGER_SIGNER_MISMATCH = "LEDGER_SIGNER_MISMATCH"
    LEDGER_UNKNOWN_SIGNER = "LEDGER_UNKNOWN_SIGNER"
    LEDGER_BAD_SIGNATURE = "LEDGER_BAD_SIGNATURE"
    LEDGER_CHAIN_BROKEN = "LEDGER_CHAIN_BROKEN"
    LEDGER_INVALID_ENTRY = "LEDGER_INVALID_ENTRY"
    LEDGER_ROLLBACK = "LEDGER_ROLLBACK"
    LEDGER_UNSUPPORTED_KEY = "LEDGER_UNSUPPORTED_KEY"
    LEDGER_KEY16_COLLISION = "LEDGER_KEY16_COLLISION"
    LEDGER_SIGNING_FAILED = "LEDGER_SIGNING_FAILED"


ALL_LEDGER_CODES: frozenset[str] = frozenset(
    v for k, v in vars(LedgerCode).items() if k.isupper() and isinstance(v, str))

# No change to the body clears these; a retry loop must stop on them (spec §7).
TERMINAL_CODES: frozenset[str] = frozenset({
    LedgerCode.NOT_YET_DISCHARGEABLE, LedgerCode.LEDGER_DUPLICATE, LedgerCode.LEDGER_BASE_MISMATCH})

# §2 checks that do not depend on the base: a signed entry failing one of these is
# LEDGER_INVALID_ENTRY whatever base it names (spec §3, base binding).
BASE_INDEPENDENT_CODES: frozenset[str] = frozenset({
    LedgerCode.LEDGER_BAD_COLUMNS, LedgerCode.LEDGER_VERSION, LedgerCode.LEDGER_BAD_KIND,
    LedgerCode.LEDGER_BAD_CHARACTER, LedgerCode.LEDGER_BAD_SUBJECT, LedgerCode.UNKNOWN_QUALIFIER,
    LedgerCode.LEDGER_BAD_REFERENCE, LedgerCode.LEDGER_REFERENCE_REQUIRED, LedgerCode.LEDGER_BAD_TAXON,
    LedgerCode.LEDGER_BAD_DATE, LedgerCode.LEDGER_BAD_OBJECT_TYPE, LedgerCode.LEDGER_ASSIGNED_BY,
    LedgerCode.LEDGER_MALFORMED})


@dataclass(frozen=True)
class LedgerError:
    code: str
    message: str
    field: str | None
    got: Any = None
    fix: Any = None
    options: tuple[Any, ...] = ()
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "field": self.field, "got": self.got,
                "fix": self.fix, "options": sorted(self.options, key=str), "context": self.context}


class LedgerIntegrityError(Exception):
    """Raised when a ledger cannot be trusted or an append cannot proceed: exit 2, nothing loads."""

    def __init__(self, errors: list[LedgerError]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(f"{e.code}: {e.message}" for e in self.errors))

    def to_json(self) -> dict[str, Any]:
        return {"errors": [e.to_dict() for e in self.errors]}
