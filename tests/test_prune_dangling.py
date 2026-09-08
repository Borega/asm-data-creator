"""Holding back an ADDED row must not leave references pointing at nothing."""

from __future__ import annotations

from asm_generator.config import GeneratorResult
from gui.app_controller import _prune_dangling_references


_STUDENT = {"person_id": "stu-1", "first_name": "Ada", "last_name": "Lovelace"}
_TEACHER = {"person_id": "anna.meier", "first_name": "Anna", "last_name": "Meier"}
_COURSE = {"course_id": "c1", "course_name": "Mathematik", "course_number": "MA"}
_CLASS = {"class_id": "k1", "class_number": "10a Mathe", "course_id": "c1",
          "instructor_id": "anna.meier", "instructor_id_2": "", "instructor_id_3": ""}
_ROSTER = {"roster_id": "r1", "class_id": "k1", "student_id": "stu-1"}


def _result(**kw) -> GeneratorResult:
    base = {
        "students": [dict(_STUDENT)],
        "staff": [dict(_TEACHER)],
        "courses": [dict(_COURSE)],
        "classes": [dict(_CLASS)],
        "rosters": [dict(_ROSTER)],
    }
    base.update(kw)
    return GeneratorResult(**base)


def _catalogue() -> GeneratorResult:
    """The unfiltered result — what the report resolves names against."""
    return _result()


def test_nothing_is_touched_when_every_reference_resolves():
    result = _result()
    assert _prune_dangling_references(result) == []
    assert len(result.classes) == 1
    assert len(result.rosters) == 1
    assert result.classes[0]["instructor_id"] == "anna.meier"


def test_held_back_teacher_only_clears_the_instructor_slot():
    """Dropping the class instead would deport every student enrolled in it."""
    result = _result(staff=[])

    notes = _prune_dangling_references(result, _catalogue())

    assert result.classes[0]["instructor_id"] == ""
    assert len(result.classes) == 1, "the class survives without its teacher"
    assert len(result.rosters) == 1, "and so does everyone in it"
    assert notes == [
        "Teacher not being created: Anna Meier (anna.meier) — removed as "
        "instructor from 1 class(es): 10a Mathe"
    ]


def test_held_back_student_drops_only_their_enrolment():
    result = _result(students=[])

    notes = _prune_dangling_references(result, _catalogue())

    assert result.rosters == []
    assert len(result.classes) == 1
    assert notes == [
        "Student not being created: Ada Lovelace (stu-1) — removed 1 enrolment(s)"
    ]


def test_held_back_course_takes_its_classes_and_enrolments_with_it():
    result = _result(courses=[])

    notes = _prune_dangling_references(result, _catalogue())

    assert result.classes == []
    assert result.rosters == [], "a roster for a dropped class would dangle too"
    assert notes[0] == (
        "Course not being created: Mathematik — dropped 1 class(es): 10a Mathe"
    )
    assert "1 further enrolment(s) removed for dropped classes" in notes[1]


def test_a_name_is_still_reported_without_a_catalogue():
    """The id alone is useless, but it must never crash for want of a name."""
    notes = _prune_dangling_references(_result(staff=[]))
    assert notes == [
        "Teacher not being created: anna.meier — removed as instructor "
        "from 1 class(es): 10a Mathe"
    ]


def test_a_long_student_list_never_hides_the_teacher_line():
    """The headline finding must survive a 30-student prune, not be truncated away."""
    students = [{"person_id": f"stu-{i}", "first_name": "S", "last_name": str(i)}
                for i in range(30)]
    classes = [dict(_CLASS, class_id=f"k{i}", class_number=f"Class {i}")
               for i in range(30)]
    rosters = [{"roster_id": f"r{i}", "class_id": "k0", "student_id": f"stu-{i}"}
               for i in range(30)]
    catalogue = _result(students=students, classes=classes, rosters=rosters)

    result = _result(students=[], classes=classes, rosters=rosters, staff=[])
    notes = _prune_dangling_references(result, catalogue)

    teacher_lines = [n for n in notes if n.startswith("Teacher not being created")]
    assert len(teacher_lines) == 1, "the teacher must still be named"
    assert " and 25 more" in teacher_lines[0], "its class list is capped in place"

    student_lines = [n for n in notes if n.startswith("Student not being created")]
    assert len(student_lines) == 4, "students capped per category, not globally"
    assert notes[-1] == "…and 26 more"
