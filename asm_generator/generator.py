"""Top-level generate() orchestrator."""
from __future__ import annotations
from pathlib import Path
from .config import GeneratorConfig, GeneratorResult


def generate(
    config: GeneratorConfig,
    student_paths: list,
    export_paths: list,
    existing_staff: list | None = None,
) -> GeneratorResult:
    """Run the full generation pipeline in memory. Writes nothing to disk."""
    raise NotImplementedError
