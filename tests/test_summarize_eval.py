"""Pure-function tests for scripts/summarize_eval.py -- no network, no OCR engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.summarize_eval import LangSummary, load_records, main, summarize, verdict


def _record(
    *,
    clip: str,
    language: str,
    model_set: str,
    matched: int,
    expected: int,
    segments: int = 10,
    unmatched: int = 0,
    raw_recall: float | None = None,
) -> dict:
    """Build an eval_ocr.py --junk result record with `matched` of `expected` found."""
    per_text = [{"expected_text": f"t{i}", "matched": i < matched} for i in range(expected)]
    recall = matched / expected
    return {
        "clip": clip,
        "language": language,
        "ocr_model_set": model_set,
        "rapidocr_version": "3.10.0",
        "recall": recall,
        "per_text_results": per_text,
        "junk": {
            "raw": {"retained_overlay_recall": recall if raw_recall is None else raw_recall},
            "post_dedup": {
                "total_segments": segments,
                "unmatched_count": unmatched,
                "unmatched_rate": unmatched / segments,
            },
        },
    }


def _summary(
    *, expected: int = 100, matched: int, segments: int = 100, unmatched: int = 0
) -> LangSummary:
    return LangSummary(
        clips=1,
        expected=expected,
        matched=matched,
        recall=matched / expected,
        segments=segments,
        unmatched=unmatched,
        unmatched_rate=unmatched / segments,
        raw_recall=matched / expected,
    )


_LANGS = ("en", "de", "fr", "es", "pt")


def _equal_summaries(model_set: str, *, matched: int = 80) -> dict:
    return {(lang, model_set): _summary(matched=matched) for lang in _LANGS}


def test_summarize_pools_by_expected_texts() -> None:
    records = [
        _record(clip="a", language="en", model_set="classic", matched=1, expected=2),
        _record(clip="b", language="en", model_set="classic", matched=3, expected=8),
    ]

    summary = summarize(records)[("en", "classic")]

    assert summary.clips == 2
    assert summary.expected == 10
    assert summary.matched == 4
    assert summary.recall == pytest.approx(0.4)  # pooled, not mean-of-clips (0.4375)


def test_summarize_keys_by_language_and_model_set() -> None:
    records = [
        _record(clip="a", language="de", model_set="classic", matched=1, expected=2),
        _record(clip="a", language="de", model_set="v6", matched=2, expected=2),
        _record(clip="b", language="fr", model_set="v6", matched=1, expected=2),
    ]

    assert set(summarize(records)) == {("de", "classic"), ("de", "v6"), ("fr", "v6")}


def test_summarize_pools_unmatched_rate_over_segments() -> None:
    records = [
        _record(
            clip="a", language="en", model_set="v6", matched=1, expected=1, segments=4, unmatched=1
        ),
        _record(
            clip="b", language="en", model_set="v6", matched=1, expected=1, segments=36, unmatched=9
        ),
    ]

    summary = summarize(records)[("en", "v6")]

    assert summary.segments == 40
    assert summary.unmatched == 10
    assert summary.unmatched_rate == pytest.approx(0.25)  # not (0.25 + 0.25) / 2 pooled by clip


def test_summarize_raw_recall_weighted_by_expected() -> None:
    records = [
        _record(clip="a", language="en", model_set="v6", matched=1, expected=2, raw_recall=1.0),
        _record(clip="b", language="en", model_set="v6", matched=2, expected=8, raw_recall=0.5),
    ]

    summary = summarize(records)[("en", "v6")]

    assert summary.raw_recall == pytest.approx((1.0 * 2 + 0.5 * 8) / 10)


def test_summarize_ignores_non_required_entries() -> None:
    record = _record(clip="a", language="en", model_set="v6", matched=1, expected=2)
    record["per_text_results"].append(
        {"expected_text": "chrome", "matched": False, "required": False}
    )

    summary = summarize([record])[("en", "v6")]

    assert (summary.expected, summary.matched) == (2, 1)


def test_summarize_requires_junk_metrics() -> None:
    record = _record(clip="a", language="en", model_set="v6", matched=1, expected=1)
    del record["junk"]

    with pytest.raises(ValueError, match="--junk"):
        summarize([record])


def test_verdict_passes_when_v6_is_equal_or_better() -> None:
    summaries = _equal_summaries("classic")
    summaries.update(_equal_summaries("v6", matched=81))
    summaries[("pt", "v6")] = _summary(matched=80, unmatched=2)  # junk +0.02 is on the boundary

    ok, reasons = verdict(summaries)

    assert ok is True
    assert reasons == []


def test_verdict_passes_within_margin() -> None:
    summaries = _equal_summaries("classic")
    summaries.update(_equal_summaries("v6", matched=82))
    summaries[("de", "v6")] = _summary(matched=79)  # -0.01 on de, offset by gains elsewhere

    ok, reasons = verdict(summaries)

    assert ok is True
    assert reasons == []


def test_verdict_fails_when_one_language_drops() -> None:
    summaries = _equal_summaries("classic")
    summaries.update(_equal_summaries("v6", matched=84))  # big gains elsewhere
    summaries[("de", "v6")] = _summary(matched=77)  # de drops by 0.03

    ok, reasons = verdict(summaries)

    assert ok is False
    assert len(reasons) == 1
    assert "de" in reasons[0]


def test_verdict_fails_when_junk_rises_beyond_margin() -> None:
    summaries = _equal_summaries("classic")
    summaries.update(_equal_summaries("v6", matched=85))
    summaries[("fr", "v6")] = _summary(matched=85, unmatched=3)  # unmatched_rate 0.03 > 0.00 + 0.02

    ok, reasons = verdict(summaries)

    assert ok is False
    assert len(reasons) == 1
    assert "fr" in reasons[0]
    assert "unmatched" in reasons[0]


def test_verdict_fails_when_overall_recall_lower() -> None:
    summaries = _equal_summaries("classic")
    summaries.update(_equal_summaries("v6", matched=79))  # every language -0.01, inside margin

    ok, reasons = verdict(summaries)

    assert ok is False
    assert len(reasons) == 1
    assert "overall" in reasons[0]


def test_verdict_fails_when_a_language_is_missing_a_set() -> None:
    summaries = _equal_summaries("classic")
    summaries.update(_equal_summaries("v6"))
    del summaries[("es", "v6")]

    ok, reasons = verdict(summaries)

    assert ok is False
    assert any("es" in r for r in reasons)


def test_summarize_records_the_clip_names() -> None:
    records = [
        _record(clip="a", language="de", model_set="v6", matched=1, expected=2),
        _record(clip="b", language="de", model_set="v6", matched=1, expected=2),
    ]

    assert summarize(records)[("de", "v6")].clip_names == frozenset({"a", "b"})


def test_verdict_fails_when_a_language_has_different_clips_per_set() -> None:
    records = [
        _record(clip="a", language="de", model_set="classic", matched=1, expected=2),
        _record(clip="b", language="de", model_set="classic", matched=1, expected=2),
        _record(clip="a", language="de", model_set="v6", matched=2, expected=2),  # b.v6 missing
    ]
    summaries = summarize(records)

    ok, reasons = verdict(summaries, languages=("de",))

    assert ok is False
    assert len(reasons) == 1
    assert "de" in reasons[0]
    assert "only in classic: b" in reasons[0]


def test_verdict_passes_when_both_sets_cover_the_same_clips() -> None:
    records = [
        _record(clip=clip, language="de", model_set=model_set, matched=1, expected=2)
        for clip in ("a", "b")
        for model_set in ("classic", "v6")
    ]

    ok, reasons = verdict(summarize(records), languages=("de",))

    assert ok is True
    assert reasons == []


def test_verdict_honours_custom_margin() -> None:
    summaries = _equal_summaries("classic")
    summaries.update(_equal_summaries("v6", matched=84))
    summaries[("de", "v6")] = _summary(matched=77)

    ok, _ = verdict(summaries, margin=0.05)

    assert ok is True


def test_cli_prints_tables_and_verdict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for model_set in ("classic", "v6"):
        record = _record(clip="clip-a", language="de", model_set=model_set, matched=1, expected=2)
        (tmp_path / f"clip-a.{model_set}.json").write_text(json.dumps(record), encoding="utf-8")

    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out

    assert "clip-a" in out
    assert "| de | classic |" in out
    assert "Verdict" in out


def test_load_records_reads_every_json_file(tmp_path: Path) -> None:
    record = _record(clip="x", language="en", model_set="v6", matched=1, expected=1)
    (tmp_path / "a.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    assert len(load_records(tmp_path)) == 2
