#!/usr/bin/env python3
"""
create_world.py
---------------
Creates a self-contained ontology-enforced Claude Code environment
for a given domain.

Usage:
    python create_world.py "economics"
    python create_world.py "cosmetics regulation" --language fr --limit 30

This creates a <domain>_world/ subfolder containing:
  - src/           → enforcement engine (graph, schemas, validator, client)
  - hooks/         → Claude Code pre/post tool hooks
  - ontology/      → JSON-LD ontology + compiled schemas
  - .claude/       → hook configuration
  - ontokit.json   → framework config
  - CLAUDE.md      → auto-generated rules for the domain
  - demo.py        → interactive demo / query tool

Each world is fully self-contained — you can open Claude Code inside it
for a constrained conversation grounded in that domain's ontology.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def create_world(
    domain: str,
    language: str = "en",
    limit: int = 30,
    root: Path = ROOT,
) -> Path:
    """Create a self-contained world folder for the given domain."""

    # 1. Derive folder name
    slug = re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")
    world_dir = root / f"{slug}_world"

    if world_dir.exists():
        print(f"⚠️  World '{world_dir.name}' already exists. Overwriting...", file=sys.stderr)
        shutil.rmtree(world_dir)

    world_dir.mkdir(parents=True)
    print(f"\n🌍 Creating world: {world_dir.name}/\n", file=sys.stderr)

    # 2. Copy enforcement engine source
    src_source = root / "src"
    src_dest = world_dir / "src"
    shutil.copytree(src_source, src_dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"  📦 Copied enforcement engine → src/", file=sys.stderr)

    # 3. Copy hooks
    hooks_source = root / "hooks"
    hooks_dest = world_dir / "hooks"
    shutil.copytree(hooks_source, hooks_dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"  🪝 Copied hooks → hooks/", file=sys.stderr)

    # 4. Copy demo.py
    shutil.copy2(root / "demo.py", world_dir / "demo.py")

    # 5. Copy .claude/settings.json (hooks config)
    claude_dir = world_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "hooks": {
            "PreToolUse": [{
                "matcher": ".*",
                "hooks": [{"type": "command", "command": "python hooks/pre_tool_call.py", "timeout": 10}]
            }],
            "PostToolUse": [{
                "matcher": ".*",
                "hooks": [{"type": "command", "command": "python hooks/post_tool_call.py", "timeout": 10}]
            }]
        }
    }
    with open(claude_dir / "settings.json", "w") as f:
        json.dump(settings, f, indent=2)

    # Also allow python execution
    settings_local = {"permissions": {"allow": ["Bash(python:*)"]}}
    with open(claude_dir / "settings.local.json", "w") as f:
        json.dump(settings_local, f, indent=2)

    print(f"  ⚙️  Configured .claude/settings.json", file=sys.stderr)

    # 6. Build the ontology via OKG + Wikidata
    # Import from the root src (not the copy)
    sys.path.insert(0, str(root))
    from src.ontology_builder import build_ontology
    from src.config import OntoKitConfig
    from src.claude_md_generator import generate as generate_claude_md

    ontology_data = build_ontology(domain, language=language, limit=limit)

    if not ontology_data or not ontology_data.get("instances"):
        print("❌ Failed to build ontology — no entities found.", file=sys.stderr)
        shutil.rmtree(world_dir)
        sys.exit(1)

    # Write ontology file
    ontology_dir = world_dir / "ontology"
    ontology_dir.mkdir(parents=True, exist_ok=True)
    ontology_filename = f"{slug}_ontology.json"
    ontology_path = ontology_dir / ontology_filename
    with open(ontology_path, "w", encoding="utf-8") as f:
        json.dump(ontology_data, f, ensure_ascii=False, indent=2)
    print(f"  🧬 Built ontology → ontology/{ontology_filename}", file=sys.stderr)

    # 7. Create ontokit.json
    config_data = {
        "ontology": f"ontology/{ontology_filename}",
        "tool_name": "ontology_grounded_response",
        "validation_threshold": 0.5,
        "max_retries": 3,
        "language": language,
        "log_file": "validation_log.jsonl",
    }
    with open(world_dir / "ontokit.json", "w") as f:
        json.dump(config_data, f, indent=2)

    # 8. Generate CLAUDE.md
    # Need to reload from the world's own copy
    sys.path.insert(0, str(world_dir))
    from src.ontology_graph import OntologyGraph
    from src.grammar_builder import GrammarBuilder

    config = OntoKitConfig(
        ontology=f"ontology/{ontology_filename}",
        tool_name="ontology_grounded_response",
        language=language,
        _root=world_dir,
    )
    graph = OntologyGraph(ontology_path)
    claude_md = generate_claude_md(graph, config)
    with open(world_dir / "CLAUDE.md", "w", encoding="utf-8") as f:
        f.write(claude_md)
    print(f"  📝 Generated CLAUDE.md", file=sys.stderr)

    # 9. Export compiled schemas
    builder = GrammarBuilder(graph)
    schemas_dir = ontology_dir / "schemas"
    exported = builder.export_all_schemas(schemas_dir)
    print(f"  📋 Exported {len(exported)} JSON Schemas", file=sys.stderr)

    # 10. Copy requirements.txt
    shutil.copy2(root / "requirements.txt", world_dir / "requirements.txt")

    # Summary
    summary = graph.summary()
    meta = graph.metadata
    name = meta.get("name", domain.title())

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  ✅ World ready: {world_dir.name}/", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Domain:     {name}", file=sys.stderr)
    print(f"  Nodes:      {summary['total_nodes']}", file=sys.stderr)
    print(f"  Edges:      {summary['total_edges']}", file=sys.stderr)
    print(f"  Predicates: {len(summary['valid_predicates'])}", file=sys.stderr)
    print(f"  Classes:    {summary['total_classes']}", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"  To enter this world:", file=sys.stderr)
    print(f"    cd {world_dir.name}", file=sys.stderr)
    print(f"    claude          # Start Claude Code — constrained to {name}", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"  Or test it:", file=sys.stderr)
    print(f"    cd {world_dir.name} && python demo.py --summary", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    return world_dir


def main():
    parser = argparse.ArgumentParser(
        description="Create an ontology-enforced Claude Code world",
        epilog="Example: python create_world.py 'economics' --language en --limit 25",
    )
    parser.add_argument("domain", type=str, help="Domain / topic (e.g., 'economics', 'cosmetics regulation')")
    parser.add_argument("--language", "-l", default="en", help="Language code (default: en)")
    parser.add_argument("--limit", type=int, default=30, help="Max entities to discover (default: 30)")
    args = parser.parse_args()

    create_world(args.domain, language=args.language, limit=args.limit)


if __name__ == "__main__":
    main()
