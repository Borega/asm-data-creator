"""A fresh install must say what to configure, not fail once files are chosen."""

from __future__ import annotations

import os

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from gui.app_controller import AppController

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _controller(qapp, **settings) -> AppController:
    controller = AppController(QWidget())
    controller._settings = settings
    return controller


def test_a_blank_install_names_both_required_settings(qapp):
    controller = _controller(qapp)
    assert controller.missing_required_settings() == ["Location ID", "Email Domain"]


def test_a_configured_install_is_ready(qapp):
    controller = _controller(
        qapp, location_id="LOC001", email_domain="school.example")
    assert controller.missing_required_settings() == []


def test_whitespace_does_not_count_as_configured(qapp):
    controller = _controller(qapp, location_id="   ", email_domain="\t")
    assert controller.missing_required_settings() == ["Location ID", "Email Domain"]


def test_only_the_missing_one_is_named(qapp):
    controller = _controller(qapp, location_id="LOC001")
    assert controller.missing_required_settings() == ["Email Domain"]


def test_startup_opens_settings_while_configuration_is_incomplete(qapp):
    """Previously only missing SFTP credentials opened Settings on startup."""
    controller = _controller(qapp)
    assert controller.should_open_settings_on_startup() is True


def test_the_required_settings_are_the_ones_generation_actually_needs(qapp):
    """email_domain now raises in transform; location_id is stamped on every row."""
    keys = {key for key, _label in AppController.REQUIRED_SETTINGS}
    assert keys == {"location_id", "email_domain"}
