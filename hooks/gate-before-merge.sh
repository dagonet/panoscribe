#!/usr/bin/env bash
# PreToolUse hook: block PR merge/auto-merge without a fresh gate artifact
# Matcher: Bash|PowerShell|mcp__MCP_DOCKER__merge_pull_request|mcp__github-tools__github_pr_auto_merge
#
# v2.0: `gh pr merge`, a `git merge` while on main/master, and a push that
# targets main/master (fast-forward merge by push) are gated too, because the
# native git/gh CLI is allowed again. The MCP branch is unchanged -- those are
# GitHub tools, not the retired git-tools server. Escape hatch:
# <cwd>/.claude/git-guard-off.
#
# v2.4.0 (A6): a merge initiated while the checkout is on a PROTECTED branch is
# refused outright, before the artifact is even read — on that topology the
# merge lands the other side's content, so no comparison against this
# checkout's HEAD can say anything about it. See the block above that check.
#
# ---------------------------------------------------------------------------
# v3.0.1 — WHAT IS AND IS NOT GATED ON A PROTECTED BRANCH. Read this before
# reaching for the kill switch; it is the contract, and it lives HERE because
# this file syncs to consumers while docs/verification.md does not.
#
#   git merge --abort / --continue / --quit   ALLOWED, always. They land nothing
#       new, and a conflicted merge on a protected branch is exactly the state
#       this gate exists to worry about — you must be able to get out of it.
#   git merge <anything else>                 GATED, unconditionally.
#       v3.0.2 DELETED the catch-up exemption that allowed
#       `git merge --ff-only <this branch's upstream>` when HEAD was already an
#       ancestor of it. It resolved the ref by NAME and trusted its VALUE, and
#       `git update-ref refs/remotes/origin/main <sha>` is ungated — measured
#       landing never-gated content on a protected branch while every
#       configuration read came back honest. Proving the ref FRESH does not
#       work either: a reflog message is forgeable with `update-ref -m`, and a
#       fresh clone has no `.git/logs/refs/remotes/origin/main` at all, so a
#       freshness check fails closed on every new clone.
#       THE CATCH-UP ROUTE IS NOW `git pull --ff-only`, which is safe here
#       BECAUSE IT FETCHES FIRST: the fetch overwrites a poisoned tracking ref
#       before the merge reads it (measured).
#   git pull --ff-only   (no remote, no refspec)   ALLOWED only when this
#       branch's own config names it: `branch.<cur>.remote` is set AND
#       `branch.<cur>.merge` is `refs/heads/<cur>`. v3.0.2: "targets the
#       configured upstream by construction" was false — `branch.<cur>.merge`
#       is re-pointable, re-pointing is ungated, and `git pull --ff-only` then
#       landed a whole foreign branch on a protected branch.
#   git pull --ff-only <remote> <branch>      ALLOWED when <branch> is this
#       branch's name and neither operand carries a ':'. Strictly more provably
#       safe than the refspec-free form — it NAMES what it lands — and gated
#       until v3.0.2 purely because the form looked refspec-bearing.
#   git pull <any other form>                 GATED, including a bare `git pull`
#       on a branch that would fast-forward cleanly. That is deliberate: the
#       remedy is one word, and it is the safer command.
#   gh pr merge / the GitHub merge tools      GATED from a protected branch.
#
#   AND: any of the gated forms above is also refused when an EARLIER clause of
#       the SAME command checks out (or switches to) a protected branch, or a
#       target this hook cannot resolve. `git checkout main && git merge
#       feature/x` used to slip through — this hook runs before the command, so
#       it read the branch you were still on. Order is what matters, not
#       chaining: `gh pr merge …; git checkout main; git pull --ff-only` is fine,
#       the gated clause runs first. `git checkout feature/z && git merge …` is
#       fine too, because the target is not protected. Run the checkout and the
#       operation as separate calls, or name the destination — `git push origin
#       <branch>` keys on its argument and never consults the current branch.
#
#   AND (v3.0.2): the same refusal when an earlier clause MOVES WHAT THE GATED
#       CLAUSE RESOLVES TO — `git branch -u`, `git config branch.*/remote.*`,
#       `git update-ref`, `git fetch` with a destination refspec, `git remote
#       set-url|remove|add` — or when the gated git invocation ITSELF carries
#       inline configuration (`-c`, `--config-env`, a `GIT_CONFIG_*` env
#       prefix). The last one needs no chaining at all: a single
#       `git -c remote.evil.url=… -c branch.main.remote=evil pull --ff-only`
#       was measured landing foreign content while `branch.main.merge` on disk
#       still read `refs/heads/main`.
#
# THE STATED LIMIT: every decision above is taken BEFORE any fetch, so the
# CONTENT of a remote ref is unknown to this hook — it can only read the form of
# the command and refs that already exist locally. That is why `pull` is gated
# by form rather than by content: a remote-tracking ref that is merely STALE
# answers "adds nothing" confidently and wrongly about an object that is not the
# one the pull will land.
# ---------------------------------------------------------------------------
#
# Requires .gate/last-pass.json (written by hooks/run-gate.sh) at the repo
# toplevel of the merging session's cwd — worktree-aware, since developer
# agents self-merge from their worktrees. Blocks (exit 2) unless:
#   - the artifact exists,
#   - its "sha" equals the current HEAD of that checkout OR its "tree" equals
#     that checkout's HEAD^{tree} — as of v2.1.5 "tree" is the WORKING tree at
#     gate time, so a commit of exactly what was gated (chained
#     `git add … && git commit`, or `git commit -a`) matches by tree even
#     though the artifact's sha is the parent commit's, and
#   - the artifact file is younger than 60 minutes (mtime).
#
# CONSEQUENCE, by construction, on a repo that commits straight to trunk: the
# artifact is STALE most of the time. Any commit moves HEAD and changes the
# tree — a docs-only commit included, because docs are tracked content — so both
# keys miss. That is correct. The artifact blesses one specific tree, that tree
# genuinely changed, and the gate cannot know which changes are harmless. The
# tree key was added in v2.1.5 to fix a different problem (the artifact's `sha`
# being the PARENT commit when an agent chains `git add … && git commit`), not
# to make an artifact outlive later commits. It costs nothing in practice: this
# gate only fires on merge-shaped commands, so staleness is invisible until an
# actual merge — at which point re-running the gate is exactly the requirement.
# Do NOT add a path-filtered or docs-excluding tree key to "fix" it: deciding
# which file changes are safe to skip is the judgement a gate must not make.
#
# No-op (exit 0) when PROJECT_CONTEXT.md has no Gate command or the field is
# still a {{...}} placeholder — same graceful degradation as pre-commit-test.sh.
#
# v2.2.0: "main/master" above means the protected set, which an optional
# PROJECT_CONTEXT.md line configures:
#
#   - **Protected branches**: develop release
#
# Default (field absent) is `main master`; `none` protects nothing — a
# `gh pr merge` is still gated, since that is a merge whatever the branch is.
# The payload is parsed through hooks/lib/json.sh (node, python3 or jq); with
# none of the three on PATH this gate fails CLOSED.

# Fail CLOSED when the sourced lib is missing: without it every gc_* helper is
# undefined, GC_TOOL stays empty, and this gate would exit 0 on every merge.
lib="$(dirname "$0")/lib/git-cmd.sh"
[ -f "$lib" ] || { echo "BLOCKED: $lib missing — run /sync-template step 6b (hooks/lib/git-cmd.sh)" >&2; exit 2; }
. "$lib"

gc_read_stdin
gc_guard_off && exit 0

CWD="$GC_CWD"

# What the block message reports about. Defaults describe the MCP merge tools,
# which carry no command string at all; the Bash branch overrides them.
A6_KIND=mcp
A6_SEG=""
A6_ARGS=""
A6_MOVE_SEG=""
A6_MOVE_TARGET=""
A6_MUT_SEG=""
moved=0
mutated=0

# --- v3.0.1 (A6 fix) argument parsing, deliberately LOCAL to this hook -------
#
# Not added to hooks/lib/git-cmd.sh: that library is covered by the three-parser
# matrix (~90 minutes), nothing else needs these shapes, and keeping them here
# means the A6 fix costs one suite run rather than three.

# a6_args <segment> <subcommand> -- everything after `<subcommand>` in a segment.
a6_args() {
  printf '%s\n' "$1" | sed -n "s/.*[[:space:]]$2\\([[:space:]]\\|\$\\)/\\1/p" | head -1
}

# a6_strip_redir <args> -- <args> with shell REDIRECTION tokens removed.
#
# v3.0.2 (measured minutes after v3.0.1 shipped): `git pull --ff-only 2>&1` was
# BLOCKED, reporting `refspec/remote named: present (2>&1 )`. `2>&1` starts with
# a digit, so the non-flag filter below counted it as an operand — an ordinary
# scripted form refused by a guard, which is how a layer gets switched off.
#
# THE STRIP MUST NOT BE GREEDY, and that is the whole difficulty. Dropping
# everything after a `>`, or every token that merely CONTAINS one, would turn
# `git pull origin feature/x 2>&1` into a refspec-free pull and hand it the
# safe-form exemption — reopening the hole A6 just closed. So it drops only
# tokens that are THEMSELVES a redirection operator:
#   - operator with its target attached (`2>&1`, `>file`, `>>file`, `<file`,
#     `&>file`): the one token goes;
#   - bare operator (`>`, `>>`, `<`, `2>`, `&>`): the token AND the next one,
#     which is its target. Exactly one follower, never a run.
# A ref name can never match either pattern, because both require a `>` or `<`
# immediately after an optional fd number or `&`.
#
# The empty-token arm comes FIRST on purpose: `tr` emits an empty field for a
# double space, so `git pull >  /dev/null` yields `>`, ``, `/dev/null`. If the
# empty token consumed the skip, `/dev/null` would leak back in as an operand.
a6_strip_redir() {
  printf '%s\n' "$1" | tr ' \t' '\n\n' | awk '
    $0 == "" { next }
    skip == 1 { skip = 0; next }
    /^([0-9]*|&)(>>|>|<).+$/ { next }
    /^([0-9]*|&)(>>|>|<)$/ { skip = 1; next }
    { print }
  ' | tr '\n' ' '
}

# a6_nonflag <args> -- the tokens that are not flags (a target ref, a remote).
a6_nonflag() {
  a6_strip_redir "$1" | tr ' \t' '\n\n' | grep -E '^[^-][^[:space:]]*$'
}

# a6_nonflag_count <args>
a6_nonflag_count() {
  a6_nonflag "$1" | grep -c . || true
}

# a6_has_flag <args> <alternation> -- a long flag from the alternation is present.
a6_has_flag() {
  printf '%s\n' "$1" | grep -qE "(^|[[:space:]])--($2)([[:space:]]|=|\$)"
}

# a6_merge_exempt <merge-args> -- `git merge --abort|--continue|--quit`.
#
# HIGHEST-PRIORITY ARM OF THE v3.0.1 FIX, and it is checked before every other
# question. All three were measured exiting 2 on a protected branch, which left
# a consumer in a CONFLICTED MERGE ON `main` — precisely the state this gate
# exists to worry about — with no way out except `.claude/git-guard-off`. A
# guard whose only exit is its own kill switch teaches the kill switch.
# None of the three lands anything new: abort restores the pre-merge state,
# continue completes work already begun (and already gated when it began), quit
# leaves the index alone.
#
# The exemption requires NO non-flag token to be present. gc_segments strips
# quotes, so `git merge -m "retry after --abort" feature/x` otherwise hands us a
# bare `--abort` token and buys a real merge the exemption. The three real forms
# take no operand, so the requirement costs nothing and closes that door.
a6_merge_exempt() {
  [ "$(a6_nonflag_count "$1")" -eq 0 ] || return 1
  a6_has_flag "$1" 'abort|continue|quit'
}

# a6_upstream_facts <repo> -- populate A6_UP / A6_UPSHA / A6_HEADSHA for both
# the discriminator and the block message. Local reads only, no network.
# a6_branch_move <segment> -- a clause that can move HEAD to another branch.
#
# NOT added to hooks/lib/git-cmd.sh even though no-push-main.sh needs the same
# three lines: the lib is covered by the ~90-minute three-parser matrix, and
# this shape carries no JSON. The duplication is deliberate and small.
#
# `--` means "everything after this is a path", so `git checkout -- file` and
# `git checkout <ref> -- path` restore files without moving HEAD. Those must not
# arm the refusal, or a routine file restore would gate the merge that follows.
a6_branch_move() {
  gc_matches_subcommand "$1" "checkout" || gc_matches_subcommand "$1" "switch" || return 1
  printf '%s\n' "$1" | grep -qE '(^|[[:space:]])--([[:space:]]|$)' && return 1
  return 0
}

# a6_move_target <segment> -- the branch a checkout/switch names, or "".
#
# KEY ON THE TARGET, NOT ON THE PRESENCE OF A CHECKOUT. A branch change only
# matters when it moves the checkout ONTO a protected branch;
# `git checkout feature/z && git merge feature/y` lands nothing near one, and
# refusing it would be a false positive on ordinary work — which is how a layer
# gets switched off. The target is an ARGUMENT, in the payload, not ambient
# state the command can change, so it is the safe thing to key on: the same
# distinction that explains the bug, applied one level in.
a6_move_target() {
  a6mt=$(a6_args "$1" "checkout")
  [ -n "$a6mt" ] || a6mt=$(a6_args "$1" "switch")
  a6_nonflag "$a6mt" | head -1
}

# a6_move_verdict <repo> <segment> -- 1 = moves onto a protected branch,
# 2 = names a target this hook cannot resolve, 0 = moves somewhere harmless.
a6_move_verdict() {
  A6_MOVE_TARGET=$(a6_move_target "$2")
  case "$A6_MOVE_TARGET" in
    # No target at all (`git checkout` alone), `-` / `@{-1}` (the previous
    # branch), a variable, or anything that is not a plain ref name: genuinely
    # cannot be determined here, so refuse THOSE rather than every chain.
    ''|*[!A-Za-z0-9._/-]*) printf 0 >/dev/null; return 2 ;;
  esac
  for a6mp in $(gc_protected_branches "$1"); do
    [ "$A6_MOVE_TARGET" = "$a6mp" ] && return 1
  done
  return 0
}

a6_upstream_facts() {
  A6_UP=$(git -C "$1" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)
  A6_UPSHA=""
  [ -n "$A6_UP" ] && A6_UPSHA=$(git -C "$1" rev-parse --verify --quiet "$A6_UP^{commit}" 2>/dev/null)
  A6_HEADSHA=$(git -C "$1" rev-parse --verify --quiet HEAD 2>/dev/null)
}

# v3.0.2 — A6.2's catch-up exemption is GONE. It lived here, and it allowed
# `git merge --ff-only <this branch's configured upstream>` on a protected
# branch when HEAD was already an ancestor of that ref. Measured end-to-end:
#
#   git update-ref refs/remotes/origin/main <rogue sha>   verdict 0  UNGATED
#   git merge --ff-only origin/main                       verdict 0  ALLOWED
#     -> never-gated content landed on the protected branch, and every
#        configuration read (branch.main.merge, main@{upstream}) stayed honest.
#
# THE EXEMPTION RESOLVED A REF BY NAME AND TRUSTED ITS VALUE. A name is not a
# value. And proving the value FRESH is not available to this hook: a reflog
# entry is forgeable (`git update-ref -m 'fetch origin: fast-forward'`), the log
# is a file that can be removed, and a FRESH CLONE HAS NO
# `.git/logs/refs/remotes/origin/main` at all — so a freshness check would fail
# closed on every new clone. Do not reintroduce either shape.
#
# No capability is lost: `git pull --ff-only` catches a protected branch up and
# SELF-HEALS, because the pull fetches before it merges — measured restoring a
# poisoned `origin/main` before reading it. That is now what the DENY message
# recommends.

# a6_pull_catchup <repo> <pull-args> -- true for the two pull forms that are
# provably safe on a protected branch BEFORE any fetch. Sets A6_PULL_WHY for the
# block message.
#
# v3.0.2, finding 54. The form this replaced allowed any refspec-free
# `--ff-only` pull, on the stated grounds that it "targets the configured
# upstream by construction". It does not: `branch.<cur>.merge` is re-pointable,
# and re-pointing is ungated on both gates.
#
#   git branch -u origin/rogue main    verdict 0   (ungated)
#   git pull --ff-only                 verdict 0   -> HEAD MOVED, rogue landed
#
# So compare NAMES — a local config read, offline, sound before the fetch:
#
#   refspec-free `--ff-only`   allowed only when `branch.<cur>.remote` is
#       non-empty AND `branch.<cur>.merge` is exactly `refs/heads/<cur>`.
#       Missing or mismatched is cannot-determine, so it gates.
#   `--ff-only <remote> <branch>`   allowed when there are exactly two operands,
#       neither carries a ':', and <branch> is the current branch. This form was
#       GATED until v3.0.2 and is strictly more provably safe than the one that
#       was allowed — it NAMES what it lands. A consumer reported the false
#       positive; the report's harmless half turned out to be the sound form.
#
# Operands are counted through a6_nonflag, which strips redirections first, so
# `git pull --ff-only origin main 2>&1` still reads as two operands and not
# three. That is the row where this rule and the v3.0.2 redirect strip meet.
#
# `config --get` is used, not `--get-all`: a multi-valued key makes it exit
# non-zero with no value, which lands in the mismatch arm and gates. That is the
# right answer — a branch with two merge refs is not one this can prove.
a6_pull_catchup() {
  a6pc_repo=$1; a6pc_args=$2
  A6_PULL_WHY=""
  a6_has_flag "$a6pc_args" 'ff-only' || { A6_PULL_WHY="no --ff-only"; return 1; }
  a6pc_cur=$(gc_current_branch "$a6pc_repo")
  [ -n "$a6pc_cur" ] || { A6_PULL_WHY="current branch unreadable"; return 1; }
  a6pc_n=$(a6_nonflag_count "$a6pc_args")
  case "$a6pc_n" in
    0)
      a6pc_rem=$(git -C "$a6pc_repo" config --get "branch.$a6pc_cur.remote" 2>/dev/null)
      a6pc_mrg=$(git -C "$a6pc_repo" config --get "branch.$a6pc_cur.merge" 2>/dev/null)
      A6_PULL_WHY="branch.$a6pc_cur.remote=${a6pc_rem:-<unset>} branch.$a6pc_cur.merge=${a6pc_mrg:-<unset>} (want refs/heads/$a6pc_cur)"
      [ -n "$a6pc_rem" ] || return 1
      [ "$a6pc_mrg" = "refs/heads/$a6pc_cur" ] || return 1
      return 0
      ;;
    2)
      a6pc_dst=$(a6_nonflag "$a6pc_args" | sed -n 2p)
      A6_PULL_WHY="operands: $(a6_nonflag "$a6pc_args" | tr '\n' ' ')(want <remote> $a6pc_cur, no ':')"
      printf '%s\n' "$(a6_nonflag "$a6pc_args")" | grep -q ':' && return 1
      [ "$a6pc_dst" = "$a6pc_cur" ] || return 1
      return 0
      ;;
    *)
      A6_PULL_WHY="$a6pc_n operand(s): $(a6_nonflag "$a6pc_args" | tr '\n' ' ')(want 0, or <remote> $a6pc_cur)"
      return 1
      ;;
  esac
}

# a6_mutates_resolution <segment> -- an EARLIER clause that moves what a later
# gated clause resolves to.
#
# KNOWN-INCOMPLETE BLOCKLIST, deliberately, and the incompleteness is the point
# of writing it down. Four resolution inputs (`branch.*.remote`,
# `branch.*.merge`, `remote.*.url`, `remote.*.fetch`) times at least four
# mutation channels (a git verb, a direct ref write, a `.git/config` file edit,
# env injection) — and WORSE, the same channel behaves differently per key:
# `-c branch.main.merge=…` fails because that key is MULTI-VALUED so `-c` adds
# rather than replaces, while `-c branch.main.remote=…` replaces cleanly and
# lands foreign content. The cell matters, not the row or the column, so no
# enumeration of keys and channels is sufficient.
#
# The sound shape is the INVERSE — allow a multi-clause call only when every
# preceding clause is on a small proven-inert allowlist (`cd`, `echo`, `printf`,
# `ls`). It is deliberately NOT in this release: it would gate
# `git checkout feature/z && git merge feature/y`, which v3.0.1 shipped on
# purpose and a consumer measured working. Queued, not snuck in.
a6_mutates_resolution() {
  a6mr=$1
  # `git branch -u` / `--set-upstream-to` (a6_has_flag is long-flags-only).
  if gc_matches_subcommand "$a6mr" "branch"; then
    printf '%s\n' "$a6mr" | grep -qE '(^|[[:space:]])(-u|--set-upstream-to)([[:space:]]|=|$)' && return 0
  fi
  # `git config <anything> branch.* | remote.*` — any subcommand form, any scope.
  if gc_matches_subcommand "$a6mr" "config"; then
    printf '%s\n' "$a6mr" | grep -qE '(^|[[:space:]])(branch|remote)\.' && return 0
  fi
  gc_matches_subcommand "$a6mr" "update-ref" && return 0
  # `git fetch` with an explicit DESTINATION refspec (an operand carrying ':').
  if gc_matches_subcommand "$a6mr" "fetch"; then
    a6_nonflag "$(a6_args "$a6mr" "fetch")" | grep -q ':' && return 0
  fi
  if gc_matches_subcommand "$a6mr" "remote"; then
    printf '%s\n' "$a6mr" | grep -qE '(^|[[:space:]])(set-url|remove|rm|add)([[:space:]]|$)' && return 0
  fi
  return 1
}

# a6_inline_config <segment> <subcommand> -- the gated invocation ITSELF carries
# configuration, so no preceding clause is needed to re-point it.
#
# BROAD BY DESIGN: any `-c` or `--config-env` before the subcommand, and any
# `GIT_CONFIG_*` env prefix on the clause — not an enumeration of keys, because
# a new key cannot then silently join the list. Measured, ONE clause:
#
#   git -c remote.evil.url=<other> -c remote.evil.fetch=+refs/heads/*:… \
#       -c branch.main.remote=evil pull --ff-only
#     -> rc=0, fast-forward, foreign content on main, while
#        branch.main.merge on disk still read refs/heads/main
#
# The name comparison in a6_pull_catchup PASSES there — the merge ref is
# honest — and the content came from another remote entirely.
#
# THE HONEST COST: a benign `git -c core.pager=cat merge …` on a protected
# branch is now refused. That is the correct direction for a fail-closed gate,
# and the DENY message says to re-run without the `-c`.
#
# The `-c` search is restricted to the text BETWEEN `git` and the subcommand:
# gc_segments strips quotes, so a segment-wide grep would fire on
# `git merge -m "note -c x" feature/x` and refuse a message body.
# a6_is_git_sub <segment> <subcommand> -- gc_matches_subcommand, widened for the
# option forms the lib's GC_GIT_PRE does not know about.
#
# MEASURED while writing the fixtures for a6_inline_config:
# `git --config-env=branch.main.remote=X pull --ff-only` on a protected branch
# returned 0 — not because the inline-config rule missed it, but because the
# clause never matched as a `pull` AT ALL. GC_GIT_PRE allows `-C <path>` and
# `-c <k>=<v>` between `git` and the subcommand and nothing else, so the whole
# pull arm was skipped and the command fell through ungated. The counting bug is
# in hooks/lib/git-cmd.sh; compensating at the call site keeps that lib — and
# its ~90-minute three-parser matrix — out of this release, exactly as the
# v3.0.2 redirect strip does for gc_has_refspec.
a6_is_git_sub() {
  gc_matches_subcommand "$1" "$2" && return 0
  printf '%s\n' "$1" | grep -qE "\\bgit\\b([[:space:]]+--config-env=[^[:space:]]+|[[:space:]]+-c[[:space:]]+[^[:space:]]+|[[:space:]]+-C[[:space:]]+[^[:space:]]+)+[[:space:]]+$2([[:space:]]|\$)"
}

a6_inline_config() {
  printf '%s\n' "$1" | grep -qE '(^|[[:space:]])GIT_CONFIG_[A-Z_]+=' && return 0
  a6ic=$(printf '%s\n' "$1" | sed -n "s/.*[[:space:]]*git\\([^;]*\\)[[:space:]]$2\\([[:space:]]\\|\$\\).*/\\1/p" | head -1)
  printf '%s\n' "$a6ic" | grep -qE '(^|[[:space:]])(-c|--config-env)([[:space:]]|=)'
}

# v2.2.6 round 2 -- THE 14th FAIL-OPEN, third instance. Checked BEFORE the tool
# case below, because that case's `*)` arm is exactly the door an unreadable
# tool_name walks through. See gc_cmd_unreadable in hooks/lib/git-cmd.sh.
if gc_cmd_unreadable; then
  echo "BLOCKED: gate-before-merge: the payload carries a command this gate could not read, so it cannot rule out a merge -- refusing. Re-run the command. (If it repeats: create '.claude/git-guard-off' under this cwd, make the one fix, then delete it.)" >&2
  exit 2
fi

# Branch on the TOOL, never on the parsed string. This hook is registered on
# Bash|PowerShell, so if node is missing or the JSON does not parse, GC_CMD is
# empty -- and treating that as "not a Bash call" would fall through to the
# artifact check and block every Bash call in the session. A Bash payload with
# NO COMMAND KEY is a Bash payload with no merge in it; only the GitHub merge
# tools are gated unconditionally.
#
# v2.2.6 round 2 narrows what "we cannot read it" means here: a payload that
# HAS a `command` key we could not read no longer reaches this case at all --
# it was refused above. What still falls open below is the genuinely absent
# key and the genuinely unknown tool, which are not cannot-determine states.
case "$GC_TOOL" in
  Bash|PowerShell) ;;   # gate only merge-shaped commands (scanned below)
  mcp__*)          ;;   # the GitHub merge tools: always gated
  *) exit 0 ;;          # unknown tool, or a payload with no command key at all
esac

if [ "$GC_TOOL" = "Bash" ] || [ "$GC_TOOL" = "PowerShell" ]; then
  is_merge=0
  base="$CWD"
  segments=$(gc_segments)

  # v3.0.1 (consumer report) — THE PREMISE THIS GATE READS IS ONE THE COMMAND
  # CAN CHANGE. Every ambient check below resolves the branch with
  # `git branch --show-current`, and this is a PreToolUse hook: it runs BEFORE
  # the command. So `git checkout main && git merge feature/x` is evaluated
  # while the checkout is still on the feature branch, the protected-branch test
  # is false, and an entire unreviewed branch lands on `main` — using the exact
  # verb this gate watches.
  #
  # AND IT IS WORSE THAN A SKIPPED CHECK. The gate does not stand aside: it
  # falls through to the artifact comparison and runs it under the
  # feature-branch premise ("artifact.sha == branch tip == merged content"),
  # which that command invalidates. With a fresh artifact the comparison PASSES.
  # A skipped guard leaves no evidence; this one emits a POSITIVE RECEIPT for
  # something it did not check.
  #
  # ORDER IS THE DISCRIMINATOR, not co-presence. `gh pr merge …; git checkout
  # main; git pull --ff-only` is SAFE and is the flow the toolkit recommends:
  # the gated operation runs FIRST, on the branch this hook can see. Refusing
  # every chain that contains a checkout would gate the recommended workflow,
  # which is how guards get switched off. Only a branch change that PRECEDES a
  # gated operation matters, because only that changes where the operation
  # LANDS.
  #
  # And the guard must gate a merge that LANDS ON a protected branch, not one
  # merely INITIATED FROM a non-protected one: an agent merging its own PR from
  # its worktree is on a feature branch, which is the toolkit's own merge
  # protocol. Gating that would block every worktree-isolated merge, and would
  # read as "the fix works" rather than as the regression it is.
  #
  # Forms whose verdict does NOT depend on the branch — the three merge-state
  # subcommands, a refspec-free `--ff-only` pull, a push naming its destination
  # explicitly — stay allowed after a branch change, because for them the moved
  # premise is not load-bearing. Where a decision can key on the payload's
  # arguments it already does; this flag covers what is left.
  moved=0
  mutated=0

  while IFS= read -r seg; do
    [ -n "$seg" ] || continue

    # v3.0.2 — the same ordering rule, one premise further out. v3.0.1 keyed on
    # a preceding CHECKOUT because that moves the branch a gated clause lands
    # on; a preceding `git branch -u`, `git config branch.*`, `git update-ref`
    # or `git remote set-url` moves what a gated clause RESOLVES TO, which is
    # the same defect with a different mutable premise. Set here, read by the
    # merge/pull/push arms below. Never reset: a mutation cannot be undone by a
    # later clause the way a checkout can be.
    if a6_mutates_resolution "$seg"; then
      mutated=1
      A6_MUT_SEG=$seg
      continue
    fi

    cdt=$(gc_cd_target "$seg")
    if [ -n "$cdt" ]; then
      base=$(gc_resolve "$base" "$cdt")
      continue
    fi

    if a6_branch_move "$seg"; then
      # Last one wins: a later checkout back onto a feature branch means the
      # gated clause no longer lands on a protected branch.
      a6_move_verdict "$(gc_repo_for "$seg" "$base")" "$seg"
      moved=$?
      A6_MOVE_SEG=$seg
      continue
    fi

    # 1. gh pr merge (any flags)
    if printf '%s\n' "$seg" | grep -qE '\bgh[[:space:]]+pr[[:space:]]+merge\b'; then
      is_merge=1
      A6_KIND=ghpr
      [ "$moved" != 0 ] && A6_KIND=moved
      A6_SEG=$seg
      CWD=$(gc_repo_for "$seg" "$base")
      break
    fi

    # 2. git merge while the checkout is on a protected branch
    if a6_is_git_sub "$seg" "merge"; then
      repo=$(gc_repo_for "$seg" "$base")
      margs=$(a6_args "$seg" "merge")
      # v3.0.1 item 1: the three merge-state subcommands are exempt on the
      # SUBCOMMAND PARSE, before the branch is even looked at. See
      # a6_merge_exempt.
      if a6_merge_exempt "$margs"; then
        continue
      fi
      # A branch change earlier in the same command: the branch this merge lands
      # on is not the branch this hook can read. Cannot determine, so refuse.
      if [ "$moved" != 0 ]; then
        is_merge=1
        A6_KIND=moved
        A6_SEG=$seg
        A6_ARGS=$margs
        CWD="$repo"
        break
      fi
      if gc_on_main "$repo"; then
        # v3.0.2: NO exemption left here but the three merge-state subcommands
        # above. The catch-up exemption that used to sit on this line resolved a
        # ref by name and trusted its value; see the comment on a6_pull_catchup's
        # neighbour block. A merge on a protected branch is gated.
        is_merge=1
        A6_KIND=merge
        A6_TARGET=$(a6_nonflag "$margs" | head -1)
        A6_SEG=$seg
        A6_ARGS=$margs
        CWD="$repo"
        break
      fi
    fi

    # 2b. v3.0.1 item 3: `git pull` while the checkout is on a protected branch.
    #
    # NO DISCRIMINATOR HERE, and that is a measured decision rather than a
    # shortcut. A pull FETCHES FIRST, so anything this hook resolves before the
    # command runs is an answer about a different object:
    #   - a CURRENT remote-tracking ref answers correctly (measured rc=0)
    #   - an ABSENT one is at least distinguishable (rc=128)
    #   - a STALE one answers CONFIDENTLY AND WRONGLY: `--is-ancestor` returns 0
    #     for the stale tip, the check reads "adds nothing", and the pull then
    #     lands every commit gained since. Resolve-after-fetch is too late, and
    #     refuse-when-unresolvable never fires because the ref does resolve.
    #   - `ls-remote` is ~1.4 s per PreToolUse call and FAILS OFFLINE, which for
    #     a fail-closed gate means "no pull on a protected branch without a
    #     network".
    #
    # So: gate every pull except the one form that cannot land foreign content.
    # Refspec-free means the target is the configured upstream by construction,
    # and --ff-only means git itself refuses if it is not a fast-forward. Both
    # are readable BEFORE the fetch, which is the constraint that defeated
    # everything else.
    #
    # NAMED RESIDUAL FALSE POSITIVE: a bare `git pull` on a cleanly
    # fast-forwardable protected branch is gated. That is deliberate — the
    # remedy is "use git pull --ff-only", a one-word fix and the safer command,
    # not a multi-minute gate run. Gating only refspec-bearing pulls would leave
    # bare `git pull` with divergent local history creating a real merge commit
    # on the protected branch, which is the topology A6 exists for.
    if a6_is_git_sub "$seg" "pull"; then
      repo=$(gc_repo_for "$seg" "$base")
      pargs=$(a6_args "$seg" "pull")
      # THE PROTECTED-BRANCH DECISION COMES FIRST (v3.0.2). The name comparison
      # in a6_pull_catchup reads THIS repo's config for THIS branch, so it is
      # only meaningful when the branch this hook can read is the branch the
      # pull lands on — i.e. not after a checkout, and only when protected.
      # Applying it to the branch-independent exemption below would gate
      # `git checkout main && git pull --ff-only` from a worktree whose feature
      # branch has no upstream, which v3.0.1 shipped as allowed on purpose.
      # NAMED RESIDUAL: a checkout onto a protected branch whose upstream config
      # is poisoned is still allowed through that exemption. Queued, not fixed
      # here — closing it needs the inverse (allowlist) shape.
      if [ "$moved" = 0 ] && gc_on_main "$repo"; then
        if a6_inline_config "$seg" "pull"; then
          is_merge=1
          A6_KIND=config
        elif [ "$mutated" != 0 ]; then
          is_merge=1
          A6_KIND=mutated
        elif a6_pull_catchup "$repo" "$pargs"; then
          continue
        else
          is_merge=1
          A6_KIND=pull
        fi
        A6_SEG=$seg
        A6_ARGS=$pargs
        CWD="$repo"
        break
      fi
      # Not on a protected branch as this hook reads it. The refspec-free
      # --ff-only form is allowed on ANY branch, so a preceding branch change
      # does not change its verdict — it stays out of the refusal.
      if [ "$(a6_nonflag_count "$pargs")" -eq 0 ] && a6_has_flag "$pargs" 'ff-only' \
         && [ "$mutated" = 0 ] && ! a6_inline_config "$seg" "pull"; then
        continue
      fi
      if [ "$moved" != 0 ]; then
        is_merge=1
        A6_KIND=moved
        A6_SEG=$seg
        A6_ARGS=$pargs
        CWD="$repo"
        break
      fi
    fi

    # 3. a push that targets a protected branch -- fast-forward merge by push
    if a6_is_git_sub "$seg" "push"; then
      repo=$(gc_repo_for "$seg" "$base")
      # v3.0.2: the push half of the redirection defect is a FAIL-OPEN, not a
      # false positive. `git push origin 2>&1` on a protected branch gave
      # gc_has_refspec two non-flag tokens, so it read "destination named", the
      # current-branch check was skipped, and the push went through ungated.
      # The counting bug is inside gc_has_refspec in hooks/lib/git-cmd.sh;
      # compensating at the call site keeps that lib — and its ~90-minute
      # three-parser matrix — out of this fix.
      args=$(a6_strip_redir "$(gc_push_args "$seg")")
      # v3.0.2: a push FROM a protected branch whose remote was just re-pointed
      # (`git remote set-url`, `-c remote.origin.url=…`) sends this branch's
      # content somewhere this hook cannot see. Scoped to a protected branch on
      # purpose: gating every `git remote set-url && git push` on a feature
      # branch would be an over-correction on ordinary work.
      if gc_on_main "$repo" && { a6_inline_config "$seg" "push" || [ "$mutated" != 0 ]; }; then
        is_merge=1
        A6_KIND=config
        [ "$mutated" != 0 ] && ! a6_inline_config "$seg" "push" && A6_KIND=mutated
        A6_SEG=$seg
        A6_ARGS=$args
        CWD="$repo"
        break
      fi
      if gc_targets_main_ref "$args" "$repo"; then
        is_merge=1
        A6_KIND=push
        A6_SEG=$seg
        A6_ARGS=$args
        CWD="$repo"
        break
      fi
      # A push with no refspec follows the current branch, which a preceding
      # checkout has changed. A push that NAMES its destination is immune by
      # construction — it never consults ambient state — and is not refused.
      if ! gc_has_refspec "$args" && ! gc_push_skips_branch_check "$args" && [ "$moved" != 0 ]; then
        is_merge=1
        A6_KIND=moved
        A6_SEG=$seg
        A6_ARGS=$args
        CWD="$repo"
        break
      fi
      if ! gc_has_refspec "$args" && ! gc_push_skips_branch_check "$args" && gc_on_main "$repo"; then
        is_merge=1
        A6_KIND=push
        A6_SEG=$seg
        A6_ARGS=$args
        CWD="$repo"
        break
      fi
    fi
  done <<GC_SEGMENTS
$segments
GC_SEGMENTS

  [ "$is_merge" = "1" ] || exit 0
fi

REPO_TOP=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_TOP" ]; then
  # Not a git checkout (nothing to gate against) — allow.
  exit 0
fi

# Read Gate command from PROJECT_CONTEXT.md through GC_KEY_PRE (see the header
# note on that constant in hooks/lib/git-cmd.sh: a leading UTF-8 BOM otherwise
# hides a key that sits on line 1).
# Tolerates: leading "- " / "* " list
# markers, the "**Gate Command**:" label style (java/python variants), and
# surrounding backticks — several variants write commands as `cmd`.
GATE_CMD=$(grep -E "${GC_KEY_PRE}\*\*Gate( Command)?\*\*:" "$REPO_TOP/PROJECT_CONTEXT.md" 2>/dev/null | sed 's/.*\*\*Gate\( Command\)\?\*\*:[[:space:]]*//;s/[[:space:]]*$//;s/^`//;s/`$//' | head -1)

# No-op: no PROJECT_CONTEXT.md or no Gate command configured
if [ -z "$GATE_CMD" ]; then
  exit 0
fi

# No-op: placeholder not yet filled in
case "$GATE_CMD" in
  *\{\{*\}\}*) exit 0 ;;
esac

# v2.4.0 (A6, found live merging PR #75) -- THE ARTIFACT CHECK BELOW COMPARES
# THE ARTIFACT TO **HEAD**, AND HEAD IS THE MERGE CONTENT ONLY ON SOME
# TOPOLOGIES. A controller sitting on `main` merges the PR BRANCH's tip, not
# HEAD; so "re-run the gate on the current head" gates content that is already
# merged, writes a green artifact, and then permits a merge of entirely
# different content -- a correct guard whose own remediation manufactures the
# false receipt. A flow of branch -> commit -> gate -> push -> PR -> merge has
# the controller ON the branch, where `artifact.sha == branch tip == merged
# content` and the same check is sound. Same hook, opposite validity.
#
# The split is purely local -- no API, no network, and both helpers are already
# in this hook: if the merge is initiated while HEAD is on a PROTECTED branch,
# the thing being merged is BY CONSTRUCTION not HEAD, so the comparison below
# verifies nothing. Say so and refuse; on a feature branch, fall through to the
# comparison, which is meaningful there.
#
# DELIBERATELY NOT UNCONDITIONALLY FAIL-CLOSED. Target resolvability varies by
# path: `git merge <ref>` resolves locally, the MCP merge tools carry
# pullNumber/owner/repo (identified, but needing an API call), and a bare
# `gh pr merge` names no target at all. Refusing on every unresolvable path
# hard-blocks every PR merge for anyone offline -- the "unconditional
# fail-closed blocks everything" hazard from the GC_CMD round. The
# protected-branch detector is what makes cannot-determine-must-refuse
# affordable here: it refuses exactly the case where the evidence is known to
# be irrelevant, and stays out of the way otherwise.
# v3.0.1 (consumer report): a branch change PRECEDES the gated operation in this
# same command, so the branch it lands on is not the branch this hook can read.
# Refused before the artifact is compared — running that comparison under a
# premise the command invalidates is what produced a green receipt for an
# unchecked merge.
if [ "$A6_KIND" = "moved" ]; then
  {
    if [ "$moved" = 1 ]; then
      echo "BLOCKED: an earlier clause in this same command checks out a PROTECTED branch, so this operation lands on one."
    else
      echo "BLOCKED: gate-before-merge cannot determine which branch this operation lands on."
    fi
    echo "  branch now:      $(gc_current_branch "$CWD")  (as this hook sees it, BEFORE the command runs)"
    echo "  protected set:   $(gc_protected_branches "$CWD" 2>/dev/null || true)"
    echo "  branch change:   ${A6_MOVE_SEG}"
    echo "  change target:   ${A6_MOVE_TARGET:-<none named, or not a plain ref name>}$([ "$moved" = 1 ] && echo '  (protected)' || echo '  (unresolvable here)')"
    echo "  matched segment: ${A6_SEG}"
    echo "  discriminator:   the branch change comes FIRST, so every branch-derived input to this gate is the pre-change value. The change TARGET is read from the command instead, because that is an argument rather than state the command can move."
    echo "Could not determine: this hook runs before the command, and the command moves HEAD before the gated clause executes. Letting it through would not merely skip a check — the gate would compare its artifact against THIS checkout's HEAD and pass, emitting a green receipt for content it never examined."
    echo "ALLOWED without a gate run: run the two as SEPARATE calls — do the checkout, then issue the merge/pull/push on its own, where this gate can see the branch it lands on. A gated operation placed BEFORE the branch change is also fine ('gh pr merge …; git checkout main; git pull --ff-only'), and a push that NAMES its destination ('git push origin <branch>') never consults the current branch at all, so it is immune to this by construction."
    echo "(Last resort, and an admission of this guard's limits rather than a remedy: create '.claude/git-guard-off' under this cwd, make the one operation, then delete it.)"
  } >&2
  exit 2
fi

if gc_on_main "$CWD"; then
  # v3.0.1 item 5: DIAGNOSIS AND FIX, NOT ARGUMENT. The rationale for the
  # refusal lives in the comment block above, where the next editor will read
  # it; at block time nobody reads an argument. What a blocked consumer needs is
  # the configuration they are subject to, the segment that fired, the inputs
  # the decision used, the limit of what the hook can see, and — before the
  # escape hatch, never after it — the form that WOULD be allowed. Whichever of
  # those last two is read first is the one that gets used, and the toolkit has
  # plenty of hooks that name only the bypass.
  a6_upstream_facts "$CWD"
  A6_BRANCH=$(gc_current_branch "$CWD")
  A6_PROT=$(gc_protected_branches "$CWD")
  {
    echo "BLOCKED: gate-before-merge refuses this operation on a protected branch."
    echo "  branch:          $A6_BRANCH"
    echo "  protected set:   ${A6_PROT:-<empty>}  (set '- **Protected branches**:' in PROJECT_CONTEXT.md; 'none' protects nothing)"
    echo "  matched segment: ${A6_SEG:-<GitHub merge tool payload — no command string>}"
    echo "  upstream:        ${A6_UP:-<none configured for this branch>}${A6_UPSHA:+ ($A6_UPSHA)}"
    echo "  HEAD:            ${A6_HEADSHA:-<unresolvable>}"
    case "$A6_KIND" in
      merge)
        echo "  discriminator:   target ref: ${A6_TARGET:-<none named, or more than one>}"
        echo "                   --ff-only: $(a6_has_flag "$A6_ARGS" 'ff-only' && echo present || echo absent)   --no-ff/--squash: $(a6_has_flag "$A6_ARGS" 'no-ff|squash' && echo present || echo absent)"
        echo "                   verdict: a merge on a protected branch is gated unconditionally as of v3.0.2. The catch-up exemption was deleted: it resolved the target by NAME and trusted its VALUE, and 'git update-ref refs/remotes/origin/main <sha>' is ungated — measured landing never-gated content here with every config read honest."
        ;;
      pull)
        echo "  discriminator:   refspec/remote named: $([ "$(a6_nonflag_count "$A6_ARGS")" -eq 0 ] && echo absent || echo "present ($(a6_nonflag "$A6_ARGS" | tr '\n' ' '))")"
        echo "                   --ff-only: $(a6_has_flag "$A6_ARGS" 'ff-only' && echo present || echo absent)"
        echo "                   name comparison: ${A6_PULL_WHY:-<not reached>}"
        echo "                   verdict: not one of the two pull forms whose target can be proved by NAME before the fetch."
        ;;
      config)
        echo "  discriminator:   this git invocation carries inline configuration (-c, --config-env, or a GIT_CONFIG_* env prefix)."
        echo "                   verdict: inline config can re-point remote.*.url / branch.*.remote for this one command, so what it resolves to is not what the repository's configuration says. Measured landing foreign content on a protected branch in a SINGLE clause, while branch.<branch>.merge on disk stayed honest."
        ;;
      mutated)
        echo "  discriminator:   earlier clause: ${A6_MUT_SEG}"
        echo "                   verdict: that clause changes the configuration or refs THIS clause resolves through (upstream, remote URL, or a tracking ref), and this hook runs before any of it."
        ;;
      *)
        echo "  discriminator:   not applicable — this operation names no local ref that can be resolved before it runs."
        ;;
    esac
    echo "Could not determine: this check runs before any fetch, so the CONTENT of a remote target ref — what a fetch would bring in — is unknown to it. It decides on the FORM of the command and on refs that already exist locally. If your case is one only the content would settle, the hook cannot see it."
    case "$A6_KIND" in
      merge)
        echo "ALLOWED without a gate run: to CATCH THIS BRANCH UP to its upstream (${A6_UP:-none configured}), use 'git pull --ff-only' — not 'git merge --ff-only origin/main'. The pull FETCHES FIRST, so it re-reads the tracking ref from the remote instead of trusting whatever is in .git/refs; that is the whole difference, and it is why the merge form is no longer exempt. Also always allowed: 'git merge --abort', '--continue', '--quit'."
        echo "Otherwise: gate the content that is actually being merged — check out the merge target (the PR branch head), run 'bash hooks/run-gate.sh' there, and merge from that checkout."
        ;;
      pull)
        echo "ALLOWED without a gate run: 'git pull --ff-only' with no remote and no refspec, when this branch's own config names itself (branch.$A6_BRANCH.remote set, branch.$A6_BRANCH.merge = refs/heads/$A6_BRANCH); or 'git pull --ff-only <remote> $A6_BRANCH', which names the same thing explicitly. Either way git itself refuses if the result would not be a fast-forward."
        ;;
      config)
        echo "ALLOWED without a gate run: re-run this command WITHOUT the '-c' / '--config-env' option (and with no GIT_CONFIG_* variable set on it). If the setting is one you genuinely need, put it in the repository's configuration in a separate call, where it is visible to a reader, and then run the operation."
        ;;
      mutated)
        echo "ALLOWED without a gate run: run the two as SEPARATE calls — make the configuration or ref change first, then issue the pull/merge/push on its own, where this gate reads the configuration the operation will actually use."
        ;;
      *)
        echo "ALLOWED without a gate run: nothing on this path — a merge run from a protected branch lands the OTHER side's content, not this checkout's HEAD, so comparing the gate artifact to HEAD verifies nothing and re-gating here would only bless content that is already merged."
        echo "Do this instead: check out the merge target (the PR branch head), run 'bash hooks/run-gate.sh' there, and merge from that checkout — or gate on the branch before opening the PR."
        ;;
    esac
    echo "(Last resort, and an admission of this guard's limits rather than a remedy: create '.claude/git-guard-off' under this cwd, make the one operation, then delete it.)"
  } >&2
  exit 2
fi

ARTIFACT="$REPO_TOP/.gate/last-pass.json"

if [ ! -f "$ARTIFACT" ]; then
  echo "BLOCKED: No gate artifact found. Run 'bash hooks/run-gate.sh' on the PR branch head (green gate writes .gate/last-pass.json), then merge." >&2
  exit 2
fi

# v2.4.0 (A6, consumer report): READ THE ARTIFACT AS JSON, NOT AS ONE SPELLING
# OF IT. Until now both reads were hardcoded to `"sha":"` — exactly the bytes
# our own run-gate.sh printf emits, with no space after the colon. A consumer
# whose project-owned gate writes the same fields pretty-printed
# (`{"sha": "…"}`, entirely valid JSON) got an EMPTY ARTIFACT_SHA and was
# blocked on every merge with `artifact sha: none` — a gate that passed,
# reported as stale, for a reason that has nothing to do with staleness. They
# carried a local widening for releases.
#
# REPLACING run-gate.sh WHOLESALE IS A SUPPORTED CONFIGURATION: the contract
# between the two halves is the `**Gate**` field plus the artifact FORMAT, not
# the script. So the reader must accept any valid JSON spelling of that format,
# not merely the one our writer happens to produce.
#
# THE `sed` IS WIDENED IN LOCKSTEP WITH THE `grep`, deliberately. Accepting
# `"sha": "` in the grep while stripping only `"sha":"` in the sed leaves a
# LEADING SPACE on the value — a sha that matches nothing, i.e. the same silent
# mismatch moved one step later and made harder to see. Both use the same
# tolerant pattern for that reason; do not "simplify" one of them.
ARTIFACT_SHA=$(grep -o '"sha"[[:space:]]*:[[:space:]]*"[^"]*"' "$ARTIFACT" | head -1 | sed 's/.*"sha"[[:space:]]*:[[:space:]]*"//;s/"$//')
ARTIFACT_TREE=$(grep -o '"tree"[[:space:]]*:[[:space:]]*"[^"]*"' "$ARTIFACT" | head -1 | sed 's/.*"tree"[[:space:]]*:[[:space:]]*"//;s/"$//')
HEAD_SHA=$(git -C "$CWD" rev-parse HEAD 2>/dev/null)
HEAD_TREE=$(git -C "$CWD" rev-parse 'HEAD^{tree}' 2>/dev/null)

# v2.1.3 fix round 1 (Critical 2 / penumbra #2c): accept either a sha match
# (the classic case: gate ran on this exact commit) or a tree match (the
# pre-commit-test.sh -> run-gate.sh chain: the gate ran against the INDEX
# just before `git commit`, so its "sha" is the PARENT commit but its "tree"
# is the tree the new commit just got). Both still gated by the freshness
# window below.
if [ -z "$ARTIFACT_SHA" ] || { [ "$ARTIFACT_SHA" != "$HEAD_SHA" ] && { [ -z "$ARTIFACT_TREE" ] || [ "$ARTIFACT_TREE" != "$HEAD_TREE" ]; }; }; then
  # v2.4.0 (A6, defect 1): the MESSAGE had drifted to the weaker half of the
  # check. The artifact matches by sha OR by tree, and the tree half is the one
  # that survives a squash -- a consumer measured a squash changing the sha and
  # leaving the tree byte-identical -- so a message naming only the sha sends
  # them to re-run a gate whose tree already matched. It also said "the current
  # head" without saying WHICH head, which is exactly the ambiguity that makes
  # gating `main` look like a remedy. The message is what a consumer acts on at
  # 2am; report both keys and name the head.
  {
    echo "BLOCKED: Gate artifact is stale — it matches this checkout by neither key."
    echo "  artifact sha:  ${ARTIFACT_SHA:-none}    HEAD:          $HEAD_SHA"
    echo "  artifact tree: ${ARTIFACT_TREE:-none}    HEAD^{tree}:   $HEAD_TREE"
    echo "Run 'bash hooks/run-gate.sh' on the head that is actually being MERGED — the PR branch tip, from a checkout of that branch — then merge from there. Gating some other head produces a fresh artifact that verifies nothing."
  } >&2
  exit 2
fi

# Freshness: artifact file mtime < 60 minutes (mtime avoids date-parsing portability issues)
ARTIFACT_EPOCH=$(stat -c %Y "$ARTIFACT" 2>/dev/null || stat -f %m "$ARTIFACT" 2>/dev/null || echo 0)
NOW_EPOCH=$(date +%s)
AGE=$((NOW_EPOCH - ARTIFACT_EPOCH))
if [ "$ARTIFACT_EPOCH" -eq 0 ] || [ "$AGE" -gt 3600 ]; then
  echo "BLOCKED: Gate artifact expired (${AGE}s old, max 3600s). Re-run 'bash hooks/run-gate.sh', then merge." >&2
  exit 2
fi

exit 0
