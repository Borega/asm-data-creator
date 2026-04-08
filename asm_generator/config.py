"""Configuration and result dataclasses for the ASM generator."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field


@dataclass
class GeneratorConfig:
    """Runtime configuration — replaces all module-level constants in generate_asm.py."""
    location_id: str
    email_domain: str
    aliases_path: str          # Path to teacher_aliases.json
    subjects_path: str         # Path to subject_map.json
    input_mode: str = "schuldock"       # schuldock | legacy (legacy alias: monolith)
    target_school_year: str = ""        # e.g. 2025/2026; empty = no filter

    # Loaded lazily on first access by from_json(); also set when loading from JSON.
    _aliases: dict = field(default_factory=dict, repr=False)
    _subjects: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, path: str) -> "GeneratorConfig":
        """Load a GeneratorConfig from a JSON file.

        The JSON schema is:
        {
            "location_id": "sts_rissen",
            "email_domain": "rissen.hamburg.de",
            "aliases_path": "teacher_aliases.json",
            "subjects_path": "subject_map.json"
        }

        Raises FileNotFoundError if path does not exist.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"GeneratorConfig: config file not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            location_id=data["location_id"],
            email_domain=data["email_domain"],
            aliases_path=data["aliases_path"],
            subjects_path=data["subjects_path"],
            input_mode=data.get("input_mode", "schuldock"),
            target_school_year=data.get("target_school_year", ""),
        )

    def load_aliases(self) -> dict:
        """Load and return TEACHER_ALIASES from aliases_path.

        The JSON file stores aliases as an array of [[from_first, from_last], [to_first, to_last]].

        Raises FileNotFoundError if aliases_path does not exist.
        Raises ValueError if the file does not contain a JSON array.
        """
        if not os.path.isfile(self.aliases_path):
            raise FileNotFoundError(
                f"GeneratorConfig: teacher aliases file not found: {self.aliases_path}"
            )
        with open(self.aliases_path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError(
                f"Expected a JSON array in {self.aliases_path}, got {type(raw).__name__}"
            )
        result: dict = {}
        for entry in raw:
            from_pair, to_pair = entry
            result[(from_pair[0], from_pair[1])] = (to_pair[0], to_pair[1])
        self._aliases = result
        return result

    def load_subjects(self) -> dict:
        """Load and return SUBJECT_MAP from subjects_path.

        Raises FileNotFoundError if subjects_path does not exist.
        Raises ValueError if the file does not contain a JSON object.
        """
        if not os.path.isfile(self.subjects_path):
            raise FileNotFoundError(
                f"GeneratorConfig: subject map file not found: {self.subjects_path}"
            )
        with open(self.subjects_path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError(
                f"Expected a JSON object in {self.subjects_path}, got {type(raw).__name__}"
            )
        self._subjects = raw
        return raw


@dataclass
class GeneratorResult:
    """In-memory output of generate(). All five ASM CSV tables as lists of dicts."""
    students: list = field(default_factory=list)
    staff:    list = field(default_factory=list)
    courses:  list = field(default_factory=list)
    classes:  list = field(default_factory=list)
    rosters:  list = field(default_factory=list)
    warnings: list = field(default_factory=list)
