"""generate_asm.py — backward-compatible shim.
All logic has been moved to asm_generator/. This script hardcodes the config
and calls generate(), then writes the result to disk.
"""
from asm_generator import generate, GeneratorConfig
from asm_generator.writer import write_csv_files

if __name__ == "__main__":
    import csv as _csv
    import os as _os

    config = GeneratorConfig(
        location_id="sts_rissen",
        email_domain="rissen.hamburg.de",
        aliases_path="teacher_aliases.json",
        subjects_path="subject_map.json",
    )

    # Load existing staff.csv to carry forward email addresses across runs
    _existing_staff: list = []
    if _os.path.exists("staff.csv"):
        with open("staff.csv", encoding="utf-8-sig", newline="") as _f:
            _existing_staff = list(_csv.DictReader(_f))

    result = generate(
        config=config,
        student_paths=["Student_20260402_1042.csv"],
        export_paths=[
            "export_angebotSchueler_2026.03.30.14-10.csv",
            "export_angebotSchueler_2026.04.02.13-40.csv",
            "export_angebotSchueler_2026.04.02.13-42.csv",
        ],
        existing_staff=_existing_staff,
    )
    write_csv_files(result, output_dir=".")
    print(f"  students.csv  : {len(result.students)} rows")
    print(f"  staff.csv     : {len(result.staff)} rows")
    print(f"  courses.csv   : {len(result.courses)} rows")
    print(f"  classes.csv   : {len(result.classes)} rows")
    print(f"  rosters.csv   : {len(result.rosters)} rows")
    if result.warnings:
        print(f"\n{len(result.warnings)} warnings:")
        for w in result.warnings:
            print(f"  {w}")


