#!/usr/bin/env python3
"""
demo.py
-------
Demonstration of Structured Decoding with any ontology.

Reads configuration from ontokit.json for the ontology path and settings.

Usage:
    python demo.py                      # Interactive mode
    python demo.py --query "..."        # Direct query
    python demo.py --check-triple       # Triple validation demo
    python demo.py --export-schemas     # Export compiled JSON Schemas
    python demo.py --inspect <node_id>  # Inspect a node
    python demo.py --summary            # Graph summary
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ontology_graph import OntologyGraph
from src.grammar_builder import GrammarBuilder
from src.validator import OntologyValidator
from src.constrained_client import ConstrainedClient


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def demo_graph_summary(graph: OntologyGraph):
    name = graph.metadata.get("name", "Ontology")
    print_section(f"GRAPH SUMMARY — {name}")
    summary = graph.summary()
    print(f"  Total nodes    : {summary['total_nodes']}")
    print(f"  Total edges    : {summary['total_edges']}")
    print(f"  Classes        : {summary['total_classes']}")
    print(f"\n  Nodes by class:")
    for cls, count in sorted(summary['nodes_by_class'].items()):
        print(f"    {cls:<25} {count} instance(s)")
    print(f"\n  Valid predicates ({len(summary['valid_predicates'])}):")
    print(f"    {', '.join(sorted(summary['valid_predicates']))}")


def demo_validation(validator: OntologyValidator, graph: OntologyGraph):
    print_section("VALIDATION DEMO")

    # Auto-generate test cases from graph edges
    test_cases = []
    # Valid triples (from actual edges)
    for s, p, o in graph.edges[:3]:
        test_cases.append((s, p, o, True))
    # Invalid triple (swap subject/object of first edge)
    if graph.edges:
        s, p, o = graph.edges[0]
        test_cases.append((o, p, s, False))
    # Invalid entity
    test_cases.append(("NonExistentEntity", "instanceOf", "Unknown", False))

    for subject, predicate, obj, expected in test_cases:
        result = validator.validate_triple(subject, predicate, obj)
        status = "✅" if result.valid == expected else "❌ UNEXPECTED"
        print(f"\n  {status} ({subject}, {predicate}, {obj})")
        print(f"     Valid: {result.valid}  Score: {result.score:.2f}")
        if result.errors:
            for e in result.errors:
                print(f"     Error: {e}")
        if result.warnings:
            for w in result.warnings:
                print(f"     ⚠️  {w}")
        if result.corrections:
            for c in result.corrections:
                print(f"     → Suggestion: {c}")


def demo_grammar(builder: GrammarBuilder, graph: OntologyGraph):
    name = graph.metadata.get("name", "Ontology")
    print_section(f"COMPILED GRAMMARS — {name}")

    # Schema for the first class with instances
    for cls_id in graph.classes:
        instances = graph.get_instances_of(cls_id)
        if instances:
            schema = builder.schema_for_class(cls_id)
            print(f"\n  Valid {cls_id} instances ({len(schema['enum'])}):")
            print(f"    {schema['enum'][:10]}{'...' if len(schema['enum']) > 10 else ''}")
            break

    # Structured response schema
    schema3 = builder.schema_query_response()
    print(f"\n  Structured response schema:")
    print(f"    Required fields: {schema3['required']}")
    entities_enum = schema3['properties']['entities_mentioned']['items']['enum']
    predicates_enum = schema3['properties']['supporting_triples']['items']['properties']['predicate']['enum']
    print(f"    Enumerated entities: {len(entities_enum)}")
    print(f"    Enumerated predicates: {len(predicates_enum)}")

    # System prompt fragment
    print(f"\n  System Prompt fragment:")
    print(f"  {'─'*50}")
    fragment = builder.build_system_prompt_fragment()
    for line in fragment.split('\n')[:15]:
        print(f"  {line}")
    print("  [...]")


def demo_subgraph(graph: OntologyGraph, node_id: str):
    print_section(f"SUBGRAPH AROUND '{node_id}'")
    node = graph.get_node(node_id)
    if not node:
        print(f"  Node '{node_id}' not found. Available entities:")
        print(f"  {list(graph.nodes.keys())[:20]}...")
        return

    print(f"  Node: {node.label} ({node.cls})")
    if node.wikidata:
        print(f"  Wikidata: https://www.wikidata.org/wiki/{node.wikidata}")

    subgraph = graph.subgraph_around(node_id, depth=1)
    print(f"\n  Direct neighbors ({len(subgraph['edges'])} edges):")
    for edge in subgraph["edges"]:
        src = graph.get_node(edge["subject"])
        tgt = graph.get_node(edge["object"])
        src_label = src.label if src else edge["subject"]
        tgt_label = tgt.label if tgt else edge["object"]
        print(f"    {src_label}  ─[{edge['predicate']}]→  {tgt_label}")


def demo_export_schemas(builder: GrammarBuilder):
    print_section("EXPORT JSON SCHEMAS")
    output_dir = ROOT / "ontology" / "schemas"
    exported = builder.export_all_schemas(output_dir)
    print(f"  {len(exported)} schemas exported to {output_dir}/")
    for path in exported[:10]:
        size = Path(path).stat().st_size
        print(f"    {Path(path).name:<35} {size} bytes")


def demo_query(client: ConstrainedClient, question: str):
    """Output ontology context and schema for a query.

    Claude Code is the LLM — this provides the constraints it must follow.
    """
    name = client.builder.ontology_name
    print_section(f"CONSTRAINED QUERY — {name}")
    print(f"  Q: {question[:60]}...")

    result = client.query(question)

    print(f"\n  📋 Ontology context loaded.")
    print(f"  Valid entities: {len(result['valid_entities'])}")
    print(f"  Valid predicates: {result['valid_predicates']}")
    if result.get("focus_node"):
        print(f"  Focus node: {result['focus_node']}")

    print(f"\n  📐 Response schema (required fields):")
    schema = result["schema"]
    if "required" in schema:
        print(f"     {schema['required']}")

    print(f"\n  💡 System prompt fragment (first 10 lines):")
    for line in result["system_prompt"].split('\n')[:10]:
        print(f"     {line}")
    print("     [...]")

    # Output full schema as JSON for Claude Code to use
    print(f"\n  📦 Full schema:")
    print(json.dumps(schema, indent=2))


def interactive_mode(client: ConstrainedClient, graph: OntologyGraph):
    name = graph.metadata.get("name", "Ontology")
    print_section(f"INTERACTIVE MODE — Structured Decoding — {name}")
    print("\n  Available commands:")
    print("    <question>              Ontology-constrained query (outputs context)")
    print("    inspect <id>            Inspect a graph node")
    print("    check <s> <p> <o>       Validate a triple")
    print("    search <term>           Search the ontology")
    print("    quit / exit             Quit")
    print()

    validator = OntologyValidator(graph)

    while True:
        try:
            user_input = input("  → ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("  Goodbye!")
            break

        parts = user_input.split()
        cmd = parts[0].lower()

        if cmd == "inspect" and len(parts) >= 2:
            demo_subgraph(graph, parts[1])

        elif cmd == "check" and len(parts) >= 4:
            s, p, o = parts[1], parts[2], parts[3]
            result = validator.validate_triple(s, p, o)
            print(f"\n  {result.summary()}\n")

        elif cmd == "search" and len(parts) >= 2:
            term = " ".join(parts[1:])
            results = graph.search(term)
            if results:
                print(f"\n  {len(results)} result(s) for '{term}':")
                for node in results[:8]:
                    print(f"    • {node.id:<25} {node.label}")
            else:
                print(f"  No results for '{term}'")

        else:
            demo_query(client, user_input)


def main():
    # Load configuration
    config = load_config(ROOT)

    parser = argparse.ArgumentParser(description=f"Structured Decoding — Ontology Enforcement")
    parser.add_argument("--query", "-q", type=str, help="Question for the constrained LLM")
    parser.add_argument("--inspect", "-i", type=str, help="Inspect a graph node")
    parser.add_argument("--check-triple", action="store_true", help="Triple validation demo")
    parser.add_argument("--export-schemas", action="store_true", help="Export JSON Schemas")
    parser.add_argument("--summary", "-s", action="store_true", help="Graph summary")
    parser.add_argument("--grammar", "-g", action="store_true", help="Grammar compilation demo")
    parser.add_argument("--all", "-a", action="store_true", help="Run all demos")
    args = parser.parse_args()

    # Load the graph
    graph = OntologyGraph(config.ontology_path)
    name = graph.metadata.get("name", "Ontology")
    print(f"\n📂 Loading ontology: {name}...")
    builder = GrammarBuilder(graph)
    validator = OntologyValidator(graph)
    summary = graph.summary()
    print(f"   {summary['total_nodes']} nodes, {summary['total_edges']} edges loaded.\n")

    # Create client (no API key needed — runs inside Claude Code)
    client = ConstrainedClient(graph, verbose=True, config=config)

    # Dispatch commands
    if args.summary or args.all:
        demo_graph_summary(graph)

    if args.grammar or args.all:
        demo_grammar(builder, graph)

    if args.check_triple or args.all:
        demo_validation(validator, graph)

    if args.export_schemas or args.all:
        demo_export_schemas(builder)

    if args.inspect:
        demo_subgraph(graph, args.inspect)

    if args.query:
        demo_query(client, args.query)

    # No options: interactive mode
    if not any([args.query, args.inspect, args.check_triple,
                args.export_schemas, args.summary, args.grammar, args.all]):
        interactive_mode(client, graph)


if __name__ == "__main__":
    main()
