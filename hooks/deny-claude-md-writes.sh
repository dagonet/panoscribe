#!/usr/bin/env bash
# deny-claude-md-writes.sh — PreToolUse hook: under a manifest v4 consumer,
# the repo-root CLAUDE.md is template-owned and the next sync overwrites it.
#
# Matcher: Edit|Write|MultiEdit|NotebookEdit
#
# v4.1 (spec docs/plans/2026-09-18-v4.1-design.md §6). Manifest v4 moves the
# project's own instructions out of CLAUDE.md's PROJECT-CUSTOM region and into
# `.claude/project-instructions.md` (a once-class file the sync server never
# overwrites). CLAUDE.md itself becomes template-owned: every sync replaces it
# wholesale. This hook is the mechanical half of that contract — a PO or agent
# who edits the root CLAUDE.md anyway loses the edit silently at the next
# sync, and this hook turns that into an immediate, explained refusal instead.
#
# DECISION RULE, AND ITS POLARITY (fail-CLOSED on cannot-determine):
#   tool_name not Edit/Write/MultiEdit/NotebookEdit  -> exit 0 (nothing to
#     read — the matcher already excludes other tools; this hook must never
#     deny on a call shape it cannot inspect)
#   path field absent/empty                          -> exit 0
#   normalised path != <root>/CLAUDE.md               -> exit 0 (a nested
#     CLAUDE.md, e.g. docs/CLAUDE.md, is not this hook's business)
#   no <root>/.claude/template-manifest.json          -> exit 0 (pre-v4
#     consumer, or the toolkit's own checkout — no manifest, no rule)
#   manifest present but its JSON does not parse      -> exit 2 (CANNOT
#     DETERMINE the version, so this hook refuses rather than guess allow —
#     the gate-design rule: a check that cannot answer must not clear the
#     call it cannot read)
#   manifest_version == 4                             -> exit 2 (DENY, the
#     message below)
#   manifest_version == 3, or anything else parseable -> exit 0 (allow —
#     manifest v3 has no `.claude/project-instructions.md` yet; the region in
#     CLAUDE.md is still the PO's legitimate surface)
#   no JSON parser on PATH / unparsable stdin          -> exit 2 (same
#     fail-closed posture as hooks/deny-secret-reads.sh: a call this hook
#     cannot inspect is not one it can clear)
#
# TWO HOOKS, ONE PATH (plan ruling R-L). hooks/enforce-delegation.sh keeps
# CLAUDE.md on the PO's main-thread write surface — under a v3 manifest that
# is still correct, the PROJECT-CUSTOM region lives there. Under a v4
# manifest the two project-level PreToolUse hooks disagree on the same path:
# enforce-delegation.sh's allow-side message still names CLAUDE.md; THIS hook
# denies. Both are registered; Claude Code runs every matching PreToolUse
# hook and a single "deny" wins over any "allow", so the deny always fires
# first in effect regardless of hook order. enforce-delegation.sh's comment,
# --help text and deny message were updated (R-L) to say CLAUDE.md is on the
# surface "pre-v4 manifests only", so its allow-side text stops teaching
# something false once a consumer migrates.
#
# SCOPE (spec §6, reviewer D5): this is a guardrail on the editing TOOLS, not
# a filesystem boundary. A Bash write (`sed -i CLAUDE.md`, `>> CLAUDE.md`, a
# heredoc) is not seen by this hook at all — deny-secret-reads.sh's Bash arm
# has a verb model for exactly this reason, and this hook does not reuse it,
# because unlike a secret a rewritten CLAUDE.md is not exfiltration; it is
# simply undone by the next sync. Never described as "CLAUDE.md cannot be
# written" — only that the editing tools refuse it and say where to write
# instead.
#
# REGISTRATION SCOPE: project-level only. Registered in every template's
# `.claude/settings.json`; NOT mirrored into `user-level-reference/hooks/`
# and NEVER registered in `~/.claude/settings.json` (HOOKS_NO_MIRROR in
# scripts/verify-template-consistency.sh carries the reason) — a user-level
# copy would refuse CLAUDE.md writes in every non-consumer repo on the
# machine, including this toolkit's own checkout and every project that has
# never run `/sync-template` at all.
#
# PATH NORMALISATION. hooks/lib/git-cmd.sh has no public repo-root helper (its
# gccc_norm is an internal two-letter-prefixed helper local to the -C
# resolver, and it only maps backslash -> forward slash — no drive-letter
# case fold), so this hook resolves the root directly with `git -C`, the same
# call hooks/enforce-delegation.sh already makes at its own line 292, and
# normalises both sides itself: backslash -> forward slash, then the DRIVE
# LETTER (only) lower-cased. The rest of the path stays case-as-given —
# Windows paths are case-insensitive as a filesystem, but this hook does not
# need to fold more than the one place a real payload and a `git
# rev-parse --show-toplevel` result are known to disagree in casing.

lib="$(dirname "$0")/lib/json.sh"
[ -f "$lib" ] || { echo "BLOCKED: $lib missing — run /sync-template step 6b (hooks/lib/json.sh)" >&2; exit 2; }
# shellcheck source=lib/json.sh
. "$lib"

DCM_JSON=$(cat)

json_have || {
  echo "BLOCKED: deny-claude-md-writes: no JSON parser (node, python3 or jq) on PATH — this hook cannot inspect the call, and a call it cannot inspect is not one it can clear. Install one of the three." >&2
  exit 2
}
json_valid "$DCM_JSON" || {
  echo "BLOCKED: deny-claude-md-writes: hook payload did not parse — this hook cannot inspect the call. Report the payload; do not work around it." >&2
  exit 2
}

DCM_TOOL=$(json_get "$DCM_JSON" tool_name)

case "$DCM_TOOL" in
  Edit|Write|MultiEdit) DCM_FIELD=file_path ;;
  NotebookEdit)         DCM_FIELD=notebook_path ;;
  *) exit 0 ;;
esac

DCM_RAW=$(json_get "$DCM_JSON" "tool_input.$DCM_FIELD")
[ -n "$DCM_RAW" ] || exit 0

DCM_CWD=$(json_get "$DCM_JSON" cwd)
[ -n "$DCM_CWD" ] || DCM_CWD="."

# dcm_norm <path> -> backslashes to forward slashes, drive letter lower-cased.
dcm_norm() {
  dn=$(printf '%s' "$1" | tr '\\' '/')
  case "$dn" in
    [A-Za-z]:/*)
      dnl=$(printf '%s' "${dn%%:*}" | tr 'A-Z' 'a-z')
      dn="$dnl:${dn#*:}"
      ;;
  esac
  printf '%s' "$dn"
}

DCM_ROOT=$(git -C "$DCM_CWD" rev-parse --show-toplevel 2>/dev/null)
[ -n "$DCM_ROOT" ] || DCM_ROOT="$DCM_CWD"

DCM_NROOT=$(dcm_norm "$DCM_ROOT")
DCM_NROOT="${DCM_NROOT%/}"

DCM_NPATH=$(dcm_norm "$DCM_RAW")
case "$DCM_NPATH" in
  /*|[a-z]:/*) ;;                                # already absolute
  *) DCM_NPATH="$DCM_NROOT/$DCM_NPATH" ;;         # relative -> under the root
esac

[ "$DCM_NPATH" = "$DCM_NROOT/CLAUDE.md" ] || exit 0

DCM_MANIFEST="$DCM_NROOT/.claude/template-manifest.json"
[ -f "$DCM_MANIFEST" ] || exit 0

DCM_MCONTENT=$(cat "$DCM_MANIFEST" 2>/dev/null)
json_valid "$DCM_MCONTENT" || {
  echo "BLOCKED: deny-claude-md-writes: cannot determine manifest version: $DCM_MANIFEST" >&2
  exit 2
}

DCM_MVER=$(json_get "$DCM_MCONTENT" manifest_version)
[ "$DCM_MVER" = "4" ] || exit 0

echo "BLOCKED: deny-claude-md-writes: CLAUDE.md is template-owned under manifest v4 — write to .claude/project-instructions.md instead; the next sync overwrites CLAUDE.md" >&2
exit 2
