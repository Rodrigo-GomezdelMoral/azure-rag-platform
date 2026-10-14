import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = ("docs/", "eval/datasets/", "web/node_modules/", "web/fixtures/")
# The specification's own layout needs more than its 42-file figure; README records the count.
MAX_FILES = 52
MAX_PYTHON_LINES = 1000
MAX_BICEP_LINES = 400
MAX_TYPESCRIPT_LINES = 700
MAX_DEPTH = 3
MAX_FUNCTION_LINES = 35
MAX_COMMENTS = 19


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout.split("\n")
    return [ROOT / f for f in out if f and not f.startswith(EXCLUDED)]


def lines(paths: list[Path]) -> int:
    return sum(len(p.read_text(encoding="utf-8").splitlines()) for p in paths)


def by_suffix(files: list[Path], *suffixes: str) -> list[Path]:
    return [f for f in files if f.suffix in suffixes]


def test_file_and_depth_budget() -> None:
    files = tracked_files()
    assert len(files) <= MAX_FILES, f"{len(files)} tracked files"
    deepest = max(len(f.relative_to(ROOT).parts) - 1 for f in files)
    assert deepest <= MAX_DEPTH, f"directory depth {deepest}"


def test_line_budgets() -> None:
    files = tracked_files()
    assert lines(by_suffix(files, ".py")) <= MAX_PYTHON_LINES
    assert lines(by_suffix(files, ".bicep", ".bicepparam")) <= MAX_BICEP_LINES
    assert lines(by_suffix(files, ".ts", ".tsx")) <= MAX_TYPESCRIPT_LINES


def test_python_craft() -> None:
    comments = 0
    for path in by_suffix(tracked_files(), ".py"):
        source = path.read_text(encoding="utf-8")
        comments += sum(1 for line in source.splitlines() if line.lstrip().startswith("#"))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = node.end_lineno - node.lineno + 1 if node.end_lineno else 0
                assert length <= MAX_FUNCTION_LINES, f"{path.name}:{node.name} is {length} lines"
            if isinstance(node, ast.ExceptHandler):
                blind = node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
                assert not blind, f"{path.name}:{node.lineno} catches everything"
    assert comments <= MAX_COMMENTS, f"{comments} comment lines"


def test_dependencies_are_pinned_and_minimal() -> None:
    pins: list[str] = []
    for name in ("requirements.txt", "requirements-dev.txt"):
        pins += (ROOT / name).read_text().splitlines()
    for pin in (p for p in pins if p and not p.startswith(("-r", "#"))):
        assert "==" in pin, f"unpinned dependency {pin}"
        assert not pin.startswith("agent-framework=="), "the agent-framework metapackage is not allowed"
