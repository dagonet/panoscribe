#!/usr/bin/env bash
# now-brief.sh -- SessionStart (matcher "compact"): re-show PROJECT_STATE.md's
# "## Now" section after a compaction, so the current goal survives it
# (v4.5.0 Part E). SessionStart stdout reaches the model; PreCompact and
# PostCompact stdout go to the debug log only (hooks reference, fetched
# 2026-10-03) -- which is why the old PreCompact `cat docs/plans/*.md` never
# reached anyone.
# ADVISORY: every path exits 0, output is capped at 1,024 B, and no JSON parser
# is needed -- the `source` guard is a grep, and an unreadable stdin leaves the
# decision to the registration's matcher. Not mirrored to user level: a bare
# ~/.claude install has no PROJECT_STATE.md to read.
IN=$(cat 2>/dev/null)
if printf '%s' "$IN" | grep -q '"source"'; then
  printf '%s' "$IN" | grep -qE '"source"[[:space:]]*:[[:space:]]*"compact"' || exit 0
fi
f="${CLAUDE_PROJECT_DIR:-.}/PROJECT_STATE.md"
[ -f "$f" ] || exit 0
# The section: from "## Now" to the next heading; HTML comment lines dropped,
# blank lines trimmed at both ends.
body=$(tr -d '\r' < "$f" | awk '
  /^## Now[[:space:]]*$/ { on = 1; next }
  !on { next }
  /^#/ { exit }
  c { if (index($0, "-->")) c = 0; next }
  /^[[:space:]]*<!--/ { if (!index($0, "-->")) c = 1; next }
  { line[++n] = $0 }
  END {
    s = 1; while (s <= n && line[s] ~ /^[[:space:]]*$/) s++
    e = n; while (e >= s && line[e] ~ /^[[:space:]]*$/) e--
    for (i = s; i <= e; i++) print line[i]
  }')
if [ -z "$body" ]; then
  echo 'now-brief: PROJECT_STATE.md has no "## Now" section -- add Goal / Current step / Next step so the goal survives compaction (AGENT_TEAM.md, Roles).'
  exit 0
fi
# The file's age is the defence against re-showing a stale goal.
m=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
age=""
case "$m" in
  ''|*[!0-9]*) ;;
  *) age=" (file changed $(( ($(date +%s) - m) / 3600 )) h ago)" ;;
esac
out=$(printf '=== Re-shown after compaction: PROJECT_STATE.md ## Now%s ===\n%s' "$age" "$body")
if [ "$(printf '%s\n' "$out" | wc -c)" -gt 1024 ]; then
  mark='… (truncated at 1 KB; read PROJECT_STATE.md)'
  keep=$((1024 - $(printf '%s\n' "$mark" | wc -c)))
  out=$(printf '%s\n' "$out" | LC_ALL=C awk -v k="$keep" '{ n += length($0) + 1; if (n > k) exit; print }')
  out=$(printf '%s\n%s' "$out" "$mark")
fi
printf '%s\n' "$out"
exit 0
