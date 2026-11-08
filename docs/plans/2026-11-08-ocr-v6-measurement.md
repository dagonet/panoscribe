# OCR v6 measurement report

Measurements for the newer-OCR-library work (`docs/plans/2026-11-08-ocr-newer-library-design.md`).
Each section records what the real engine does for every language value that
`_ISO_TO_LANGREC` can produce, so later sections can be compared against it.
All numbers come from `scripts/probe_ocr_languages.py` (CPU, real engine, one
rendered image per language).

## 3.8.1 baseline

Recorded on `feat/ocr-model-sets` with the unchanged lock: `importlib.metadata.version("rapidocr")` = **3.8.1**,
`python scripts/probe_ocr_languages.py` (no `--model-set`, because `ocr_model_set` does not exist yet).
This table defines "works today" and the classic detector per language (design D3, D3a).

14 distinct `LangRec` values are mapped. **3 start and 11 fail to start** on 3.8.1.

| language | ok | det model | rec model | probe text | recognised text | error |
|---|---|---|---|---|---|---|
| en | yes | en_PP-OCRv3_det_mobile.onnx | en_PP-OCRv4_rec_mobile.onnx | panoscribe 2026 | panoscribe 2026 | |
| latin | yes | en_PP-OCRv3_det_mobile.onnx | latin_PP-OCRv3_rec_mobile.onnx | Größe Straße 2026 | GröBe Straße 2026 | |
| eslav | no | | | Привет мир 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| cyrillic | no | | | Добър ден 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| ch | yes | ch_PP-OCRv4_det_mobile.onnx | ch_PP-OCRv4_rec_mobile.onnx | 你好世界 2026 | 你好世界2026 | |
| japan | no | | | こんにちは世界 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| korean | no | | | 안녕하세요 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| arabic | no | | | مرحبا بالعالم 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| devanagari | no | | | नमस्ते दुनिया 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| th | no | | | สวัสดีชาวโลก 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| el | no | | | Καλημέρα κόσμε 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| ta | no | | | வணக்கம் உலகம் 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| te | no | | | హలో ప్రపంచం 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |
| ka | no | | | ನಮಸ್ಕಾರ ಜಗತ್ತು 2026 | | PanoScribeError: Failed to initialize RapidOCR on cpu: Invalid OCR configuration. |

Observations:

- **Why 11 fail.** rapidocr's own log for each failure reads `Unsupported configuration: ... ocr_version = PP-OCRv4, task_type = det, lang_type = <language>`.
  `RapidOCREngine._ensure_loaded` sets `Det.lang_type` to the recognition language for every
  value except `latin` (which uses `en`). The 3.8.1 detector registry only has `ch`, `en` and `multi`, so any
  other value is rejected while building the *detector*, before a recognition model is chosen. The failures are
  therefore all in detection; recognition support for those languages is not measured here.
- `ka` is `LangRec.KA`, which is **Kannada** in rapidocr (its font is `kannada.ttf`), while panoscribe's ISO `ka` (Georgian)
  maps to it. The probe text for `ka` is therefore Kannada. The ISO mapping looks wrong; it is not changed here.
- `latin` read `ß` as `B` (`GröBe`); `ch` dropped the space before the year. Both are recorded as observed, not as failures.
- Fonts for rendering come from rapidocr's own `fonts:` registry (`rapidocr.utils.vis_res.get_font_path`); every language had one,
  so no row is "no font". Detection and recognition files are read from rapidocr's `Using <path>.onnx` log lines.

## Classic and v6 on rapidocr 3.10

Recorded on `feat/ocr-model-sets` after the bump: `importlib.metadata.version("rapidocr")` = **3.10.0**
(onnxruntime-gpu 1.24.4, CPU provider; no onnxruntime floor change was needed),
`python scripts/probe_ocr_languages.py --model-set classic` and `--model-set v6`.
The probe passes the `LangRec` values, not ISO codes, so under `v6` only `en`, `ch` and `japan` have a
PP-OCRv6 code; the other values take the automatic per-language fallback to the classic models (design D3).
The ISO-coded v6 path (`de`, `fr`, ...) is shown in the second half of this section.

**All 14 values start under both sets** (3.8.1 baseline: 3 of 14).

What changed against the 3.8.1 baseline, and why:

- **11 languages fixed.** `_ensure_loaded` used to pass the recognition language as `Det.lang_type`; the detector
  registry only has `ch`, `en` and `multi`. The detector is now chosen on its own: `en` for `en`/`latin`, `ch` for
  `ch`/`chinese_cht`/`japan`, `multi` for every other script.
- **`eslav`, `th`, `el`** use PP-OCRv5 mobile recognition (PP-OCRv4 has no route for them); detection stays PP-OCRv4/v3 `multi`.
- **Arabic needs `python-bidi`.** rapidocr 3.10 refuses to build an Arabic recogniser without its optional `rtl` extra
  (`ModuleNotFoundError: RTL recognition requires the optional dependency 'python-bidi'`), which the first 3.10 probe run hit.
  `pyproject.toml` therefore depends on `rapidocr[rtl]` (adds `python-bidi` 0.6.12 to the lock).
- **`en`, `latin`, `ch` are model-for-model identical to the 3.8.1 baseline** (same det and rec files in the classic table).
- **`ka` fixed in the ISO map.** `LangRec.KA` is Kannada; the ISO code `ka` (Georgian) no longer maps to it and `kn` (Kannada) does.
  The probe text for the `ka` value is still Kannada, which is what that model reads.

### rapidocr 3.10.0, `--model-set classic`

| language | ok | det model | rec model | probe text | recognised text | error |
|---|---|---|---|---|---|---|
| en | yes | en_PP-OCRv3_det_mobile.onnx | en_PP-OCRv4_rec_mobile.onnx | panoscribe 2026 | panoscribe 2026 | |
| latin | yes | en_PP-OCRv3_det_mobile.onnx | latin_PP-OCRv3_rec_mobile.onnx | Größe Straße 2026 | GröBe Straße 2026 | |
| eslav | yes | multi_PP-OCRv3_det_mobile.onnx | eslav_PP-OCRv5_rec_mobile.onnx | Привет мир 2026 | Привет м мир 2026 | |
| cyrillic | yes | multi_PP-OCRv3_det_mobile.onnx | cyrillic_PP-OCRv3_rec_mobile.onnx | Добър ден 2026 | Доърден 2о26 | |
| ch | yes | ch_PP-OCRv4_det_mobile.onnx | ch_PP-OCRv4_rec_mobile.onnx | 你好世界 2026 | 你好世界2026 | |
| japan | yes | ch_PP-OCRv4_det_mobile.onnx | japan_PP-OCRv4_rec_mobile.onnx | こんにちは世界 2026 | こんにちは世界 2026 | |
| korean | yes | multi_PP-OCRv3_det_mobile.onnx | korean_PP-OCRv4_rec_mobile.onnx | 안녕하세요 2026 | 2026 | |
| arabic | yes | multi_PP-OCRv3_det_mobile.onnx | arabic_PP-OCRv4_rec_mobile.onnx | مرحبا بالعالم 2026 | 20 26 لاعلابابت اح | |
| devanagari | yes | multi_PP-OCRv3_det_mobile.onnx | devanagari_PP-OCRv4_rec_mobile.onnx | नमस्ते दुनिया 2026 | Phh | |
| th | yes | multi_PP-OCRv3_det_mobile.onnx | th_PP-OCRv5_rec_mobile.onnx | สวัสดีชาวโลก 2026 | | |
| el | yes | multi_PP-OCRv3_det_mobile.onnx | el_PP-OCRv5_rec_mobile.onnx | Καλημέρα κόσμε 2026 | Καλημέρα κόσμε 2026 | |
| ta | yes | multi_PP-OCRv3_det_mobile.onnx | ta_PP-OCRv4_rec_mobile.onnx | வணக்கம் உலகம் 2026 | வண ககம் உல் லகம்ஜ 2026 | |
| te | yes | multi_PP-OCRv3_det_mobile.onnx | te_PP-OCRv4_rec_mobile.onnx | హలో ప్రపంచం 2026 | హలో Ogం&థి | |
| ka | yes | multi_PP-OCRv3_det_mobile.onnx | ka_PP-OCRv4_rec_mobile.onnx | ನಮಸ್ಕಾರ ಜಗತ್ತು 2026 | ಜಗತು 2026 | |

### rapidocr 3.10.0, `--model-set v6`

| language | ok | det model | rec model | probe text | recognised text | error |
|---|---|---|---|---|---|---|
| en | yes | PP-OCRv6_det_small.onnx | PP-OCRv6_rec_small.onnx | panoscribe 2026 | panoscribe 2026 | |
| latin | yes | en_PP-OCRv3_det_mobile.onnx | latin_PP-OCRv3_rec_mobile.onnx | Größe Straße 2026 | GröBe Straße 2026 | |
| eslav | yes | multi_PP-OCRv3_det_mobile.onnx | eslav_PP-OCRv5_rec_mobile.onnx | Привет мир 2026 | Привет м мир 2026 | |
| cyrillic | yes | multi_PP-OCRv3_det_mobile.onnx | cyrillic_PP-OCRv3_rec_mobile.onnx | Добър ден 2026 | Доърден 2о26 | |
| ch | yes | PP-OCRv6_det_small.onnx | PP-OCRv6_rec_small.onnx | 你好世界 2026 | 你好世界 2026 | |
| japan | yes | PP-OCRv6_det_small.onnx | PP-OCRv6_rec_small.onnx | こんにちは世界 2026 | こんにちは世界 2026 | |
| korean | yes | multi_PP-OCRv3_det_mobile.onnx | korean_PP-OCRv4_rec_mobile.onnx | 안녕하세요 2026 | 2026 | |
| arabic | yes | multi_PP-OCRv3_det_mobile.onnx | arabic_PP-OCRv4_rec_mobile.onnx | مرحبا بالعالم 2026 | 20 26 لاعلابابت اح | |
| devanagari | yes | multi_PP-OCRv3_det_mobile.onnx | devanagari_PP-OCRv4_rec_mobile.onnx | नमस्ते दुनिया 2026 | Phh | |
| th | yes | multi_PP-OCRv3_det_mobile.onnx | th_PP-OCRv5_rec_mobile.onnx | สวัสดีชาวโลก 2026 | | |
| el | yes | multi_PP-OCRv3_det_mobile.onnx | el_PP-OCRv5_rec_mobile.onnx | Καλημέρα κόσμε 2026 | Καλημέρα κόσμε 2026 | |
| ta | yes | multi_PP-OCRv3_det_mobile.onnx | ta_PP-OCRv4_rec_mobile.onnx | வணக்கம் உலகம் 2026 | வண ககம் உல் லகம்ஜ 2026 | |
| te | yes | multi_PP-OCRv3_det_mobile.onnx | te_PP-OCRv4_rec_mobile.onnx | హలో ప్రపంచం 2026 | హలో Ogం&థి | |
| ka | yes | multi_PP-OCRv3_det_mobile.onnx | ka_PP-OCRv4_rec_mobile.onnx | ನಮಸ್ಕಾರ ಜಗತ್ತು 2026 | ಜಗತು 2026 | |

In the v6 table, 11 of 14 values fell back to the classic models (`en`, `ch` and `japan` use PP-OCRv6 small; `latin` has no v6
code, which is the Review Focus 1 case). The remaining rows are identical to the classic table by design (D3).

### ISO-coded languages (what a `de`/`fr`/... configuration or auto-detection sends)

One synthetic line per language, real engine on CPU, rapidocr 3.10.0 (scratch check, not part of the probe script):

| ocr_language | set | det model | rec model | recognised | rendered |
|---|---|---|---|---|---|
| de | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | GröBe Straße über 2026 | Größe Straße über 2026 |
| de | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Größe Straße über 2026 | Größe Straße über 2026 |
| fr | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | 'école  Noél 2026 | Élève à l'école Noël 2026 |
| fr | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Élève à e à l'école Noël 1 2026 | Élève à l'école Noël 2026 |
| es | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | El nino comio pina   2026 | El niño comió piña 2026 |
| es | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | El niño comió piña 2026 | El niño comió piña 2026 |
| pt | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | 2026 | Ação e informação 2026 |
| pt | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Ação e  informação 2026 | Ação e informação 2026 |
| it | classic | en_PP-OCRv3_det_mobile | latin_PP-OCRv3_rec_mobile | Perché  la citta  2026 | Perché la città 2026 |
| it | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Perché la città 2026 | Perché la città 2026 |
| en | classic | en_PP-OCRv3_det_mobile | en_PP-OCRv4_rec_mobile | Hello world 2026 | Hello world 2026 |
| en | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | Hello world 2026 | Hello world 2026 |
| zh | classic | ch_PP-OCRv4_det_mobile | ch_PP-OCRv4_rec_mobile | 你好世界2026 | 你好世界 2026 |
| zh | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | 你好世界 2026 | 你好世界 2026 |
| ja | classic | ch_PP-OCRv4_det_mobile | japan_PP-OCRv4_rec_mobile | こんにちは世界 2026 | こんにちは世界 2026 |
| ja | v6 | PP-OCRv6_det_small | PP-OCRv6_rec_small | こんにちは世界 2026 | こんにちは世界 2026 |

These are single synthetic lines (one font, one size), a start-up and sanity check only. They say nothing about quality on
real clips; that is the D5 measurement.
Rows where the recognised text is empty or far from the probe text (`th`, `devanagari`, `te`, `ka`, `korean` without its Hangul) show the
engine starts but that the synthetic line is not read; they are recorded as observed, not as failures of this change.
