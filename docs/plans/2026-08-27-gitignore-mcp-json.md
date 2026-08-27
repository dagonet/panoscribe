# Gitignore the generated root `.mcp.json`

Tier: T1

`.mcp.json` appeared untracked in the repo root during the Docker MCP work. It is a
generated project-scope MCP config carrying machine-specific paths (sqlite DB path,
mcp-dev-servers venv), so it must not be committed. The claude-code-toolkit template
gitignores it in all six variants; this project was set up before that and never picked
it up.

Change: add `.mcp.json` to `.gitignore`, next to the existing `.claude/.mcp.json` entry
(the legacy path already listed there). One line, no code touched.
