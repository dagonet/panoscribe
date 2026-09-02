#!/usr/bin/env bash
# PreToolUse hook: require '## Required Skills' block in spawn prompts for
# bound subagent_types.
#
# Matcher: Task
#
# Enforces the AGENT_TEAM.md Spawn-Prompt Binding Table. When the PO spawns
# a Task whose subagent_type is in the binding table, the prompt body MUST
# contain a literal '## Required Skills' line. Subagent types not in the
# table pass through. The 'code-reviewer' and 'doc-generator' types have
# no required skills and also pass through.
#
# DRIFT WARNING: the case statement below duplicates the binding table in
# templates/general/AGENT_TEAM.md §Superpowers Skills Integration. The
# scripts/verify-template-consistency.sh script diffs the two and fails
# CI if they diverge — keep them in sync.
#
# Reference: docs/plans/2026-04-12-wire-superpowers-skills.md (Chunk B,
# §Architecture). Reads its payload through hooks/lib/json.sh, the shared
# node/python3/jq reader the git gates use.

TOOL_INPUT=$(cat)

# v2.2.0: fields are read through hooks/lib/json.sh (node, python3 or jq).
# Fail-open with one WARN when none of the three is on PATH.
jlib="$(dirname "$0")/lib/json.sh"
[ -f "$jlib" ] || {
  echo "WARN: require-skills-block: hooks/lib/json.sh missing — enforcement inactive" >&2
  exit 0
}
. "$jlib"
json_have || { json_warn_no_parser require-skills-block "$(json_session "$TOOL_INPUT")"; exit 0; }

SUBAGENT_TYPE=$(json_get "$TOOL_INPUT" subagent_type)
PROMPT=$(json_get "$TOOL_INPUT" prompt)

case "$SUBAGENT_TYPE" in
  # Any language coder, including ones a project adds itself (cpp-coder, …).
  # An enumeration the template owns silently unbinds project coders on sync.
  coder|*-coder)
    REQUIRED="karpathy-guidelines superpowers:test-driven-development superpowers:verification-before-completion superpowers:receiving-code-review"
    ;;
  tester)
    REQUIRED="superpowers:systematic-debugging superpowers:verification-before-completion"
    ;;
  test-writer)
    REQUIRED="superpowers:test-driven-development"
    ;;
  architect)
    REQUIRED="superpowers:writing-plans"
    ;;
  requirements-engineer)
    REQUIRED="superpowers:brainstorming"
    ;;
  # DELIBERATELY EXEMPT — v2.4.0 (item A5) MADE THIS SET EXPLICIT, and the
  # names are the whole point of the change. Until now `ops` and `Explore`
  # reached the `*)` arm below, which is BYTE-IDENTICAL IN EFFECT to this one:
  # an agent exempted on purpose and an agent whose name silently fell out of
  # the enumeration produced the same `exit 0`, with no signal at runtime or
  # afterwards that distinguished them. A consumer could not tell whether their
  # own `game-tester` was unbound deliberately or by accident.
  #
  # THE OBVIOUS FIX — make `*)` warn — IS UNAVAILABLE, and this programme has
  # already paid for the lesson: a hook that exits 0 has no reliable channel to
  # the transcript, and hook stderr was measured not to reach the lead. A
  # warning nobody receives is the same silence with more code, and it reads as
  # fixed. So the intent is written down HERE, as arm labels, and
  # scripts/verify-template-consistency.sh check 29 asserts statically — in the
  # gate, where output demonstrably reaches someone — that every SHIPPED agent
  # name matches a binding arm or appears on this list. Deleting or renaming an
  # agent without updating this file is red before the release ships.
  #
  # ADDING A NAME HERE IS A DECISION, NOT A TIDY-UP: it says this agent needs
  # no skills block. Do not add a name here to silence check 29 — the check
  # exists to make that decision visible.
  ops|Explore|code-reviewer|doc-generator)
    exit 0
    ;;
  # The genuinely UNKNOWN type: a project's own agent (a consumer's
  # `game-tester`, a `cpp-coder` they added). It must pass — a template
  # enumeration has no business blocking an agent it never shipped, and check
  # 29 is scoped to the toolkit's own agent set for exactly that reason. A gate
  # that goes red on a consumer's own file is the cries-wolf failure this
  # release exists to reduce.
  *)
    exit 0
    ;;
esac

if printf '%s\n' "$PROMPT" | grep -qE '^## Required Skills$'; then
  exit 0
fi

{
  echo "BLOCKED: Task spawn for subagent_type '$SUBAGENT_TYPE' is missing a '## Required Skills' block in the prompt body."
  echo
  echo "Per AGENT_TEAM.md Spawn-Prompt Binding Table, this subagent_type must invoke:"
  for skill in $REQUIRED; do
    echo "  - $skill"
  done
  echo
  echo "Add this block to the prompt body before spawning:"
  echo
  echo "## Required Skills"
  echo "Invoke these via the Skill tool before beginning task work:"
  for skill in $REQUIRED; do
    echo "- $skill"
  done
} >&2
exit 2
