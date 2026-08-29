#!/usr/bin/env bash
# hooks/lib/json.sh
#
# One JSON field reader for every enforcement hook.
#
# Why: until v2.2.0 the hooks parsed their stdin payload with `node -e`. Native
# Claude Code installs (and most WSL/Linux boxes that never installed a JS
# toolchain) have no `node`, so every `node -e` returned empty, every gate saw
# an empty command and exited 0 — the guards were silently inactive. Reported
# 2026-08-29 from a WSL dry run.
#
# Backends, in order: node, python3, jq. All three read the payload from STDIN
# (never argv, which has platform length caps) and print the value with no
# trailing newline.
#
# Source it from a hook:  . "$(dirname "$0")/lib/json.sh"

JSON_PARSER=""

# json_parser -- prints node | python3 | jq | none (memoised).
json_parser() {
  if [ -z "$JSON_PARSER" ]; then
    if   command -v node    >/dev/null 2>&1; then JSON_PARSER=node
    elif command -v python3 >/dev/null 2>&1; then JSON_PARSER=python3
    elif command -v jq      >/dev/null 2>&1; then JSON_PARSER=jq
    else                                          JSON_PARSER=none
    fi
  fi
  printf '%s' "$JSON_PARSER"
}

# json_have -- true when any backend is available.
json_have() { [ "$(json_parser)" != "none" ]; }

# A UTF-8 BOM. Claude Code does not emit one, but a payload that has been
# round-tripped through a Windows tool can carry it, and it makes every backend
# fail to parse — stripped once here rather than three times below.
JSON_BOM=$(printf '\357\273\277')

# json_get <json> <dotted.path> -- prints the scalar at that path, or "".
#
# Objects, arrays, null and missing keys all print "" — the hooks treat an
# unreadable field as absent, which is the same contract the old `node -e ||
# echo ''` calls had.
json_get() {
  case "$1" in "$JSON_BOM"*) set -- "${1#"$JSON_BOM"}" "$2" ;; esac
  case "$(json_parser)" in
    node)
      printf '%s' "$1" | node -e '
        var v; try { v = JSON.parse(require("fs").readFileSync(0, "utf8")); }
        catch (e) { process.exit(0); }
        var p = process.argv[1].split(".");
        for (var i = 0; i < p.length; i++) {
          if (v === null || typeof v !== "object") { v = undefined; break; }
          v = v[p[i]];
        }
        if (v === undefined || v === null || typeof v === "object") process.exit(0);
        process.stdout.write(String(v));
      ' "$2" 2>/dev/null
      ;;
    python3)
      # Bytes in, bytes out, UTF-8 both ways. `json.load(sys.stdin)` decodes in
      # the LOCALE encoding: on Windows Git Bash (ANSI code page) or under
      # LC_ALL=C an em dash in the payload raises UnicodeDecodeError, the field
      # comes back empty, and a gate that keys on it exits 0 silently. The
      # matching sys.stdout.write would raise UnicodeEncodeError on the way out.
      printf '%s' "$1" | python3 -c '
import json, sys
try:
    v = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", "replace"))
except Exception:
    sys.exit(0)
for k in sys.argv[1].split("."):
    if not isinstance(v, dict):
        v = None
        break
    v = v.get(k)
if v is None or isinstance(v, (dict, list)):
    sys.exit(0)
sys.stdout.buffer.write((v if isinstance(v, str) else json.dumps(v)).encode("utf-8"))
' "$2" 2>/dev/null
      ;;
    jq)
      printf '%s' "$1" | jq -j --arg p "$2" '
        getpath($p | split("."))
        | if . == null or type == "object" or type == "array" then ""
          elif type == "string" then .
          else tojson end
      ' 2>/dev/null
      ;;
    *) printf '' ;;
  esac
}

# json_session <json> -- the payload's session_id, by grep. Deliberately NOT
# json_get: the warn-once path has to work when there is no parser at all.
json_session() {
  printf '%s' "$1" | grep -o '"session_id":"[^"]*"' | head -1 | cut -d'"' -f4
}

# json_warn_once <hook-name> <session-id> <message> -- print <message> to stderr
# at most once per hook per session. PreToolUse hooks fire on EVERY tool call,
# so an unconditional warning is thousands of identical stderr lines; a marker
# with no session in it is the opposite failure — on a host-global TMPDIR the
# hook would warn once EVER and every later outage would be silent. With no
# session id to key on (a payload we could not even grep) the marker expires
# after an hour instead. Best-effort: an unwritable marker just means the
# warning repeats. Never changes an exit code.
#
# The session id lands in a FILENAME, so a value carrying a path separator or
# `..` is discarded rather than sanitised — an unusable key is exactly the
# no-session case, and the TTL path below is the right fallback for it.
JSON_WARN_TTL=3600
json_warn_once() {
  jws=$2
  case "$jws" in */*|*\\*|*..*) jws="" ;; esac
  jwm="${TMPDIR:-/tmp}/claude-hook-warn-$1${jws:+-$jws}"
  if [ -f "$jwm" ]; then
    [ -n "$jws" ] && return 0
    jwmt=$(stat -c %Y "$jwm" 2>/dev/null || stat -f %m "$jwm" 2>/dev/null || echo 0)
    [ $(( $(date +%s) - jwmt )) -lt "$JSON_WARN_TTL" ] && return 0
  fi
  : > "$jwm" 2>/dev/null || true
  echo "$3" >&2
}

# json_warn_no_parser <hook-name> [session-id] -- the ONE stderr line a fail-open
# hook prints when it cannot enforce anything. Never changes an exit code.
json_warn_no_parser() {
  json_warn_once "$1" "${2:-}" "WARN: $1: no JSON parser on PATH — enforcement inactive"
}

# json_require_node <hook-name> [session-id] -- for the fail-open hooks whose
# engine is an embedded node program (a JSONL transcript scan, a JSON rewrite)
# rather than a field read. Returns non-zero — and warns once per session — when
# node is missing, so the caller can `|| exit 0`.
json_require_node() {
  command -v node >/dev/null 2>&1 && return 0
  if json_have; then
    json_warn_once "$1" "${2:-}" "WARN: $1: node not on PATH (found $(json_parser)) — enforcement inactive"
  else
    json_warn_no_parser "$1" "${2:-}"
  fi
  return 1
}
