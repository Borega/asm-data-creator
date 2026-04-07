"""Diff Review page — five-tab colour-coded confirmation table."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget,
    QHeaderView, QTableWidgetItem,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF,
    Pivot, PrimaryPushButton, PushButton, TableWidget,
)

from diff_engine import DiffResult, DiffStatus, RowDiff

if TYPE_CHECKING:
    from gui.app_controller import AppController

# ---- Row colors ----
_COLOR_ADDED = QColor("#d4edda")
_COLOR_CHANGED = QColor("#fff3cd")
_COLOR_DELETED = QColor("#f8d7da")
_COLOR_TEXT = QColor("#000000")  # force black text on all colored rows (dark theme compat)

# ---- Tab configuration: (tab_key, tab_label, data_attr, key_columns) ----
_TAB_DEFS = [
    ("students", "Students", "students", ["person_id", "first_name", "last_name", "grade_level"]),
    ("staff",    "Staff",    "staff",    ["person_id", "first_name", "last_name"]),
    ("courses",  "Courses",  "courses",  ["course_id", "course_name", "location_id"]),
    ("classes",  "Classes",  "classes",  ["class_id", "course_id", "teacher_id", "grade_level"]),
    ("rosters",  "Rosters",  "rosters",  ["roster_id", "class_id", "student_id"]),
]


@dataclass
class _RowMeta:
    """Runtime metadata for a table row."""
    row_diff: RowDiff
    table_row: int
    reviewed: bool          # True after first checkbox interaction (DELETED rows only)
    checkbox_item: QTableWidgetItem | None  # None for ADDED/UNCHANGED


class _TabWidget(QWidget):
    """Single tab: toolbar + TableWidget for one entity type."""

    def __init__(self, tab_key: str, key_columns: list[str], parent=None):
        super().__init__(parent)
        self.tab_key = tab_key
        self.key_columns = key_columns
        self._all_columns = key_columns + ["Status", ""]  # "" = checkbox col header

        # State
        self._row_metas: list[_RowMeta] = []
        self._unchanged_hidden = True

        # Counts (set by populate)
        self.n_added = 0
        self.n_changed = 0
        self.n_deleted = 0
        self.n_unchanged = 0

        self._gate_callback = None

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        # --- Toolbar row ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._summary_label = CaptionLabel("")
        toolbar.addWidget(self._summary_label)
        toolbar.addStretch()

        self._toggle_btn = PushButton("Show unchanged")
        self._toggle_btn.clicked.connect(self._toggle_unchanged)
        toolbar.addWidget(self._toggle_btn)

        self._approve_all_btn = PushButton(FIF.ACCEPT, "Approve All Changes")
        self._approve_all_btn.clicked.connect(self._approve_all_changes)
        toolbar.addWidget(self._approve_all_btn)

        layout.addLayout(toolbar)

        # --- Table ---
        self._table = TableWidget(self)
        self._table.setColumnCount(len(self._all_columns))
        self._table.setHorizontalHeaderLabels(self._all_columns)
        self._table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)

        hdr = self._table.horizontalHeader()
        for i in range(len(self.key_columns)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        status_idx = len(self.key_columns)
        hdr.setSectionResizeMode(status_idx, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(status_idx, 90)
        chk_idx = status_idx + 1
        hdr.setSectionResizeMode(chk_idx, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(chk_idx, 48)

        layout.addWidget(self._table, stretch=1)

    def set_gate_callback(self, cb) -> None:
        """Callback to call whenever a DELETED checkbox is toggled."""
        self._gate_callback = cb

    def populate(self, table_diff) -> None:
        """Populate table from a TableDiff. Resets all state."""
        self._row_metas.clear()
        self.n_added = self.n_changed = self.n_deleted = self.n_unchanged = 0
        self._unchanged_hidden = True
        self._toggle_btn.setText("Show unchanged")

        rows = table_diff.rows
        self._table.setRowCount(len(rows))

        for row_idx, row_diff in enumerate(rows):
            self._populate_row(row_idx, row_diff)

        self._update_summary()
        self._approve_all_btn.setVisible(self.n_changed > 0)
        self._toggle_btn.setVisible(self.n_unchanged > 0)

    def _populate_row(self, row_idx: int, row_diff: RowDiff) -> None:
        status = row_diff.status
        data = row_diff.current if status != DiffStatus.DELETED else row_diff.snapshot
        key_cols = self.key_columns

        color_map = {
            DiffStatus.ADDED: _COLOR_ADDED,
            DiffStatus.CHANGED: _COLOR_CHANGED,
            DiffStatus.DELETED: _COLOR_DELETED,
            DiffStatus.UNCHANGED: None,
        }
        bg_color = color_map[status]

        for col_idx, col_name in enumerate(key_cols):
            val = str(data.get(col_name, "") if data else "")
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg_color:
                item.setBackground(bg_color)
                item.setForeground(_COLOR_TEXT)
            self._table.setItem(row_idx, col_idx, item)

        status_item = QTableWidgetItem(status.value.upper())
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if bg_color:
            status_item.setBackground(bg_color)
            status_item.setForeground(_COLOR_TEXT)
        status_col = len(key_cols)
        self._table.setItem(row_idx, status_col, status_item)

        chk_col = status_col + 1
        chk_item = None

        if status == DiffStatus.CHANGED:
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Checked)
            if bg_color:
                chk_item.setBackground(bg_color)
                chk_item.setForeground(_COLOR_TEXT)
            chk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row_idx, chk_col, chk_item)
            self.n_changed += 1

        elif status == DiffStatus.DELETED:
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            if bg_color:
                chk_item.setBackground(bg_color)
                chk_item.setForeground(_COLOR_TEXT)
            chk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row_idx, chk_col, chk_item)
            self.n_deleted += 1

        elif status == DiffStatus.ADDED:
            self.n_added += 1
            placeholder = QTableWidgetItem("")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if bg_color:
                placeholder.setBackground(bg_color)
                placeholder.setForeground(_COLOR_TEXT)
            self._table.setItem(row_idx, chk_col, placeholder)

        elif status == DiffStatus.UNCHANGED:
            self.n_unchanged += 1
            placeholder = QTableWidgetItem("")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row_idx, chk_col, placeholder)
            self._table.setRowHidden(row_idx, True)

        meta = _RowMeta(
            row_diff=row_diff,
            table_row=row_idx,
            reviewed=(status != DiffStatus.DELETED),
            checkbox_item=chk_item,
        )
        self._row_metas.append(meta)

    def disconnect_item_changed(self) -> None:
        """Safely disconnect itemChanged (call before repopulating the table)."""
        try:
            self._table.itemChanged.disconnect()
        except (RuntimeError, TypeError):
            pass

    def wire_item_changed(self) -> None:
        """Connect itemChanged after all rows are populated (avoids mid-populate firing)."""
        self._table.itemChanged.connect(self._on_item_changed)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        row_idx = item.row()
        if row_idx >= len(self._row_metas):
            return
        meta = self._row_metas[row_idx]
        if meta.row_diff.status == DiffStatus.DELETED and not meta.reviewed:
            meta.reviewed = True
            if self._gate_callback:
                self._gate_callback()

    def _update_summary(self) -> None:
        self._summary_label.setText(
            f"{self.n_added} added · {self.n_changed} changed · "
            f"{self.n_deleted} deleted · {self.n_unchanged} unchanged"
        )

    def _toggle_unchanged(self) -> None:
        self._unchanged_hidden = not self._unchanged_hidden
        for meta in self._row_metas:
            if meta.row_diff.status == DiffStatus.UNCHANGED:
                self._table.setRowHidden(meta.table_row, self._unchanged_hidden)
        self._toggle_btn.setText(
            "Hide unchanged" if not self._unchanged_hidden else "Show unchanged"
        )

    def _approve_all_changes(self) -> None:
        """Check all CHANGED checkboxes in this tab."""
        self._table.blockSignals(True)
        for meta in self._row_metas:
            if meta.row_diff.status == DiffStatus.CHANGED and meta.checkbox_item:
                meta.checkbox_item.setCheckState(Qt.CheckState.Checked)
        self._table.blockSignals(False)

    def count_unreviewed_deletions(self) -> int:
        return sum(
            1 for m in self._row_metas
            if m.row_diff.status == DiffStatus.DELETED and not m.reviewed
        )

    def get_approved_records(self) -> list[dict]:
        """Return records approved for this tab according to checkbox decisions.

        - ADDED       → always include current
        - UNCHANGED   → always include current
        - CHANGED + checked   → include current (new value)
        - CHANGED + unchecked → include snapshot (old value)
        - DELETED + checked   → EXCLUDED (confirmed deletion)
        - DELETED + unchecked → include snapshot (preserved)
        """
        approved = []
        for meta in self._row_metas:
            rd = meta.row_diff
            if rd.status == DiffStatus.ADDED:
                approved.append(dict(rd.current))
            elif rd.status == DiffStatus.UNCHANGED:
                approved.append(dict(rd.current))
            elif rd.status == DiffStatus.CHANGED:
                checked = (
                    meta.checkbox_item is not None
                    and meta.checkbox_item.checkState() == Qt.CheckState.Checked
                )
                approved.append(dict(rd.current if checked else rd.snapshot))
            elif rd.status == DiffStatus.DELETED:
                checked = (
                    meta.checkbox_item is not None
                    and meta.checkbox_item.checkState() == Qt.CheckState.Checked
                )
                if not checked:
                    approved.append(dict(rd.snapshot))
        return approved


class DiffReviewPage(QWidget):
    export_requested = pyqtSignal()

    def __init__(self, controller: "AppController | None" = None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DiffReviewPage")   # Must be set before addSubInterface

        self._controller = controller
        self._tab_widgets: list[_TabWidget] = []
        self._diff_result: DiffResult | None = None

        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)

        # --- Placeholder ---
        self._placeholder = BodyLabel("No diff loaded. Run generation on the Input page first.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._placeholder, alignment=Qt.AlignmentFlag.AlignCenter)

        # --- Diff content (hidden until load_diff called) ---
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        # Pivot tab bar
        self._pivot = Pivot(self)
        content_layout.addWidget(self._pivot)

        # Stacked widget
        self._stack = QStackedWidget(self)
        content_layout.addWidget(self._stack, stretch=1)

        # Build tabs
        for tab_key, tab_label, _data_attr, key_columns in _TAB_DEFS:
            tab_w = _TabWidget(tab_key, key_columns)
            tab_w.set_gate_callback(self._check_export_gate)
            self._tab_widgets.append(tab_w)
            self._stack.addWidget(tab_w)
            self._pivot.addItem(
                routeKey=tab_key,
                text=tab_label,
                onClick=lambda checked=False, w=tab_w: self._stack.setCurrentWidget(w),
            )

        # Activate first tab
        self._pivot.setCurrentItem(_TAB_DEFS[0][0])

        # Bottom bar: Export ZIP
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        self._export_btn = PrimaryPushButton(FIF.SAVE, "Export ZIP")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export_clicked)
        bottom_bar.addWidget(self._export_btn)
        content_layout.addLayout(bottom_bar)

        root.addWidget(self._content)
        self._content.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_diff(self, diff_result: DiffResult) -> None:
        """Populate all tabs from diff_result. Resets all state."""
        self._diff_result = diff_result

        tab_map = {
            "students": diff_result.students,
            "staff":    diff_result.staff,
            "courses":  diff_result.courses,
            "classes":  diff_result.classes,
            "rosters":  diff_result.rosters,
        }

        for tab_w in self._tab_widgets:
            tab_w.disconnect_item_changed()
            tab_w.populate(tab_map[tab_w.tab_key])
            tab_w.wire_item_changed()

        # Jump to Students tab
        self._pivot.setCurrentItem(_TAB_DEFS[0][0])
        self._stack.setCurrentWidget(self._tab_widgets[0])

        self._export_btn.setEnabled(False)
        self._placeholder.hide()
        self._content.show()

        # If no deletions at all, enable export immediately
        self._check_export_gate()

    def get_approved_records(self) -> dict[str, list[dict]]:
        """Return approved records for all five tables."""
        result = {}
        for tab_w, (_tab_key, _label, data_attr, _cols) in zip(self._tab_widgets, _TAB_DEFS):
            result[data_attr] = tab_w.get_approved_records()
        return result

    def reset(self) -> None:
        """Return to placeholder state (called after successful export)."""
        self._diff_result = None
        self._content.hide()
        self._export_btn.setEnabled(False)
        self._placeholder.show()

    # ------------------------------------------------------------------
    # Export gate
    # ------------------------------------------------------------------

    def _check_export_gate(self) -> None:
        total_unreviewed = sum(
            tw.count_unreviewed_deletions() for tw in self._tab_widgets
        )
        self._export_btn.setEnabled(total_unreviewed == 0)

    # ------------------------------------------------------------------
    # Export ZIP
    # ------------------------------------------------------------------

    def _on_export_clicked(self) -> None:
        self.export_requested.emit()
