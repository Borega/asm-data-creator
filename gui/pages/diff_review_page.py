"""Diff Review page — five-tab colour-coded confirmation table."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6.QtCore import QItemSelectionModel, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    MessageBox,
    Pivot,
    PrimaryPushButton,
    PushButton,
    TableWidget,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from asm_state import UNKNOWN, AsmState
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
    (
        "students",
        "Students",
        "students",
        [
            "person_id",
            "first_name",
            "middle_name",
            "last_name",
            "grade_level",
            "email_address",
            "sis_username",
        ],
    ),
    (
        "staff",
        "Staff",
        "staff",
        [
            "person_id",
            "person_number",
            "first_name",
            "middle_name",
            "last_name",
            "email_address",
            "sis_username",
        ],
    ),
    ("courses", "Courses", "courses", ["course_id", "course_name", "location_id"]),
    ("classes", "Classes", "classes", ["class_id", "class_number", "course_id", "instructor_id", "location_id"]),
    ("rosters", "Rosters", "rosters", ["roster_id", "class_id", "student_id"]),
]


@dataclass
class _RowMeta:
    """Runtime metadata for a table row."""
    row_diff: RowDiff
    table_row: int
    reviewed: bool          # True after first checkbox interaction (DELETED rows only)
    checkbox_item: QTableWidgetItem | None  # None for UNCHANGED


class _TabWidget(QWidget):
    """Single tab: toolbar + TableWidget for one entity type."""

    def __init__(self, tab_key: str, key_columns: list[str], parent=None):
        super().__init__(parent)
        self.tab_key = tab_key
        self.key_columns = key_columns
        # Only people have an ASM account whose existence the decision can
        # destroy, so only those tabs carry the evidence column.
        self.shows_asm_state = tab_key in ("students", "staff")
        self._asm_state = AsmState()
        # The box means a different thing per status (create / take the new
        # value / delete), so the header names the one thing they share.
        self._all_columns = key_columns + ["Status", "Apply"]
        if self.shows_asm_state:
            self._all_columns += ["In ASM"]

        # State
        self._row_metas: list[_RowMeta] = []
        self._unchanged_hidden = True
        self._filter_text = ""

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

        # --- Filter + selection actions ---
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._filter_edit = LineEdit()
        self._filter_edit.setPlaceholderText("Filter rows… (matches any column)")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        action_row.addWidget(self._filter_edit, stretch=1)

        self._filter_count_label = CaptionLabel("")
        action_row.addWidget(self._filter_count_label)

        # Selection was previously inert: rows could be selected but nothing
        # acted on them. These two apply a decision to whatever is selected.
        self._approve_selected_btn = PushButton(FIF.ACCEPT, "Approve selected")
        self._approve_selected_btn.setToolTip(
            "Changed → take the new value.  Deleted → confirm the deletion."
        )
        self._approve_selected_btn.clicked.connect(lambda: self._decide_selected(approve=True))
        action_row.addWidget(self._approve_selected_btn)

        self._reject_selected_btn = PushButton(FIF.CANCEL, "Keep selected")
        self._reject_selected_btn.setToolTip(
            "Changed → keep the old value.  Deleted → keep the record.\n"
            "Also marks the rows reviewed, so the export gate is satisfied."
        )
        self._reject_selected_btn.clicked.connect(lambda: self._decide_selected(approve=False))
        action_row.addWidget(self._reject_selected_btn)

        layout.addLayout(action_row)

        # --- Toolbar row ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._summary_label = CaptionLabel("")
        toolbar.addWidget(self._summary_label)
        toolbar.addStretch()

        self._select_all_added_btn = PushButton("Select All Added")
        self._select_all_added_btn.clicked.connect(
            lambda: self._toggle_status_row_selection(DiffStatus.ADDED)
        )
        toolbar.addWidget(self._select_all_added_btn)

        self._select_all_changed_btn = PushButton("Select All Changed")
        self._select_all_changed_btn.clicked.connect(
            lambda: self._toggle_status_row_selection(DiffStatus.CHANGED)
        )
        toolbar.addWidget(self._select_all_changed_btn)

        self._select_all_deleted_btn = PushButton("Select All Deleted")
        self._select_all_deleted_btn.clicked.connect(
            lambda: self._toggle_status_row_selection(DiffStatus.DELETED)
        )
        toolbar.addWidget(self._select_all_deleted_btn)

        self._toggle_btn = PushButton("Show unchanged")
        self._toggle_btn.clicked.connect(self._toggle_unchanged)
        toolbar.addWidget(self._toggle_btn)

        self._approve_all_btn = PushButton(FIF.ACCEPT, "Approve All Changes")
        self._approve_all_btn.clicked.connect(self._approve_all_changes)
        toolbar.addWidget(self._approve_all_btn)

        self._approve_all_del_btn = PushButton("Approve All Deletions")
        self._approve_all_del_btn.clicked.connect(self._approve_all_deletions)
        toolbar.addWidget(self._approve_all_del_btn)

        layout.addLayout(toolbar)

        # --- Table ---
        self._table = TableWidget(self)
        self._table.setColumnCount(len(self._all_columns))
        self._table.setHorizontalHeaderLabels(self._all_columns)
        self._table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(TableWidget.SelectionMode.ExtendedSelection)
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

    def set_row_height(self, px: int) -> None:
        self._table.verticalHeader().setDefaultSectionSize(px)

    def populate(self, table_diff, asm_state: AsmState | None = None) -> None:
        """Populate table from a TableDiff. Resets all state."""
        self._asm_state = asm_state or AsmState()
        self._row_metas.clear()
        self.n_added = self.n_changed = self.n_deleted = self.n_unchanged = 0
        self._unchanged_hidden = True
        self._toggle_btn.setText("Show unchanged")

        self._filter_text = ""
        self._filter_edit.blockSignals(True)
        self._filter_edit.clear()
        self._filter_edit.blockSignals(False)

        rows = table_diff.rows
        self._table.setRowCount(len(rows))

        for row_idx, row_diff in enumerate(rows):
            self._populate_row(row_idx, row_diff)

        self._refresh_row_visibility()
        self._update_summary()
        self._select_all_added_btn.setVisible(self.n_added > 0)
        self._select_all_changed_btn.setVisible(self.n_changed > 0)
        self._select_all_deleted_btn.setVisible(self.n_deleted > 0)
        self._approve_all_btn.setVisible(self.n_changed > 0)
        self._approve_all_del_btn.setVisible(self.n_deleted > 0)
        self._toggle_btn.setVisible(self.n_unchanged > 0)

    def _populate_row(self, row_idx: int, row_diff: RowDiff) -> None:
        status = row_diff.status
        data = row_diff.current if status != DiffStatus.DELETED else row_diff.snapshot
        curr = row_diff.current or {}
        snap = row_diff.snapshot or {}
        key_cols = self.key_columns

        color_map = {
            DiffStatus.ADDED: _COLOR_ADDED,
            DiffStatus.CHANGED: _COLOR_CHANGED,
            DiffStatus.DELETED: _COLOR_DELETED,
            DiffStatus.UNCHANGED: None,
        }
        bg_color = color_map[status]

        for col_idx, col_name in enumerate(key_cols):
            if status == DiffStatus.CHANGED:
                old_val = str(snap.get(col_name, ""))
                new_val = str(curr.get(col_name, ""))
                val = new_val if old_val == new_val else f"Before: {old_val} | After: {new_val}"
            else:
                val = str(data.get(col_name, "") if data else "")
            item = QTableWidgetItem(val)
            if status == DiffStatus.CHANGED:
                item.setToolTip(val)
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
            # Checked by default — creating a genuinely new person is the normal
            # case. Unchecking holds one back: Schuldock sometimes still lists a
            # teacher who has already left, and creating that account is work to
            # undo, so the decision has to be available before the upload.
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Checked)
            if bg_color:
                chk_item.setBackground(bg_color)
                chk_item.setForeground(_COLOR_TEXT)
            chk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row_idx, chk_col, chk_item)
            self.n_added += 1

        elif status == DiffStatus.UNCHANGED:
            self.n_unchanged += 1
            placeholder = QTableWidgetItem("")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row_idx, chk_col, placeholder)
            self._table.setRowHidden(row_idx, True)

        if self.shows_asm_state:
            self._table.setItem(
                row_idx, chk_col + 1, self._asm_cell(row_diff, status, bg_color))

        meta = _RowMeta(
            row_diff=row_diff,
            table_row=row_idx,
            reviewed=(status != DiffStatus.DELETED),
            checkbox_item=chk_item,
        )
        self._row_metas.append(meta)

    def _asm_cell(self, row_diff, status, bg_color) -> QTableWidgetItem:
        """Does ASM hold this person? The question the Status column cannot answer."""
        item = QTableWidgetItem(self._asm_state.label(row_diff.record_id))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if bg_color:
            item.setBackground(bg_color)
            item.setForeground(_COLOR_TEXT)

        if self._asm_state.state(row_diff.record_id) == UNKNOWN:
            item.setToolTip(
                "No trustworthy evidence about this person's ASM account.\n"
                "Load a recent ASM activity log, or upload once from this app, "
                "before holding rows back."
            )
        elif status == DiffStatus.ADDED and self._asm_state.holding_back_is_destructive(
                row_diff.record_id):
            item.setToolTip(
                "This person already has an active ASM account.\n"
                "Unticking will deactivate it, not skip a creation."
            )
        elif status == DiffStatus.DELETED and self._asm_state.keeping_is_destructive(
                row_diff.record_id):
            item.setToolTip(
                "ASM has no active account for this id.\n"
                "Keeping this row re-sends it, which creates a new account."
            )
        return item

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
        self._refresh_row_visibility()
        self._toggle_btn.setText(
            "Hide unchanged" if not self._unchanged_hidden else "Show unchanged"
        )

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = (text or "").strip().lower()
        self._refresh_row_visibility()

    def _row_matches_filter(self, meta: _RowMeta) -> bool:
        if not self._filter_text:
            return True
        for col_idx in range(len(self.key_columns)):
            item = self._table.item(meta.table_row, col_idx)
            if item is not None and self._filter_text in item.text().lower():
                return True
        return False

    def _refresh_row_visibility(self) -> None:
        """Single owner of row visibility: the unchanged toggle and the filter.

        Drops the selection: rows hidden while selected would stay selected but
        invisible, and would make the select-all toggle read "already all
        selected" and deselect on the next click.
        """
        selection_model = self._table.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()

        visible = 0
        for meta in self._row_metas:
            hidden = not self._row_matches_filter(meta)
            if meta.row_diff.status == DiffStatus.UNCHANGED and self._unchanged_hidden:
                hidden = True
            self._table.setRowHidden(meta.table_row, hidden)
            visible += not hidden
        self._filter_count_label.setText(
            f"{visible} of {len(self._row_metas)} shown" if self._filter_text else ""
        )

    def _row_indices_for_status(self, status: DiffStatus) -> list[int]:
        """Visible rows of *status* — a filtered-away row is not 'all' of anything."""
        if status not in {DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED}:
            return []
        return [
            meta.table_row
            for meta in self._row_metas
            if meta.row_diff.status == status
            and not self._table.isRowHidden(meta.table_row)
        ]

    def _decide_selected(self, *, approve: bool) -> None:
        """Apply one decision to every selected, visible row that has a checkbox.

        Signals stay blocked while the boxes are written, so ``reviewed`` is set
        here rather than left to ``_on_item_changed`` (which would never fire).
        Rejecting a deletion counts as reviewing it — keeping a record is a
        decision, and previously the only way to register it was to tick the box
        and untick it again.
        """
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return

        selected_rows = {
            idx.row()
            for idx in selection_model.selectedRows()
            if not self._table.isRowHidden(idx.row())
        }
        if not selected_rows:
            return

        state = Qt.CheckState.Checked if approve else Qt.CheckState.Unchecked
        touched = 0
        self._table.blockSignals(True)
        for meta in self._row_metas:
            if meta.table_row not in selected_rows or meta.checkbox_item is None:
                continue
            meta.checkbox_item.setCheckState(state)
            meta.reviewed = True
            touched += 1
        self._table.blockSignals(False)

        if touched and self._gate_callback:
            self._gate_callback()

    def _are_all_rows_selected(self, row_indices: list[int]) -> bool:
        if not row_indices:
            return False
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return False
        return all(
            selection_model.isRowSelected(row_idx, self._table.rootIndex())
            for row_idx in row_indices
        )

    def _toggle_status_row_selection(self, status: DiffStatus) -> None:
        row_indices = self._row_indices_for_status(status)
        if not row_indices:
            return

        selection_model = self._table.selectionModel()
        model = self._table.model()
        if selection_model is None or model is None:
            return

        all_selected = self._are_all_rows_selected(row_indices)
        selection_flag = (
            QItemSelectionModel.SelectionFlag.Deselect
            if all_selected
            else QItemSelectionModel.SelectionFlag.Select
        )

        for row_idx in row_indices:
            index = model.index(row_idx, 0)
            selection_model.select(
                index,
                selection_flag | QItemSelectionModel.SelectionFlag.Rows,
            )

    def _approve_all_changes(self) -> None:
        """Check all CHANGED checkboxes in this tab."""
        self._table.blockSignals(True)
        for meta in self._row_metas:
            if meta.row_diff.status == DiffStatus.CHANGED and meta.checkbox_item:
                meta.checkbox_item.setCheckState(Qt.CheckState.Checked)
        self._table.blockSignals(False)

    def _approve_all_deletions(self) -> None:
        """Check all DELETED checkboxes in this tab after explicit warning."""
        total = sum(1 for m in self._row_metas if m.row_diff.status == DiffStatus.DELETED)
        if total == 0:
            return

        box = MessageBox(
            "Warning",
            (
                f"You are about to approve {total} deletion(s) at once.\n\n"
                "This will remove these records from the export. Continue?"
            ),
            self,
        )
        if hasattr(box, "yesButton"):
            box.yesButton.setText("Approve all deletions")
        if hasattr(box, "cancelButton"):
            box.cancelButton.setText("Cancel")
        if not box.exec():
            return

        self._table.blockSignals(True)
        for meta in self._row_metas:
            if meta.row_diff.status == DiffStatus.DELETED and meta.checkbox_item:
                meta.checkbox_item.setCheckState(Qt.CheckState.Checked)
                meta.reviewed = True
        self._table.blockSignals(False)
        if self._gate_callback:
            self._gate_callback()

    def risky_decisions(self) -> list[tuple[str, str]]:
        """Decisions on this tab whose effect on ASM is worse than it looks.

        One choke point rather than a guard per control: the same mistake can
        arrive from a checkbox, a bulk button, or Keep all deletions, and only
        the resulting decision matters.

        Returns ``(kind, description)`` pairs, empty when nothing is risky.
        """
        if not self.shows_asm_state:
            return []

        risky: list[tuple[str, str]] = []
        for meta in self._row_metas:
            rd = meta.row_diff
            checked = (
                meta.checkbox_item is not None
                and meta.checkbox_item.checkState() == Qt.CheckState.Checked
            )
            record = rd.current or rd.snapshot or {}
            who = " ".join(
                p for p in (record.get("first_name", ""), record.get("last_name", "")) if p
            ).strip() or rd.record_id

            if (rd.status == DiffStatus.ADDED and not checked
                    and self._asm_state.holding_back_is_destructive(rd.record_id)):
                risky.append(("deactivate", f"{who} ({rd.record_id})"))
            elif (rd.status == DiffStatus.DELETED and not checked
                    and self._asm_state.keeping_is_destructive(rd.record_id)):
                risky.append(("duplicate", f"{who} ({rd.record_id})"))
        return risky

    def keep_all_deletions(self) -> int:
        """Untick every DELETED row and mark it decided. Returns rows touched.

        No confirmation: keeping a record is the safe direction and is already
        the default state — the tick is what needs a warning, not this.
        """
        touched = 0
        self._table.blockSignals(True)
        for meta in self._row_metas:
            if meta.row_diff.status == DiffStatus.DELETED and meta.checkbox_item:
                meta.checkbox_item.setCheckState(Qt.CheckState.Unchecked)
                meta.reviewed = True
                touched += 1
        self._table.blockSignals(False)
        return touched

    def count_unreviewed_deletions(self) -> int:
        return sum(
            1 for m in self._row_metas
            if m.row_diff.status == DiffStatus.DELETED and not m.reviewed
        )

    def get_approved_records(self) -> list[dict]:
        """Return records approved for this tab according to checkbox decisions.

        - UNCHANGED           → always include current
        - ADDED + checked     → include current (create it)
        - ADDED + unchecked   → EXCLUDED; there is no snapshot to fall back to,
                                so the row simply never reaches ASM and nothing
                                is created
        - CHANGED + checked   → include current (new value)
        - CHANGED + unchecked → include snapshot (old value)
        - DELETED + checked   → EXCLUDED (confirmed deletion)
        - DELETED + unchecked → include snapshot (preserved)
        """
        approved = []
        for meta in self._row_metas:
            rd = meta.row_diff
            if rd.status == DiffStatus.UNCHANGED:
                approved.append(dict(rd.current))
            elif rd.status == DiffStatus.ADDED:
                checked = (
                    meta.checkbox_item is not None
                    and meta.checkbox_item.checkState() == Qt.CheckState.Checked
                )
                if checked:
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
    upload_requested = pyqtSignal()

    def __init__(self, controller: AppController | None = None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("DiffReviewPage")   # Must be set before addSubInterface

        self._controller = controller
        self._tab_widgets: list[_TabWidget] = []
        self._diff_result: DiffResult | None = None
        self._upload_available = False
        self._upload_status = ""
        self._row_size_map = {
            "Compact": 24,
            "Normal": 30,
            "Comfortable": 36,
            "Large": 44,
        }
        self._current_row_height = self._row_size_map["Normal"]

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

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        size_row.addWidget(CaptionLabel("Row size"))
        self._row_size_combo = ComboBox(self)
        self._row_size_combo.addItems(list(self._row_size_map.keys()))
        self._row_size_combo.setCurrentText("Normal")
        self._row_size_combo.currentTextChanged.connect(self._on_row_size_changed)
        size_row.addWidget(self._row_size_combo)
        size_row.addStretch()
        content_layout.addLayout(size_row)

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
        self._apply_row_height(self._current_row_height)

        # Bottom bar: Export ZIP
        bottom_bar = QHBoxLayout()
        # Export is gated on reviewing every deletion; without this label a
        # disabled button is the only feedback and the reason is invisible.
        self._gate_label = CaptionLabel("")
        bottom_bar.addWidget(self._gate_label)

        self._evidence_label = CaptionLabel("")
        self._evidence_label.setToolTip(
            "Without evidence, ADDED only means 'not in the local snapshot'.\n"
            "A stale snapshot makes live accounts look new."
        )
        bottom_bar.addWidget(self._evidence_label)

        # The only one-click bulk action for deletions used to be the
        # destructive one, so satisfying the gate by keeping everything meant
        # selecting rows tab by tab. Unticked already means keep — this just
        # records that it was a decision, across every tab at once.
        self._keep_all_del_btn = PushButton("Keep all deletions")
        self._keep_all_del_btn.setVisible(False)
        self._keep_all_del_btn.clicked.connect(self._keep_all_deletions)
        bottom_bar.addWidget(self._keep_all_del_btn)

        bottom_bar.addStretch()
        self._upload_btn = PrimaryPushButton(FIF.SEND, "Create ZIP and Upload")
        self._upload_btn.setEnabled(False)
        self._upload_btn.setVisible(False)
        self._upload_btn.clicked.connect(self._on_upload_clicked)
        bottom_bar.addWidget(self._upload_btn)

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

    def load_diff(self, diff_result: DiffResult, asm_state: AsmState | None = None) -> None:
        """Populate all tabs from diff_result. Resets all state."""
        self._diff_result = diff_result
        self._asm_state = asm_state or AsmState()

        tab_map = {
            "students": diff_result.students,
            "staff":    diff_result.staff,
            "courses":  diff_result.courses,
            "classes":  diff_result.classes,
            "rosters":  diff_result.rosters,
        }

        for tab_w in self._tab_widgets:
            tab_w.disconnect_item_changed()
            tab_w.populate(tab_map[tab_w.tab_key], self._asm_state)
            tab_w.wire_item_changed()

        self._evidence_label.setText(
            "" if self._asm_state.has_evidence
            else "No ASM evidence loaded — the 'In ASM' column cannot be answered"
        )

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

    def set_upload_available(self, available: bool, reason: str = "") -> None:
        self._upload_available = available
        self._upload_status = reason or ""
        self._upload_btn.setVisible(available)
        self._upload_btn.setToolTip(self._upload_status if self._upload_status else "")
        if self._diff_result is None:
            self._upload_btn.setEnabled(False)
            return
        self._check_export_gate()

    def reset(self) -> None:
        """Return to placeholder state (called after successful export)."""
        self._diff_result = None
        self._content.hide()
        self._export_btn.setEnabled(False)
        self._upload_btn.setEnabled(False)
        self._placeholder.show()

    # ------------------------------------------------------------------
    # Export gate
    # ------------------------------------------------------------------

    def _check_export_gate(self) -> None:
        total_unreviewed = sum(
            tw.count_unreviewed_deletions() for tw in self._tab_widgets
        )
        gate_ok = total_unreviewed == 0
        self._export_btn.setEnabled(gate_ok)
        self._upload_btn.setEnabled(gate_ok and self._upload_available)

        self._keep_all_del_btn.setVisible(not gate_ok)
        if gate_ok:
            self._gate_label.setText("")
            self._gate_label.setToolTip("")
            return

        plural = "" if total_unreviewed == 1 else "s"
        self._gate_label.setText(
            f"Export blocked — {total_unreviewed:,} deletion{plural} need a decision"
        )
        self._keep_all_del_btn.setText(
            f"Keep all {total_unreviewed:,} deletion{plural}"
        )
        per_tab = "\n".join(
            f"  {tw.count_unreviewed_deletions():,} in {tw.tab_key}"
            for tw in self._tab_widgets
            if tw.count_unreviewed_deletions()
        )
        self._gate_label.setToolTip(
            f"Still undecided:\n{per_tab}\n\n"
            "Keep all deletions retains every one of them. To delete some, "
            "select those rows and use Approve selected."
        )

    def _keep_all_deletions(self) -> None:
        """Record 'keep them' for every undecided deletion, in every tab."""
        for tab_w in self._tab_widgets:
            tab_w.keep_all_deletions()
        self._check_export_gate()

    def _on_row_size_changed(self, label: str) -> None:
        self._current_row_height = self._row_size_map.get(label, self._row_size_map["Normal"])
        self._apply_row_height(self._current_row_height)

    def _apply_row_height(self, px: int) -> None:
        for tab_w in self._tab_widgets:
            tab_w.set_row_height(px)

    # ------------------------------------------------------------------
    # Export ZIP
    # ------------------------------------------------------------------

    def _on_export_clicked(self) -> None:
        if self._confirm_risky_decisions("Export ZIP"):
            self.export_requested.emit()

    def _on_upload_clicked(self) -> None:
        if self._confirm_risky_decisions("Create ZIP and Upload"):
            self.upload_requested.emit()

    def risky_decisions(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for tab_w in self._tab_widgets:
            out += tab_w.risky_decisions()
        return out

    def _confirm_risky_decisions(self, proceed_label: str) -> bool:
        """Last stop before a decision reaches ASM. True = go ahead.

        The Status column describes the local snapshot; this describes ASM. When
        they disagree, the disagreement is the whole story, so it is spelled out
        by name rather than counted.
        """
        risky = self.risky_decisions()
        if not risky:
            return True

        deactivate = [who for kind, who in risky if kind == "deactivate"]
        duplicate = [who for kind, who in risky if kind == "duplicate"]

        parts: list[str] = []
        if deactivate:
            parts.append(
                f"{len(deactivate)} person(s) you left unticked already have an ASM "
                f"account, or may have one. Holding them back DEACTIVATES it:\n  "
                + "\n  ".join(deactivate[:10])
                + (f"\n  …and {len(deactivate) - 10:,} more" if len(deactivate) > 10 else "")
            )
        if duplicate:
            parts.append(
                f"{len(duplicate)} record(s) you chose to keep have no active ASM "
                f"account. Re-sending them CREATES a new account:\n  "
                + "\n  ".join(duplicate[:10])
                + (f"\n  …and {len(duplicate) - 10:,} more" if len(duplicate) > 10 else "")
            )
        if not self._asm_state.has_evidence:
            parts.append(
                "No ASM evidence is loaded, so this is a warning, not a diagnosis. "
                "Load a recent ASM activity log to get a real answer."
            )

        box = MessageBox("These decisions change ASM accounts",
                         "\n\n".join(parts), self)
        if hasattr(box, "yesButton"):
            box.yesButton.setText(proceed_label)
        if hasattr(box, "cancelButton"):
            box.cancelButton.setText("Go back")
        return bool(box.exec())
