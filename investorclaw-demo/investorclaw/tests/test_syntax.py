"""
Syntax validation: ensure all Python source files parse without errors.
This is the minimum release gate — it catches broken imports or typos
that would prevent the skill from loading at all.
"""
import ast
import os
import glob


SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_GLOBS = [
    "*.py",
    "runtime/*.py",
    "commands/*.py",
    "internal/*.py",
    "rendering/*.py",
    "providers/*.py",
    "services/*.py",
    "workers/*.py",
    "config/*.py",
    "setup/*.py",
    "models/*.py",
]

EXCLUDE_DIRS = {"__pycache__", ".git"}


def collect_py_files():
    files = []
    for pattern in SOURCE_GLOBS:
        files.extend(glob.glob(os.path.join(SKILL_ROOT, pattern)))
    return sorted(set(files))


def test_all_python_files_parse():
    """Every .py file in the skill must parse without a SyntaxError."""
    py_files = collect_py_files()
    assert py_files, "No Python source files found — check SKILL_ROOT path"

    errors = []
    for filepath in py_files:
        rel = os.path.relpath(filepath, SKILL_ROOT)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            ast.parse(source, filename=filepath)
        except SyntaxError as exc:
            errors.append(f"{rel}: {exc}")
        except Exception as exc:
            errors.append(f"{rel}: unexpected error — {exc}")

    assert not errors, "Syntax errors found:\n" + "\n".join(errors)


def test_file_count_sanity():
    """Sanity check: skill must have at least 10 Python source files."""
    py_files = collect_py_files()
    assert len(py_files) >= 10, (
        f"Only {len(py_files)} Python files found — skill may be incomplete"
    )
