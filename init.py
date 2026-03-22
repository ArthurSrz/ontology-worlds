#!/usr/bin/env python3
"""
init.py
-------
Scaffolds a new ontology-enforced Claude Code project.

Two modes:
  Mode A: From existing JSON-LD file
    python init.py --ontology path/to/my_ontology.json [--language en]

  Mode B: Build from domain query (OKG + Wikidata pipeline)
    python init.py --build "cosmetics regulation" [--language fr] [--limit 30]

Steps:
  1. Load or build the ontology file
  2. Validate it (has classes, instances, relations, valid_predicates)
  3. Add metadata block if missing
  4. Create ontokit.json config
  5. Generate CLAUDE.md from ontology
  6. Export compiled JSON schemas
  7. Print summary
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.config import OntoKitConfig, get_ontology_metadata
from src.ontology_graph import OntologyGraph
from src.grammar_builder import GrammarBuilder
from src.claude_md_generator import generate as generate_claude_md


def validate_ontology(data: dict) -> list[str]:
    """Check that the ontology file has the required sections."""
    errors = []
    if not data.get("classes"):
        errors.append("Missing 'classes' section (or it is empty)")
    if not data.get("instances"):
        errors.append("Missing 'instances' section (or it is empty)")
    if not data.get("relations"):
        errors.append("Missing 'relations' section (or it is empty)")
    if not data.get("valid_predicates"):
        errors.append("Missing 'valid_predicates' section (or it is empty)")
    return errors


def ensure_metadata(data: dict, domain: str | None = None, language: str = "en") -> dict:
    """Add metadata block if absent."""
    if "metadata" in data:
        return data

    name = domain or "Ontology"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    data["metadata"] = {
        "name": name.title(),
        "name_short": slug,
        "description": f"Ontology for {name}",
        "language": language,
        "version": "1.0.0",
        "domain": slug,
    }
    return data


def create_config(ontology_rel_path: str, language: str) -> dict:
    """Create ontokit.json content."""
    return {
        "ontology": ontology_rel_path,
        "tool_name": "ontology_grounded_response",
        "validation_threshold": 0.5,
        "max_retries": 3,
        "language": language,
        "log_file": "validation_log.jsonl",
    }


def main():
    parser = argparse.ArgumentParser(description="Initialize ontology-enforced Claude Code project")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ontology", "-o", type=str, help="Path to existing JSON-LD ontology file")
    group.add_argument("--build", "-b", type=str, help="Domain query to build ontology from OKG + Wikidata")
    parser.add_argument("--language", "-l", default="en", help="Language code (default: en)")
    parser.add_argument("--limit", type=int, default=30, help="Max entities for --build mode (default: 30)")
    parser.add_argument("--tool-name", default="ontology_grounded_response", help="Tool name for structured output")
    args = parser.parse_args()

    print("\n🔧 Initializing ontology-enforced Claude Code project...\n")

    # Step 1: Load or build ontology
    if args.ontology:
        ontology_source = Path(args.ontology)
        if not ontology_source.exists():
            print(f"❌ Ontology file not found: {ontology_source}")
            sys.exit(1)

        with open(ontology_source, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Copy to ontology/ if not already there
        target = ROOT / "ontology" / ontology_source.name
        if ontology_source.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ontology_source, target)
            print(f"  📂 Copied ontology to {target}")
        ontology_rel = f"ontology/{ontology_source.name}"

    else:
        # Build mode
        from src.ontology_builder import build_ontology
        data = build_ontology(args.build, language=args.language, limit=args.limit)
        if not data:
            print("❌ Failed to build ontology. Check OKG/Wikidata availability.")
            sys.exit(1)

        slug = re.sub(r"[^a-z0-9]+", "_", args.build.lower()).strip("_")
        target = ROOT / "ontology" / f"{slug}_ontology.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  📂 Built ontology at {target}")
        ontology_rel = f"ontology/{target.name}"

    # Step 2: Validate
    errors = validate_ontology(data)
    if errors:
        print("⚠️  Ontology validation warnings:")
        for e in errors:
            print(f"    • {e}")

    # Step 3: Ensure metadata
    data = ensure_metadata(data, domain=args.build, language=args.language)
    meta = get_ontology_metadata(data)
    language = meta.get("language", args.language)

    # Step 4: Create ontokit.json
    config_data = create_config(ontology_rel, language)
    config_data["tool_name"] = args.tool_name
    config_path = ROOT / "ontokit.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    print(f"  ⚙️  Created {config_path}")

    # Step 5: Load graph and generate CLAUDE.md
    config = OntoKitConfig(
        ontology=ontology_rel,
        tool_name=args.tool_name,
        language=language,
        _root=ROOT,
    )
    graph = OntologyGraph(config.ontology_path)
    claude_md = generate_claude_md(graph, config)
    claude_md_path = ROOT / "CLAUDE.md"
    with open(claude_md_path, "w", encoding="utf-8") as f:
        f.write(claude_md)
    print(f"  📝 Generated {claude_md_path}")

    # Step 6: Export schemas
    builder = GrammarBuilder(graph)
    schemas_dir = ROOT / "ontology" / "schemas"
    exported = builder.export_all_schemas(schemas_dir)
    print(f"  📋 Exported {len(exported)} JSON Schemas to {schemas_dir}/")

    # Step 7: Summary
    summary = graph.summary()
    print(f"\n✅ Ready.")
    print(f"   Ontology: {meta.get('name', 'Ontology')}")
    print(f"   {summary['total_nodes']} nodes, {summary['total_edges']} edges, "
          f"{len(summary['valid_predicates'])} predicates")
    print(f"   Hooks: .claude/settings.json (PreToolUse + PostToolUse)")
    print(f"   Config: ontokit.json")
    print(f"   CLAUDE.md: auto-generated\n")


if __name__ == "__main__":
    main()
