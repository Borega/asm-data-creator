"""Settings page layout regressions around SFTP status rendering."""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import QApplication, QScrollArea

from gui.pages.settings_page import SettingsPage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _rect_in_page(page: SettingsPage, widget) -> QRect:
    top_left = widget.mapTo(page, QPoint(0, 0))
    return QRect(top_left, widget.size())


def test_long_sftp_status_keeps_config_path_fields_usable_without_overlap(qapp: QApplication):
    page = SettingsPage(controller=None)
    page.resize(1024, 768)
    page.show()
    qapp.processEvents()

    long_status = (
        "DNS resolution failed for upload.appleschoolcontent.com: "
        "[Errno -2] Name or service not known "
    ) * 4
    page.set_sftp_status(False, long_status)
    qapp.processEvents()

    assert page._sftp_status_label.wordWrap() is False
    assert page._sftp_status_label.toolTip().startswith("Status: Not ready - DNS resolution failed")

    assert page._teacher_aliases_edit.isEnabled() is True
    assert page._teacher_aliases_edit.isReadOnly() is False
    assert page._subject_map_edit.isEnabled() is True
    assert page._subject_map_edit.isReadOnly() is False

    location_rect = _rect_in_page(page, page._location_id_edit)
    email_rect = _rect_in_page(page, page._email_domain_edit)
    year_rect = _rect_in_page(page, page._target_year_edit)
    alias_rect = _rect_in_page(page, page._teacher_aliases_edit)
    subject_rect = _rect_in_page(page, page._subject_map_edit)
    save_rect = _rect_in_page(page, page._save_btn)

    assert alias_rect.width() <= page.width()
    assert subject_rect.width() <= page.width()

    assert location_rect.bottom() < email_rect.top()
    assert email_rect.bottom() < year_rect.top()
    assert year_rect.bottom() < alias_rect.top()
    assert alias_rect.bottom() < subject_rect.top()
    assert subject_rect.bottom() < save_rect.top()


def test_settings_page_uses_scroll_area_when_viewport_is_small(qapp: QApplication):
    page = SettingsPage(controller=None)
    page.resize(720, 480)
    page.show()
    qapp.processEvents()

    scroll_areas = page.findChildren(QScrollArea)
    assert scroll_areas, "Settings page should be wrapped in a scroll area"

    scroll = scroll_areas[0]
    assert scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

    # On small viewports content should be scrollable (range > 0).
    assert scroll.verticalScrollBar().maximum() > 0
