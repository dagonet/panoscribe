#!/usr/bin/env python3
"""Summarise ``scripts/eval_ocr.py --junk`` results per language and model set.

Usage
-----
    python scripts/summarize_eval.py RESULTS_DIR

``RESULTS_DIR`` holds one ``eval_ocr.py --junk --output FILE.json`` result per
(clip, model set). Each record carries ``ocr_model_set``, ``language``, ``clip``,
``per_text_results`` and ``junk`` (see ``panoscribe.eval.models.EvalResult``).

Prints Markdown tables (per clip, per language) and the verdict of the D5
decision rule from ``docs/plans/2026-11-08-ocr-newer-library-design.md``:
``v6`` becomes the default iff, for each of EN/DE/FR/ES/PT (pooled over that
language's clips), recall(v6) >= recall(classic) - margin and
unmatched_rate(v6) <= unmatched_rate(classic) + margin, and the overall pooled
recall of v6 is not lower than classic's.

Recall is pooled over all expected texts of the language's clips (not averaged
per clip), and the unmatched rate over all post-dedup segments.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_LANGUAGES: tuple[str, ...] = ("en", "de", "fr", "es", "pt")
DEFAULT_MARGIN = 0.02
_EPS = 1e-9
_BASELINE = "classic"
_CANDIDATE = "v6"


@dataclass(frozen=True)
class LangSummary:
    """Pooled results for one (language, model set)."""

    clips: int
    expected: int
    matched: int
    recall: float
    """``matched / expected``, pooled over every expected text of every clip."""
    segments: int
    unmatched: int
    unmatched_rate: float
    """``unmatched / segments`` after the full filter chain (``junk.post_dedup``)."""
    raw_recall: float
    """``junk.raw.retained_overlay_recall`` (before the filters), weighted by expected."""
    clip_names: frozenset[str] = frozenset()
    """Names of the pooled clips; ``verdict`` requires both sets to cover the same clips."""


def _field(record: dict, key: str) -> object:
    if key not in record or record[key] is None:
        raise ValueError(f"record for clip {record.get('clip')!r} has no {key!r}")
    return record[key]


def _counts(record: dict) -> tuple[int, int]:
    """Return ``(expected, matched)`` over the required ground-truth texts."""
    entries = [e for e in record.get("per_text_results", []) if e.get("required", True)]
    return len(entries), sum(1 for e in entries if e["matched"])


def _junk_stage(record: dict, stage: str) -> dict:
    junk = record.get("junk")
    if not junk or stage not in junk:
        raise ValueError(
            f"record for clip {record.get('clip')!r} has no junk stage {stage!r}; "
            "rerun scripts/eval_ocr.py with --junk"
        )
    return junk[stage]


def summarize(records: list[dict]) -> dict[tuple[str, str], LangSummary]:
    """Pool ``records`` by ``(language, ocr_model_set)``."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        key = (str(_field(record, "language")), str(_field(record, "ocr_model_set")))
        groups.setdefault(key, []).append(record)

    summaries: dict[tuple[str, str], LangSummary] = {}
    for key, group in groups.items():
        expected = matched = segments = unmatched = 0
        raw_weighted = 0.0
        for record in group:
            exp, mat = _counts(record)
            expected += exp
            matched += mat
            post_dedup = _junk_stage(record, "post_dedup")
            segments += int(post_dedup["total_segments"])
            unmatched += int(post_dedup["unmatched_count"])
            raw_weighted += float(_junk_stage(record, "raw")["retained_overlay_recall"]) * exp
        summaries[key] = LangSummary(
            clips=len(group),
            expected=expected,
            matched=matched,
            recall=matched / expected if expected else 1.0,
            segments=segments,
            unmatched=unmatched,
            unmatched_rate=unmatched / segments if segments else 0.0,
            raw_recall=raw_weighted / expected if expected else 1.0,
            clip_names=frozenset(str(record.get("clip")) for record in group),
        )
    return summaries


def _overall_recall(summaries: dict[tuple[str, str], LangSummary], model_set: str) -> float | None:
    rows = [s for (_, ms), s in summaries.items() if ms == model_set]
    expected = sum(s.expected for s in rows)
    if not expected:
        return None
    return sum(s.matched for s in rows) / expected


def verdict(
    summaries: dict[tuple[str, str], LangSummary],
    languages: Sequence[str] = DEFAULT_LANGUAGES,
    margin: float = DEFAULT_MARGIN,
) -> tuple[bool, list[str]]:
    """Apply the D5 rule; return ``(v6_becomes_default, reasons_for_failure)``."""
    reasons: list[str] = []
    for lang in languages:
        classic = summaries.get((lang, _BASELINE))
        v6 = summaries.get((lang, _CANDIDATE))
        if classic is None or v6 is None:
            missing = [ms for ms, s in ((_BASELINE, classic), (_CANDIDATE, v6)) if s is None]
            reasons.append(f"{lang}: no results for {', '.join(missing)}")
            continue
        if classic.clip_names != v6.clip_names:
            # A missing result JSON would silently change one set's pool; refuse to compare.
            only_classic = ", ".join(sorted(classic.clip_names - v6.clip_names)) or "-"
            only_v6 = ", ".join(sorted(v6.clip_names - classic.clip_names)) or "-"
            reasons.append(
                f"{lang}: clip sets differ (only in classic: {only_classic}; only in v6: {only_v6})"
            )
            continue
        if v6.recall < classic.recall - margin - _EPS:
            reasons.append(
                f"{lang}: recall v6 {v6.recall:.3f} < classic {classic.recall:.3f} - {margin:.2f}"
            )
        if v6.unmatched_rate > classic.unmatched_rate + margin + _EPS:
            reasons.append(
                f"{lang}: unmatched_rate v6 {v6.unmatched_rate:.3f} > "
                f"classic {classic.unmatched_rate:.3f} + {margin:.2f}"
            )

    overall_classic = _overall_recall(summaries, _BASELINE)
    overall_v6 = _overall_recall(summaries, _CANDIDATE)
    if (
        overall_classic is not None
        and overall_v6 is not None
        and overall_v6 < overall_classic - _EPS
    ):
        reasons.append(
            f"overall: pooled recall v6 {overall_v6:.3f} < classic {overall_classic:.3f}"
        )
    return not reasons, reasons


def load_records(results_dir: Path) -> list[dict]:
    """Read every ``*.json`` result file in ``results_dir``."""
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(results_dir.glob("*.json"))
    ]


def _clip_table(records: list[dict]) -> list[str]:
    lines = [
        "| clip | language | model set | recall | raw recall | unmatched rate | segments |",
        "|---|---|---|---|---|---|---|",
    ]
    ordered = sorted(
        records,
        key=lambda r: (str(r.get("language")), str(r.get("clip")), str(r.get("ocr_model_set"))),
    )
    for record in ordered:
        s = next(iter(summarize([record]).values()))
        lines.append(
            f"| {record.get('clip')} | {record['language']} | {record['ocr_model_set']} | "
            f"{s.matched}/{s.expected} = {s.recall:.3f} | {s.raw_recall:.3f} | "
            f"{s.unmatched_rate:.3f} | {s.segments} |"
        )
    return lines


def _language_table(summaries: dict[tuple[str, str], LangSummary]) -> list[str]:
    lines = [
        "| language | model set | clips | recall | raw recall | unmatched rate | segments |",
        "|---|---|---|---|---|---|---|",
    ]
    for (lang, model_set), s in sorted(summaries.items()):
        lines.append(
            f"| {lang} | {model_set} | {s.clips} | "
            f"{s.matched}/{s.expected} = {s.recall:.3f} | {s.raw_recall:.3f} | "
            f"{s.unmatched_rate:.3f} | {s.segments} |"
        )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise eval_ocr.py --junk results.")
    parser.add_argument("results_dir", type=Path, help="Directory of eval_ocr.py result JSONs.")
    args = parser.parse_args(argv)

    records = load_records(args.results_dir)
    if not records:
        parser.error(f"No *.json result files in {args.results_dir}")
    summaries = summarize(records)
    ok, reasons = verdict(summaries)

    out = ["## Per clip", "", *_clip_table(records), "", "## Per language", ""]
    out += _language_table(summaries)
    out += ["", "## Verdict", ""]
    if ok:
        out.append("PASS: v6 meets the D5 rule and may become the default.")
    else:
        out.append("FAIL: classic stays the default.")
        out += [f"- {reason}" for reason in reasons]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
