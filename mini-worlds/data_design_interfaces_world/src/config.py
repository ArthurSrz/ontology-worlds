"""
config.py
---------
Central configuration for the ontology enforcement framework.

Loads ontokit.json from the project root and provides typed defaults.
All other modules read their configuration through this module,
eliminating hardcoded paths and domain-specific values.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONFIG_FILENAME = "ontokit.json"


@dataclass
class OntoKitConfig:
    """Typed configuration for the ontology enforcement framework."""
    ontology: str = "ontology/ontology.json"
    tool_name: str = "ontology_grounded_response"
    validation_threshold: float = 0.5
    max_retries: int = 3
    language: str = "en"
    log_file: str = "validation_log.jsonl"

    # Resolved at load time
    _root: Path = field(default_factory=lambda: Path.cwd(), repr=False)

    @property
    def ontology_path(self) -> Path:
        """Absolute path to the ontology file."""
        p = Path(self.ontology)
        if p.is_absolute():
            return p
        return self._root / p

    @property
    def log_path(self) -> Path:
        p = Path(self.log_file)
        if p.is_absolute():
            return p
        return self._root / p


def load_config(root: Path | None = None) -> OntoKitConfig:
    """
    Load configuration from ontokit.json in the given root directory.
    Falls back to defaults if the file is missing.
    """
    if root is None:
        root = Path.cwd()
    root = root.resolve()

    config_path = root / CONFIG_FILENAME
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return OntoKitConfig(
            ontology=data.get("ontology", OntoKitConfig.ontology),
            tool_name=data.get("tool_name", OntoKitConfig.tool_name),
            validation_threshold=data.get("validation_threshold", OntoKitConfig.validation_threshold),
            max_retries=data.get("max_retries", OntoKitConfig.max_retries),
            language=data.get("language", OntoKitConfig.language),
            log_file=data.get("log_file", OntoKitConfig.log_file),
            _root=root,
        )

    return OntoKitConfig(_root=root)


def get_ontology_metadata(raw_data: dict) -> dict[str, Any]:
    """
    Extract the metadata block from a loaded ontology JSON-LD dict.
    Returns sensible defaults if metadata is absent.
    """
    default = {
        "name": "Ontology",
        "name_short": "",
        "description": "",
        "language": "en",
        "version": "1.0.0",
        "domain": "general",
    }
    meta = raw_data.get("metadata", {})
    return {**default, **meta}
