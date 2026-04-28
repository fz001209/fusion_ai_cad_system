"""
Interface Declaration Validator

Validates that all assembly constraints reference only declared interfaces
from geometry generation output.

Usage:
    python tools/validate_interface_declarations.py --run-dir <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_declared_interfaces(geometry_plan: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Extract all declared interfaces from geometry plan.
    
    Returns: {component_id: {interface_id: interface_declaration}}
    """
    declared = {}
    
    steps = geometry_plan.get("steps", [])
    if not isinstance(steps, list):
        return declared
    
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        
        exports = step.get("exports")
        if not isinstance(exports, Mapping):
            continue
        
        component_id = exports.get("component_id")
        interfaces = exports.get("interfaces", [])
        
        if not isinstance(component_id, str) or not isinstance(interfaces, list):
            continue
        
        component_interfaces = {}
        for iface in interfaces:
            if isinstance(iface, Mapping):
                iface_id = iface.get("interface_id")
                if isinstance(iface_id, str):
                    component_interfaces[iface_id] = iface
        
        if component_interfaces:
            declared[component_id] = component_interfaces
    
    return declared


def extract_assembly_references(kg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract all interface references from KG relations.
    
    Returns: List of {relation_id, a: {component, interface}, b: {component, interface}}
    """
    references = []
    
    relations = kg.get("relations", [])
    if not isinstance(relations, list):
        return references
    
    for rel in relations:
        if not isinstance(rel, Mapping):
            continue
        
        a = rel.get("a", {})
        b = rel.get("b", {})
        
        if not isinstance(a, Mapping) or not isinstance(b, Mapping):
            continue
        
        references.append({
            "relation_id": rel.get("id"),
            "relation_type": rel.get("type"),
            "a": {
                "component_id": a.get("component_id"),
                "interface_id": a.get("interface_id")
            },
            "b": {
                "component_id": b.get("component_id"),
                "interface_id": b.get("interface_id")
            }
        })
    
    return references


def validate_interface_declarations(
    declared_interfaces: Dict[str, Dict[str, Any]],
    assembly_references: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate that all assembly references use declared interfaces.
    
    Returns validation report with errors and warnings.
    """
    errors = []
    warnings = []
    validated = []
    
    for ref in assembly_references:
        rel_id = ref["relation_id"]
        
        # Validate endpoint A
        a_comp = ref["a"]["component_id"]
        a_if = ref["a"]["interface_id"]
        
        if not a_comp or not a_if:
            errors.append({
                "relation_id": rel_id,
                "endpoint": "A",
                "error": "Missing component_id or interface_id",
                "severity": "CRITICAL"
            })
            continue
        
        if a_comp not in declared_interfaces:
            errors.append({
                "relation_id": rel_id,
                "endpoint": "A",
                "component_id": a_comp,
                "error": f"Component '{a_comp}' has NO declared interfaces",
                "available_components": sorted(declared_interfaces.keys()),
                "severity": "CRITICAL"
            })
        elif a_if not in declared_interfaces[a_comp]:
            errors.append({
                "relation_id": rel_id,
                "endpoint": "A",
                "component_id": a_comp,
                "interface_id": a_if,
                "error": f"Interface '{a_if}' NOT declared on component '{a_comp}'",
                "declared_interfaces": sorted(declared_interfaces[a_comp].keys()),
                "severity": "CRITICAL"
            })
        
        # Validate endpoint B
        b_comp = ref["b"]["component_id"]
        b_if = ref["b"]["interface_id"]
        
        if not b_comp or not b_if:
            errors.append({
                "relation_id": rel_id,
                "endpoint": "B",
                "error": "Missing component_id or interface_id",
                "severity": "CRITICAL"
            })
            continue
        
        if b_comp not in declared_interfaces:
            errors.append({
                "relation_id": rel_id,
                "endpoint": "B",
                "component_id": b_comp,
                "error": f"Component '{b_comp}' has NO declared interfaces",
                "available_components": sorted(declared_interfaces.keys()),
                "severity": "CRITICAL"
            })
        elif b_if not in declared_interfaces[b_comp]:
            errors.append({
                "relation_id": rel_id,
                "endpoint": "B",
                "component_id": b_comp,
                "interface_id": b_if,
                "error": f"Interface '{b_if}' NOT declared on component '{b_comp}'",
                "declared_interfaces": sorted(declared_interfaces[b_comp].keys()),
                "severity": "CRITICAL"
            })
        
        # If both endpoints valid, mark as validated
        if (a_comp in declared_interfaces and a_if in declared_interfaces[a_comp] and
            b_comp in declared_interfaces and b_if in declared_interfaces[b_comp]):
            validated.append({
                "relation_id": rel_id,
                "a": {"component": a_comp, "interface": a_if},
                "b": {"component": b_comp, "interface": b_if},
                "status": "VALID"
            })
    
    return {
        "validation_status": "PASS" if len(errors) == 0 else "FAIL",
        "total_relations": len(assembly_references),
        "validated_count": len(validated),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "validated_relations": validated,
        "declared_interface_summary": {
            comp: sorted(interfaces.keys())
            for comp, interfaces in declared_interfaces.items()
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Validate interface declarations")
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="Run directory containing geometry plan and knowledge graph")
    parser.add_argument("--round-index", type=int, default=1,
                        help="Round index for geometry plan")
    parser.add_argument("--output", type=Path,
                        help="Optional output file for validation report")
    
    args = parser.parse_args()
    
    # Load geometry plan
    geom_path = args.run_dir / "planning" / f"geometry_plan_round_{args.round_index}.json"
    if not geom_path.exists():
        print(f"ERROR: Geometry plan not found: {geom_path}", file=sys.stderr)
        sys.exit(1)
    
    geometry_plan = _read_json(geom_path)
    
    # Load knowledge graph
    kg_path = args.run_dir / "knowledge" / "knowledge_graph.json"
    if not kg_path.exists():
        print(f"ERROR: Knowledge graph not found: {kg_path}", file=sys.stderr)
        sys.exit(1)
    
    kg = _read_json(kg_path)
    
    # Extract declarations and references
    declared_interfaces = extract_declared_interfaces(geometry_plan)
    assembly_references = extract_assembly_references(kg)
    
    # Validate
    report = validate_interface_declarations(declared_interfaces, assembly_references)
    
    # Print report
    print("=" * 80)
    print("INTERFACE DECLARATION VALIDATION REPORT")
    print("=" * 80)
    print()
    
    print(f"Status: {report['validation_status']}")
    print(f"Total Relations: {report['total_relations']}")
    print(f"Validated: {report['validated_count']}")
    print(f"Errors: {report['error_count']}")
    print(f"Warnings: {report['warning_count']}")
    print()
    
    if report["declared_interface_summary"]:
        print("Declared Interfaces:")
        for comp, interfaces in sorted(report["declared_interface_summary"].items()):
            print(f"  {comp}: {', '.join(interfaces)}")
        print()
    else:
        print("WARNING: No interfaces declared in geometry plan!")
        print()
    
    if report["errors"]:
        print("ERRORS:")
        for error in report["errors"]:
            print(f"  - Relation '{error.get('relation_id')}' [{error.get('endpoint')}]:")
            print(f"    {error['error']}")
            if "declared_interfaces" in error:
                print(f"    Declared: {error['declared_interfaces']}")
            if "available_components" in error:
                print(f"    Available components: {error['available_components']}")
            print()
    
    if report["warnings"]:
        print("WARNINGS:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
        print()
    
    if report["validated_relations"]:
        print(f"Validated Relations ({len(report['validated_relations'])}):")
        for val in report["validated_relations"]:
            print(f"  ✓ {val['relation_id']}: "
                  f"{val['a']['component']}.{val['a']['interface']} <-> "
                  f"{val['b']['component']}.{val['b']['interface']}")
        print()
    
    # Save report if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"Report saved to: {args.output}")
    
    # Exit with error code if validation failed
    sys.exit(0 if report["validation_status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
