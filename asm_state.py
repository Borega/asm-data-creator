"""What ASM actually holds for a person, and how confident we can be.

The Diff Review labels a row ADDED or DELETED by comparing against the local
snapshot. That is a statement about a *file*, not about ASM, and the two come
apart whenever the snapshot is stale — written before a schema change, before
a school year rolled over, or before someone edited ASM directly.

When they disagree, the review's own labels mislead in both directions:

- an ADDED row may already hold an active ASM account, so holding it back
  deactivates that account instead of skipping a creation
- a DELETED row may name an id ASM never had, so keeping it creates a new
  account rather than preserving one

Both have been observed in practice; the second created five duplicate staff
accounts in one upload that ASM reported as fully successful.

So a row's decision needs a second question answered: does ASM hold this person
right now? This module answers it in three states, and refuses to guess.
"""
from __future__ import annotations

LIVE = "live"          # ASM has an active account — holding the row back deactivates it
INACTIVE = "inactive"  # ASM knows the id but it is deactivated — re-sending revives it
UNKNOWN = "unknown"    # no trustworthy evidence either way


class AsmState:
    """Answers 'does ASM hold this person?' from the best evidence available.

    Evidence, strongest first:

    1. An ASM activity log. This is ASM's own record, so it outranks everything
       — including for accounts created outside this app. It is a delta though,
       so it only speaks about the people it names.
    2. A snapshot whose provenance says it was uploaded. Those rows were handed
       to ASM and the sync accepted them, so membership is reliable both ways:
       present means live, absent means genuinely new.
    3. Nothing. Every answer is UNKNOWN, and the caller must not present a
       held-back row as safe.
    """

    def __init__(
        self,
        log_state: dict[str, bool] | None = None,
        snapshot_ids: set[str] | None = None,
        snapshot_confirmed: bool = False,
    ) -> None:
        self._log = log_state or {}
        # An unconfirmed snapshot is not weak evidence, it is no evidence: a
        # stale snapshot is internally consistent and still describes a file
        # rather than ASM.
        self._snapshot = snapshot_ids if (snapshot_confirmed and snapshot_ids is not None) else None

    @property
    def has_evidence(self) -> bool:
        return bool(self._log) or self._snapshot is not None

    def state(self, person_id: str) -> str:
        if person_id in self._log:
            return LIVE if self._log[person_id] else INACTIVE
        if self._snapshot is not None:
            return LIVE if person_id in self._snapshot else INACTIVE
        return UNKNOWN

    def label(self, person_id: str) -> str:
        """Short cell text for the review table."""
        return {LIVE: "Yes", INACTIVE: "No", UNKNOWN: "?"}[self.state(person_id)]

    def holding_back_is_destructive(self, person_id: str) -> bool:
        """True when leaving this ADDED row out would deactivate a real account.

        UNKNOWN counts as destructive. The asymmetry is the point: being wrong
        in this direction costs a pointless confirmation click, being wrong the
        other way silently switches off an account someone is using.
        """
        return self.state(person_id) in (LIVE, UNKNOWN)

    def keeping_is_destructive(self, person_id: str) -> bool:
        """True when re-sending this DELETED row might create a duplicate account.

        If ASM has no live account for the id, sending it again does not 'keep'
        anything — it creates a new person. That is how five duplicate staff
        accounts were once created in a single successful upload.
        """
        return self.state(person_id) in (INACTIVE, UNKNOWN)
