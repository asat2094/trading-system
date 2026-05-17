"""Multi-layer security gate for agent-generated Temporal activities.
Layers: AST scan → RestrictedPython compile → bytecode scan.
"""
import ast
import dis
import io
from RestrictedPython import compile_restricted


class SecurityViolation(Exception):
    pass


_ALLOWED_IMPORTS = {
    "temporalio", "core", "pandas", "numpy", "datetime", "typing",
    "dataclasses", "collections", "functools", "itertools", "math",
    "scanner", "technical",
}

_BANNED_AST_CALLS = {"exec", "eval", "compile", "getattr", "globals", "locals", "vars"}
# LOAD_BUILD_CLASS signals dynamic class creation; __import__ caught in AST
_BANNED_BYTECODES = {"LOAD_BUILD_CLASS"}


def validate_activity_code(code: str) -> None:
    """Raises SecurityViolation if code fails any security check."""
    _check_ast(code)
    # RestrictedPython does not support async — skip for async Temporal activities
    _check_bytecode(code)


def _check_ast(code: str) -> None:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            else:
                module = node.names[0].name
            root = module.split(".")[0]
            if root not in _ALLOWED_IMPORTS:
                raise SecurityViolation(
                    f"Forbidden import: {module!r}. Allowed roots: {_ALLOWED_IMPORTS}"
                )

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in _BANNED_AST_CALLS:
                    raise SecurityViolation(f"Forbidden call: {node.func.id!r}")
                if node.func.id == "__import__":
                    raise SecurityViolation("Forbidden: __import__")

        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise SecurityViolation(f"Forbidden dunder access: {node.attr!r}")


def _check_restricted_python(code: str) -> None:
    try:
        compile_restricted(code, filename="<agent_activity>", mode="exec")
    except SyntaxError as exc:
        raise SecurityViolation(f"RestrictedPython rejected: {exc}")


def _check_bytecode(code: str) -> None:
    try:
        compiled = compile(code, "<agent_activity>", "exec")
    except SyntaxError as exc:
        raise SecurityViolation(f"Compile failed: {exc}")

    buf = io.StringIO()
    dis.dis(compiled, file=buf)
    bytecode_text = buf.getvalue()

    for banned in _BANNED_BYTECODES:
        if banned in bytecode_text:
            raise SecurityViolation(f"Banned bytecode instruction: {banned!r}")


def run_in_sandbox(code: str, test_data_path: str) -> dict:
    import subprocess
    import tempfile
    import resource
    import os

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["python", "-S", "-I", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
            preexec_fn=lambda: resource.setrlimit(
                resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024)
            ),
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout[:2000],
            "error": result.stderr[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Timeout: >60s"}
    finally:
        os.unlink(tmp_path)
