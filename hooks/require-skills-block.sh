#!/usr/bin/env bash
# require-skills-block.sh -- RETIRED in v4.5.0; this no-op stub ships for ONE
# release and is deleted in the next one.
#
# v4.5.0 removed the "## Required Skills" spawn mandate: each agent opens its
# skills on demand from the `## Skills` table in its own definition. The
# registration left every templates/*/.claude/settings.json in v4.5.0, but a
# consumer whose settings.json still names this file (LOCAL_EDITED, keep-mine,
# or files and settings applied in the wrong order) runs it through the
# fail-closed 127 wrapper -- a deleted file would block EVERY Agent spawn. So
# the file stays, empty of rules: it reads stdin (no broken pipe) and allows.
# Precedent: block-bash-vcs.sh and require-teammate-report.sh, v2.1.
cat >/dev/null
exit 0
