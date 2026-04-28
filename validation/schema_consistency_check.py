import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_FILE = ROOT / "fusion_api_server" / "modeling.py"
SCHEMA_FILE = ROOT / "functions" / "functions.json"


def _load_json_with_dups(path: Path):
    raw = path.read_text(encoding="utf-8")
    dup_keys = []

    def hook(pairs):
        seen = set()
        obj = {}
        for k, v in pairs:
            if k in seen:
                dup_keys.append(k)
            seen.add(k)
            obj[k] = v
        return obj

    data = json.loads(raw, object_pairs_hook=hook)
    return data, dup_keys


def _get_controller_methods(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    methods = {}

    class_finder = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FusionApiController":
            class_finder = node
            break

    if not class_finder:
        return methods

    public_name = re.compile(r"^[A-Z][A-Z0-9_]+$")

    for node in class_finder.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        if not public_name.match(node.name):
            continue

        args = []
        defaults = []
        for arg in node.args.args:
            args.append(arg.arg)
        defaults = node.args.defaults

        required = []
        optional = []
        if args and args[0] == "self":
            args = args[1:]

        required_count = max(0, len(args) - len(defaults))
        required = args[:required_count]
        optional = args[required_count:]

        has_varargs = node.args.vararg is not None
        has_kwargs = node.args.kwarg is not None

        methods[node.name] = {
            "args": args,
            "required": required,
            "optional": optional,
            "has_varargs": has_varargs,
            "has_kwargs": has_kwargs,
        }

    return methods


def main():
    schema, dup_keys = _load_json_with_dups(SCHEMA_FILE)
    methods = _get_controller_methods(MODEL_FILE)

    schema_methods = set(schema.keys())
    impl_methods = set(methods.keys())

    missing_in_impl = sorted(schema_methods - impl_methods)
    missing_in_schema = sorted(impl_methods - schema_methods)

    print("schema_count", len(schema_methods))
    print("impl_count", len(impl_methods))
    print("missing_in_impl", missing_in_impl)
    print("missing_in_schema", missing_in_schema)

    if dup_keys:
        print("duplicate_keys_detected", sorted(set(dup_keys)))
    else:
        print("duplicate_keys_detected", [])

    required_mismatches = []
    unknown_inputs = []

    for name, spec in schema.items():
        inputs = spec.get("inputs", {})
        required = inputs.get("required", [])
        properties = inputs.get("properties", {})

        if name not in methods:
            continue

        sig = methods[name]
        args = set(sig["args"])

        if not sig["has_kwargs"]:
            for req in required:
                if req not in args:
                    required_mismatches.append((name, req))

        for prop in properties.keys():
            if prop not in args and not sig["has_kwargs"]:
                unknown_inputs.append((name, prop))

        for req in required:
            if req not in properties:
                required_mismatches.append((name, f"{req} (not in properties)"))

    if required_mismatches:
        print("required_mismatches", required_mismatches)
    else:
        print("required_mismatches", [])

    if unknown_inputs:
        print("unknown_inputs", unknown_inputs)
    else:
        print("unknown_inputs", [])

    output_mismatches = []
    for name, spec in schema.items():
        outputs = spec.get("outputs", {})
        if not isinstance(outputs, dict):
            continue
        required = outputs.get("required", [])
        properties = outputs.get("properties", {})
        if required and properties:
            for req in required:
                if req not in properties:
                    output_mismatches.append((name, req))

    if output_mismatches:
        print("output_required_missing_properties", output_mismatches)
    else:
        print("output_required_missing_properties", [])


if __name__ == "__main__":
    main()
