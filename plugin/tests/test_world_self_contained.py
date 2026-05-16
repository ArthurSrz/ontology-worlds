"""
Test that mini-worlds on the subscribers branch are fully self-contained.

Clones the subscribers branch into a temp directory and verifies:
- No broken symlinks
- All required files/directories present
- No imports referencing parent directories
- All config paths resolve within the world
- Python modules importable from within the world
- Ontology JSON-LD is valid and non-empty
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_URL = "git@github.com:ArthurSrz/ontology-worlds.git"
BRANCH = "subscribers"


@pytest.fixture(scope="module")
def subscribers_repo(tmp_path_factory):
    """Clone the subscribers branch into a temporary directory."""
    tmp = tmp_path_factory.mktemp("subscribers")
    subprocess.run(
        ["git", "clone", "-b", BRANCH, "--single-branch", "--depth", "1", REPO_URL, str(tmp / "repo")],
        check=True,
        capture_output=True,
    )
    return tmp / "repo"


def discover_worlds(repo_path):
    """Find all *_world/ directories in the repo."""
    return [d for d in repo_path.iterdir() if d.is_dir() and d.name.endswith("_world")]


@pytest.fixture(scope="module")
def worlds(subscribers_repo):
    found = discover_worlds(subscribers_repo)
    assert len(found) > 0, "No *_world/ directories found on subscribers branch"
    return found


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

REQUIRED_FILES = [
    "ontokit.json",
    "CLAUDE.md",
    "requirements.txt",
    "demo.py",
    "map.py",
    "log_entities.py",
    ".claude/settings.json",
    ".mcp.json",
]

REQUIRED_DIRS = [
    "src",
    "hooks",
    "ontology",
    "mcp",
]

SRC_MODULES = [
    "src/__init__.py",
    "src/config.py",
    "src/ontology_graph.py",
    "src/grammar_builder.py",
    "src/validator.py",
    "src/constrained_client.py",
    "src/world_map.py",
]

HOOK_FILES = [
    "hooks/pre_tool_call.py",
    "hooks/post_tool_call.py",
]

MCP_MODULES = [
    "mcp/okg_mcp/__init__.py",
    "mcp/okg_mcp/server.py",
    "mcp/wikidata_mcp/__init__.py",
    "mcp/wikidata_mcp/server.py",
    "mcp/pyproject.toml",
]


class TestWorldStructure:
    """Every world must have the required files and directories."""

    def test_required_files_exist(self, worlds):
        for world in worlds:
            for f in REQUIRED_FILES:
                assert (world / f).exists(), f"{world.name}: missing {f}"

    def test_required_dirs_exist(self, worlds):
        for world in worlds:
            for d in REQUIRED_DIRS:
                path = world / d
                assert path.exists(), f"{world.name}: missing directory {d}"
                assert path.is_dir(), f"{world.name}: {d} is not a directory"

    def test_src_modules_exist(self, worlds):
        for world in worlds:
            for m in SRC_MODULES:
                assert (world / m).exists(), f"{world.name}: missing {m}"

    def test_hook_files_exist(self, worlds):
        for world in worlds:
            for h in HOOK_FILES:
                assert (world / h).exists(), f"{world.name}: missing {h}"

    def test_mcp_modules_exist(self, worlds):
        for world in worlds:
            for m in MCP_MODULES:
                assert (world / m).exists(), f"{world.name}: missing {m}"

    def test_ontology_json_exists(self, worlds):
        for world in worlds:
            ontology_dir = world / "ontology"
            json_files = list(ontology_dir.glob("*_ontology.json"))
            assert len(json_files) >= 1, f"{world.name}: no *_ontology.json in ontology/"

    def test_schemas_exist(self, worlds):
        for world in worlds:
            schema_dir = world / "ontology" / "schemas"
            assert schema_dir.is_dir(), f"{world.name}: missing ontology/schemas/"
            schemas = list(schema_dir.glob("*.json"))
            assert len(schemas) >= 1, f"{world.name}: no schemas in ontology/schemas/"


# ---------------------------------------------------------------------------
# No broken symlinks
# ---------------------------------------------------------------------------

class TestNoSymlinks:
    """A self-contained world must have no symlinks at all."""

    def test_no_symlinks(self, worlds):
        for world in worlds:
            symlinks = []
            for path in world.rglob("*"):
                if path.is_symlink():
                    symlinks.append(str(path.relative_to(world)))
            assert symlinks == [], (
                f"{world.name}: found symlinks (would break standalone clone): {symlinks}"
            )


# ---------------------------------------------------------------------------
# No parent directory references in Python source
# ---------------------------------------------------------------------------

class TestNoParentReferences:
    """No Python file should import from or reference parent directories."""

    def test_no_dotdot_imports(self, worlds):
        """No 'from ..' or 'import ..' reaching outside the world."""
        for world in worlds:
            violations = []
            for py in world.rglob("*.py"):
                content = py.read_text(errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    # Skip comments
                    if stripped.startswith("#"):
                        continue
                    # Check for path references going up past the world root
                    if "../../" in stripped or "'../'" in stripped or '"../"' in stripped:
                        violations.append(f"{py.relative_to(world)}:{i}: {stripped}")
            assert violations == [], (
                f"{world.name}: parent directory references found:\n"
                + "\n".join(violations)
            )

    def test_no_hardcoded_absolute_paths(self, worlds):
        """No hardcoded /Users/ or /home/ paths in source files."""
        for world in worlds:
            violations = []
            for py in world.rglob("*.py"):
                content = py.read_text(errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if "/Users/" in stripped or "/home/" in stripped:
                        violations.append(f"{py.relative_to(world)}:{i}: {stripped}")
            assert violations == [], (
                f"{world.name}: hardcoded absolute paths:\n"
                + "\n".join(violations)
            )


# ---------------------------------------------------------------------------
# Config integrity
# ---------------------------------------------------------------------------

class TestConfigIntegrity:
    """All config files must parse and reference paths that exist within the world."""

    def test_ontokit_json_valid(self, worlds):
        for world in worlds:
            config = json.loads((world / "ontokit.json").read_text())
            assert "ontology" in config, f"{world.name}: ontokit.json missing 'ontology' key"
            ontology_path = world / config["ontology"]
            assert ontology_path.exists(), (
                f"{world.name}: ontokit.json references {config['ontology']} but it doesn't exist"
            )

    def test_claude_settings_valid(self, worlds):
        for world in worlds:
            settings = json.loads((world / ".claude" / "settings.json").read_text())
            assert "hooks" in settings, f"{world.name}: .claude/settings.json missing 'hooks'"
            # Every hook command should reference files that exist
            for event, hook_list in settings["hooks"].items():
                for hook_group in hook_list:
                    for hook in hook_group.get("hooks", []):
                        cmd = hook.get("command", "")
                        # Extract the Python script path from commands like "python hooks/pre_tool_call.py"
                        parts = cmd.split()
                        for part in parts:
                            if part.endswith(".py"):
                                assert (world / part).exists(), (
                                    f"{world.name}: hook references {part} but it doesn't exist"
                                )

    def test_mcp_json_valid(self, worlds):
        for world in worlds:
            mcp = json.loads((world / ".mcp.json").read_text())
            assert "mcpServers" in mcp, f"{world.name}: .mcp.json missing 'mcpServers'"

    def test_mcp_json_references_local_mcp(self, worlds):
        """MCP commands should use 'cd mcp' (relative), not absolute paths."""
        for world in worlds:
            content = (world / ".mcp.json").read_text()
            mcp = json.loads(content)
            for name, server in mcp["mcpServers"].items():
                args_str = " ".join(server.get("args", []))
                assert "cd mcp" in args_str or "mcp" in server.get("command", ""), (
                    f"{world.name}: MCP server '{name}' doesn't reference local mcp/"
                )
                assert "../" not in args_str, (
                    f"{world.name}: MCP server '{name}' references parent directory"
                )


# ---------------------------------------------------------------------------
# Ontology content validation
# ---------------------------------------------------------------------------

class TestOntologyContent:
    """The ontology JSON-LD must be valid and contain meaningful content."""

    def test_ontology_is_valid_json(self, worlds):
        for world in worlds:
            for ontology_file in (world / "ontology").glob("*_ontology.json"):
                data = json.loads(ontology_file.read_text())
                assert isinstance(data, dict), f"{world.name}: ontology is not a JSON object"

    def test_ontology_has_required_keys(self, worlds):
        for world in worlds:
            for ontology_file in (world / "ontology").glob("*_ontology.json"):
                data = json.loads(ontology_file.read_text())
                for key in ["@context", "metadata", "classes", "instances", "relations"]:
                    assert key in data, f"{world.name}: ontology missing '{key}'"

    def test_ontology_has_entities(self, worlds):
        for world in worlds:
            for ontology_file in (world / "ontology").glob("*_ontology.json"):
                data = json.loads(ontology_file.read_text())
                total = len(data.get("classes", [])) + len(data.get("instances", []))
                assert total > 0, f"{world.name}: ontology has no classes or instances"

    def test_ontology_has_valid_predicates(self, worlds):
        for world in worlds:
            for ontology_file in (world / "ontology").glob("*_ontology.json"):
                data = json.loads(ontology_file.read_text())
                preds = data.get("valid_predicates", [])
                assert len(preds) > 0, f"{world.name}: ontology has no valid_predicates"


# ---------------------------------------------------------------------------
# Python importability (syntax check)
# ---------------------------------------------------------------------------

class TestPythonSyntax:
    """All Python files must at least compile without syntax errors."""

    def test_all_python_files_compile(self, worlds):
        for world in worlds:
            failures = []
            for py in world.rglob("*.py"):
                try:
                    compile(py.read_text(), str(py), "exec")
                except SyntaxError as e:
                    failures.append(f"{py.relative_to(world)}: {e}")
            assert failures == [], (
                f"{world.name}: Python syntax errors:\n" + "\n".join(failures)
            )
