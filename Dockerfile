FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# ffmpeg is required by moviepy for video encoding/decoding
# libcairo2 is required by CairoSVG/cairocffi used by asset generation
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer is cached separately from code changes
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application source (credentials and runtime dirs are excluded via .dockerignore)
COPY . .

# Pre-create runtime directories; actual data lives in mounted volumes
RUN mkdir -p database \
             temp/voiceover \
             temp/videos/final \
             temp/drive_clips \
             config/video \
             logs

# Run as a non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import core.database, pipeline.collector, pipeline.daily_runner; print('ok')" || exit 1

CMD ["python", "-u", "main.py"]
