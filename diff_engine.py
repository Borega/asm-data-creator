"""Diff engine for ASM Generator.

Compares two GeneratorResult objects and categorises each record as
ADDED, CHANGED, DELETED, or UNCHANGED.

Keys per table:
  students, staff  -> person_id
  courses          -> course_id
  classes          -> class_id
  rosters          -> "{class_id}:{student_id}" composite (stable; NOT roster_id)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asm_generator.config import GeneratorResult


class DiffStatus(Enum):
    ADDED = "added"
    CHANGED = "changed"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


@dataclass
class RowDiff:
    record_id: str
    status: DiffStatus
    current: dict | None    # None for DELETED rows
    snapshot: dict | None   # None for ADDED rows


@dataclass
class TableDiff:
    rows: list[RowDiff] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(1 for r in self.rows if r.status == DiffStatus.ADDED)

    @property
    def changed(self) -> int:
        return sum(1 for r in self.rows if r.status == DiffStatus.CHANGED)

    @property
    def deleted(self) -> int:
        return sum(1 for r in self.rows if r.status == DiffStatus.DELETED)

    @property
    def unchanged(self) -> int:
        return sum(1 for r in self.rows if r.status == DiffStatus.UNCHANGED)


@dataclass
class DiffResult:
    students: TableDiff = field(default_factory=TableDiff)
    staff: TableDiff = field(default_factory=TableDiff)
    courses: TableDiff = field(default_factory=TableDiff)
    classes: TableDiff = field(default_factory=TableDiff)
    rosters: TableDiff = field(default_factory=TableDiff)


def _diff_table(
    current_rows: list[dict],
    snapshot_rows: list[dict] | None,
    key_fn,
    eq_fn=None,
) -> TableDiff:
    """Compute a TableDiff for a single table.

    Args:
        current_rows: Records from the current GeneratorResult.
        snapshot_rows: Records from the snapshot GeneratorResult, or None.
        key_fn: Callable that extracts a stable string key from a row dict.
        eq_fn: Optional callable(curr_row, snap_row) -> bool for equality check.
               Defaults to full dict equality (curr_row == snap_row).
               Used for rosters to exclude roster_id from equality comparison.
    """
    if eq_fn is None:
        eq_fn = lambda c, s: c == s

    table = TableDiff()

    if snapshot_rows is None:
        # No prior snapshot -> every record is ADDED
        for row in current_rows:
            table.rows.append(RowDiff(
                record_id=key_fn(row),
                status=DiffStatus.ADDED,
                current=row,
                snapshot=None,
            ))
        return table

    snap_index: dict[str, dict] = {key_fn(r): r for r in snapshot_rows}
    curr_index: dict[str, dict] = {key_fn(r): r for r in current_rows}

    # Records in current: ADDED or CHANGED or UNCHANGED
    for key, curr_row in curr_index.items():
        if key not in snap_index:
            table.rows.append(RowDiff(
                record_id=key,
                status=DiffStatus.ADDED,
                current=curr_row,
                snapshot=None,
            ))
        else:
            snap_row = snap_index[key]
            if eq_fn(curr_row, snap_row):
                table.rows.append(RowDiff(
                    record_id=key,
                    status=DiffStatus.UNCHANGED,
                    current=curr_row,
                    snapshot=snap_row,
                ))
            else:
                table.rows.append(RowDiff(
                    record_id=key,
                    status=DiffStatus.CHANGED,
                    current=curr_row,
                    snapshot=snap_row,
                ))

    # Records only in snapshot: DELETED
    for key, snap_row in snap_index.items():
        if key not in curr_index:
            table.rows.append(RowDiff(
                record_id=key,
                status=DiffStatus.DELETED,
                current=None,
                snapshot=snap_row,
            ))

    return table


def compute_diff(
    current: "GeneratorResult",
    snapshot: "GeneratorResult | None",
) -> DiffResult:
    """Compare current GeneratorResult against a snapshot.

    When snapshot is None, all records in current are categorised as ADDED.
    No DELETED records are produced when snapshot is None.

    Returns a DiffResult with one TableDiff per table type.
    """
    snap_students = snapshot.students if snapshot is not None else None
    snap_staff    = snapshot.staff    if snapshot is not None else None
    snap_courses  = snapshot.courses  if snapshot is not None else None
    snap_classes  = snapshot.classes  if snapshot is not None else None
    snap_rosters  = snapshot.rosters  if snapshot is not None else None

    return DiffResult(
        students=_diff_table(current.students, snap_students, lambda r: r["person_id"]),
        staff=_diff_table(current.staff,       snap_staff,    lambda r: r["person_id"]),
        courses=_diff_table(current.courses,   snap_courses,  lambda r: r["course_id"]),
        classes=_diff_table(current.classes,   snap_classes,  lambda r: r["class_id"]),
        rosters=_diff_table(
            current.rosters,
            snap_rosters,
            lambda r: f"{r['class_id']}:{r['student_id']}",
            # Exclude roster_id from equality: enrollment identity is class+student.
            eq_fn=lambda c, s: {k: v for k, v in c.items() if k != "roster_id"}
                             == {k: v for k, v in s.items() if k != "roster_id"},
        ),
    )
