#!/usr/bin/env python3
"""
Geometry-Assembly Contract Validator

Validates that assembly plans strictly adhere to the geometry-assembly contract.
This tool can be run standalone to verify contract compliance before pipeline execution.

Usage:
    python tools/validate_contract.py --contract path/to/geometry_semantics_assembly_round_1.json \
                                      --assembly path/to/assembly_patch.json

    python tools/validate_contract.py \
        --contract execution/runs/20260202_120000/planning/geometry_semantics_assembly_round_1.json \
        --assembly execution/runs/20260202_120000/planning/assembly_semantics_round_1.json
    0 - Validation passed (no violations)
    1 - Validation failed (contract violations found)
    2 - Error (file not found, invalid JSON, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

try:
    from jsonschema import Draft202012Validator, ValidationError
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


class ContractValidator:
    """Validates assembly plans against geometry-assembly contracts"""
    
    def __init__(self, contract: Mapping[str, Any]):
        self.contract = contract
        self.components = {c["component_id"]: c for c in contract.get("components", [])}
        
        # Build interface lookup: {component_id: {interface_id: interface_data}}
        self.interfaces = {}
        for comp in contract.get("components", []):
            comp_id = comp["component_id"]
            self.interfaces[comp_id] = {
                iface["interface_id"]: iface
                for iface in comp.get("interfaces", [])
            }
        
        self.allowable_attachments = set(contract.get("allowable_attachment_types", []))
        self.prohibited_dof = contract.get("prohibited_degrees_of_freedom", {})
        self.violations = []
    
    def validate_assembly_patch(self, patch: Mapping[str, Any]) -> List[str]:
        """
        Validate assembly patch against contract.
        
        Returns list of violation messages (empty if valid).
        """
        self.violations = []
        
        steps = patch.get("steps", [])
        for step_idx, step in enumerate(steps):
            self._validate_step(step, step_idx)
        
        return self.violations
    
    def _validate_step(self, step: Mapping[str, Any], step_idx: int):
        """Validate a single assembly step"""
        step_id = step.get("id", f"step_{step_idx}")
        function = step.get("function", "")
        inputs = step.get("inputs", {})
        
        # Skip non-assembly functions
        if not self._is_assembly_function(function):
            return
        
        # Extract component and interface references
        component_refs = []
        interface_refs = []
        
        for key, value in inputs.items():
            if isinstance(value, str):
                # Check for component references
                if "component" in key.lower() or "occ" in key.lower() or "part" in key.lower():
                    component_refs.append((key, value))
                
                # Check for interface references (pattern: component_id.interface_id)
                if "." in value:
                    parts = value.split(".", 1)
                    if len(parts) == 2:
                        interface_refs.append((key, parts[0], parts[1]))
        
        # Validate component existence
        for param_name, comp_id in component_refs:
            self._validate_component_exists(step_id, function, param_name, comp_id)
        
        # Validate interface existence and compatibility
        for param_name, comp_id, iface_id in interface_refs:
            self._validate_interface_exists(step_id, function, param_name, comp_id, iface_id)
        
        # Validate attachment type
        attachment_type = self._infer_attachment_type(function)
        if attachment_type:
            self._validate_attachment_type(step_id, function, attachment_type)
    
    def _is_assembly_function(self, function: str) -> bool:
        """Check if function is an assembly operation"""
        keywords = ["MATE", "JOINT", "CONSTRAINT", "ATTACH", "ASSEMBLE", "CONNECT"]
        return any(keyword in function.upper() for keyword in keywords)
    
    def _validate_component_exists(
        self,
        step_id: str,
        function: str,
        param_name: str,
        comp_id: str
    ):
        """Validate that component exists in contract"""
        if comp_id not in self.components:
            available = ", ".join(sorted(self.components.keys()))
            self.violations.append(
                f"Step '{step_id}' ({function}): "
                f"Parameter '{param_name}' references unknown component '{comp_id}'. "
                f"Available components in contract: {available}"
            )
    
    def _validate_interface_exists(
        self,
        step_id: str,
        function: str,
        param_name: str,
        comp_id: str,
        iface_id: str
    ):
        """Validate that interface exists in contract"""
        if comp_id not in self.components:
            available = ", ".join(sorted(self.components.keys()))
            self.violations.append(
                f"Step '{step_id}' ({function}): "
                f"Parameter '{param_name}' references interface on unknown component '{comp_id}'. "
                f"Available components: {available}"
            )
            return
        
        if comp_id not in self.interfaces:
            self.violations.append(
                f"Step '{step_id}' ({function}): "
                f"Component '{comp_id}' has no interfaces declared in contract."
            )
            return
        
        if iface_id not in self.interfaces[comp_id]:
            available = ", ".join(sorted(self.interfaces[comp_id].keys()))
            self.violations.append(
                f"Step '{step_id}' ({function}): "
                f"Interface '{comp_id}.{iface_id}' not declared in contract. "
                f"Available interfaces for '{comp_id}': {available}"
            )
    
    def _validate_attachment_type(
        self,
        step_id: str,
        function: str,
        attachment_type: str
    ):
        """Validate that attachment type is allowable"""
        if attachment_type not in self.allowable_attachments:
            allowed = ", ".join(sorted(self.allowable_attachments))
            self.violations.append(
                f"Step '{step_id}' ({function}): "
                f"Uses attachment type '{attachment_type}' which is not in allowable list. "
                f"Allowable types: {allowed}"
            )
    
    @staticmethod
    def _infer_attachment_type(function_name: str) -> str | None:
        """Infer attachment type from CAD function name"""
        fn_upper = function_name.upper()
        
        if "RIGID" in fn_upper or "FIXED" in fn_upper:
            return "rigid"
        elif "REVOLUTE" in fn_upper or "HINGE" in fn_upper or "PIN" in fn_upper:
            return "revolute"
        elif "SLIDER" in fn_upper or "SLIDE" in fn_upper:
            return "slider"
        elif "CYLINDRICAL" in fn_upper:
            return "cylindrical"
        elif "PIN_SLOT" in fn_upper:
            return "pin_slot"
        elif "PLANAR" in fn_upper:
            return "planar"
        elif "BALL" in fn_upper or "SPHERE" in fn_upper:
            return "ball"
        else:
            return None


def validate_contract_schema(contract: Dict[str, Any], schema_path: Path) -> List[str]:
    """Validate contract against JSON schema"""
    if not HAS_JSONSCHEMA:
        return ["WARNING: jsonschema not installed, skipping schema validation"]
    
    if not schema_path.exists():
        return [f"WARNING: Schema not found: {schema_path}"]
    
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(contract))
        
        if errors:
            return [
                f"Contract schema validation error: {err.message} at {'/'.join(str(p) for p in err.path)}"
                for err in errors[:10]  # Limit to first 10 errors
            ]
        
        return []
    
    except Exception as e:
        return [f"ERROR validating contract schema: {e}"]


def print_report(
    contract_path: Path,
    assembly_path: Path,
    violations: List[str],
    schema_errors: List[str]
):
    """Print validation report"""
    print("=" * 80)
    print("GEOMETRY-ASSEMBLY CONTRACT VALIDATION REPORT")
    print("=" * 80)
    print()
    print(f"Contract: {contract_path}")
    print(f"Assembly: {assembly_path}")
    print()
    
    if schema_errors:
        print("CONTRACT SCHEMA VALIDATION:")
        for error in schema_errors:
            print(f"  ⚠ {error}")
        print()
    
    if violations:
        print(f"VIOLATIONS FOUND: {len(violations)}")
        print()
        for i, violation in enumerate(violations, 1):
            print(f"{i}. {violation}")
            print()
        print("=" * 80)
        print("RESULT: VALIDATION FAILED ❌")
        print("=" * 80)
        print()
        print("Assembly plan violates the geometry-assembly contract.")
        print("Only components, interfaces, and attachment types declared in the")
        print("contract are allowed. Please fix the violations and try again.")
    else:
        print("=" * 80)
        print("RESULT: VALIDATION PASSED ✓")
        print("=" * 80)
        print()
        print("Assembly plan fully complies with the geometry-assembly contract.")


def main():
    parser = argparse.ArgumentParser(
        description="Validate assembly plans against geometry-assembly contract",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate specific files
  python tools/validate_contract.py \
      --contract execution/runs/20260202_120000/planning/geometry_semantics_assembly_round_1.json \
      --assembly execution/runs/20260202_120000/planning/assembly_patch_round_1.json
  
  # Validate latest run
  python tools/validate_contract.py --run-dir execution/runs/20260202_120000 --round 1
        """
    )
    
    parser.add_argument(
        "--contract",
        type=Path,
        help="Path to geometry_semantics_assembly_round_{N}.json"
    )
    parser.add_argument(
        "--assembly",
        type=Path,
        help="Path to assembly_patch_round_N.json"
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Run directory (alternative to --contract/--assembly)"
    )
    parser.add_argument(
        "--round",
        type=int,
        default=1,
        help="Round index (used with --run-dir, default: 1)"
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("planning/geometry_assembly_contract_schema.json"),
        help="Path to contract schema (default: planning/geometry_assembly_contract_schema.json)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output, only return exit code"
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    if args.run_dir:
        contract_path = args.run_dir / "planning" / f"geometry_semantics_assembly_round_{args.round}.json"
        assembly_path = args.run_dir / "planning" / f"assembly_patch_round_{args.round}.json"
    elif args.contract and args.assembly:
        contract_path = args.contract
        assembly_path = args.assembly
    else:
        parser.error("Either --run-dir or both --contract and --assembly must be provided")
    
    # Check file existence
    if not contract_path.exists():
        print(f"ERROR: Contract not found: {contract_path}", file=sys.stderr)
        sys.exit(2)
    
    if not assembly_path.exists():
        print(f"ERROR: Assembly patch not found: {assembly_path}", file=sys.stderr)
        sys.exit(2)
    
    # Load files
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        assembly = json.loads(assembly_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to load JSON: {e}", file=sys.stderr)
        sys.exit(2)
    
    # Validate contract schema
    schema_errors = validate_contract_schema(contract, args.schema)
    
    # Validate assembly against contract
    validator = ContractValidator(contract)
    violations = validator.validate_assembly_patch(assembly)
    
    # Print report
    if not args.quiet:
        print_report(contract_path, assembly_path, violations, schema_errors)
    
    # Exit with appropriate code
    if violations:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
