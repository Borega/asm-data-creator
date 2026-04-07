"""Pure transform functions — no file I/O, no global state."""
from __future__ import annotations
from .config import GeneratorConfig, GeneratorResult


def build_student_records(parsed_students: list, config: GeneratorConfig) -> list:
    raise NotImplementedError


def build_teacher_records(
    sections: list,
    existing_staff: list,
    config: GeneratorConfig,
) -> dict:
    raise NotImplementedError


def build_course_records(sections: list, config: GeneratorConfig) -> dict:
    raise NotImplementedError


def build_class_records(
    sections: list,
    courses_map: dict,
    teacher_records: dict,
    student_records: list,
    config: GeneratorConfig,
) -> tuple:
    """Returns (classes, rosters, warnings)."""
    raise NotImplementedError
