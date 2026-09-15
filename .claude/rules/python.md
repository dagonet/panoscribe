---
paths:
  - "**/*.py"
  - "pyproject.toml"
  - "requirements*.txt"
  - ".editorconfig"
---

# Code Style (MANDATORY)

This repository uses `ruff` as the authoritative formatter and linter. The `.editorconfig` at the repository root provides supplementary whitespace and indent rules.

All Python code MUST:
- pass `ruff format` and `ruff check` without changes
- use `snake_case` for functions, methods, and variables
- use `UpperCamelCase` for classes
- use `UPPER_SNAKE_CASE` for constants
- use type hints for all function signatures
- use absolute imports (avoid relative imports unless within a package)

Claude agents MUST NOT:
- reformat code that already complies
- introduce alternative styles
- override `.editorconfig` or ruff preferences

If generated code would violate the project formatter,
the code MUST be rewritten until it complies.

## Enforcement Notes

- `.editorconfig` is committed and authoritative for whitespace
- `ruff` is authoritative for Python style and linting
- Formatting consistency is more important than brevity
- Run `uv run ruff format .` and `uv run ruff check .` before every commit

# Python Project Conventions

- Always verify `import` statements are present after merges or multi-file edits
- Use type hints for all function signatures and return types
- Use `pathlib.Path` over `os.path` for file system operations
- Use the `logging` module — never `print()` for diagnostics
- Use context managers (`with` statements) for resource management
- Check `pyproject.toml` / `requirements.txt` for new dependencies before adding
- After branch merges, verify no `import` statements were dropped
- Run `uv run ruff format .` + `uv run ruff check .` before every commit

# Agent Routing and Build/Test Notes (moved from CLAUDE.md)

**Agent fallback:** The `python-coder` agent uses Bash pip/poetry/uv + pytest (no Python-specific MCP tools exist yet). Do NOT substitute `coder` for `python-coder` — it carries Python-specific knowledge beyond build tool usage.

**Build & Test:** use the project's pip/poetry/uv build+test commands (see `PROJECT_CONTEXT.md`); for slow suites, target first (`pytest path/to/test_file.py::TestClass::test_method -x`) then run the full suite.

**Debugging:** trace read and write paths through Route/View → Service → Repository/ORM → Database — a common miss is fixing one direction but not the other.
