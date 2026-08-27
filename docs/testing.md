# Testing

## Default suite

```bash
uv run pytest
```

Runs the full mocked unit/component suite. Three pytest markers are excluded
by default via `[tool.pytest.ini_options] addopts` in `pyproject.toml`:

| Marker | What it needs | Why excluded by default |
|---|---|---|
| `integration` | A live local Ollama server | Not available in CI or most dev machines |
| `eval` | Eval fixture files (media + ground truth) fetched separately | Large, gitignored assets |
| `slow` | Real model inference | Downloads/loads a real model; too slow for every PR |

## Real-Whisper end-to-end test (`slow`)

`tests/test_e2e_whisper.py` drives a real `faster-whisper` transcription
(CPU, `tiny` model) over a committed real-speech clip
(`tests/fixtures/e2e/quick_brown_fox.wav` — see the README next to it for
provenance). It is the only test in the suite that exercises actual model
loading and audio decoding rather than a mock.

Run it locally with:

```bash
uv run pytest -m slow -v
```

First run downloads the `tiny` Whisper model (~75 MB) to the local
Hugging Face cache; subsequent runs reuse it.

In CI, this test runs in the opt-in `e2e-whisper` job
(`.github/workflows/ci.yml`), triggered nightly (`schedule`) and via manual
`workflow_dispatch` — never on every push/PR, since the per-PR `test` job is
the wrong host for a job that downloads model weights.
