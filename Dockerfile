FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    UV_PYTHON=python3.11 \
    YT_DLP_NO_UPDATE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    python3.11 \
    python3.11-venv \
    libcudnn9-cuda-12 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies (layer cached unless pyproject.toml/uv.lock/README.md changes).
# --extra photo bundles gallery-dl so TikTok /photo/ posts work in-container.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra photo

# Pre-download Whisper model (~1.5 GB)
RUN .venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"

# Pre-download RapidOCR models (~66 MB, 63.3 MiB): the default classic set for English, Latin script
# and Chinese (PP-OCRv4/v3 mobile detection + recognition, plus the angle classifier), and
# the PP-OCRv6 small set (one detector + one recogniser for every v6 language). Other
# languages download on first use. These configs mirror ocr/model_sets.py. rapidocr 3.10
# loads models lazily, so constructing RapidOCR alone downloads nothing: the _load_*_model
# calls fetch them (and fail the build loudly if rapidocr renames them).
RUN .venv/bin/python -c "\
from rapidocr import LangRec as L, ModelType as M, OCRVersion as V, RapidOCR; \
cpu = {'EngineConfig.onnxruntime.use_cuda': False}; \
cfg = lambda d, r, v, t: {**cpu, 'Det.lang_type': d, 'Det.ocr_version': v, 'Det.model_type': t, 'Rec.lang_type': r, 'Rec.ocr_version': v, 'Rec.model_type': t}; \
engines = [RapidOCR(params=p) for p in (cfg(L.EN, L.EN, V.PPOCRV4, M.MOBILE), cfg(L.EN, L.LATIN, V.PPOCRV4, M.MOBILE), cfg(L.CH, L.CH, V.PPOCRV4, M.MOBILE), cfg('en', 'en', V.PPOCRV6, M.SMALL))]; \
[(e._load_det_model(), e._load_cls_model(), e._load_rec_model()) for e in engines]"

# Install application
COPY src/ ./src/
RUN uv sync --frozen --no-dev --extra photo \
    && uv cache clean

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["panoscribe"]
CMD ["--help"]
