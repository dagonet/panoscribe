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
