"""I/O functions — the only module in asm_generator that touches the filesystem."""
from __future__ import annotations
from pathlib import Path
from .config import GeneratorResult


def write_to_zip(result: GeneratorResult, output_path) -> None:
    """Pack approved output CSVs into a ZIP file at output_path.

    Implementation deferred to Phase 3. This stub exists so Phase 2 can import
    writer without errors. The GUI Export pipeline will implement this.
    """
    raise NotImplementedError("write_to_zip is implemented in Phase 3")


def write_csv_files(result: GeneratorResult, output_dir=".") -> None:
    """Write all five CSVs to output_dir. Used by the generate_asm.py shim."""
    raise NotImplementedError
