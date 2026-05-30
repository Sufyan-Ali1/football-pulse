FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg is required by moviepy for video encoding/decoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer is cached separately from code changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application source (credentials and runtime dirs are excluded via .dockerignore)
COPY . .

# Pre-create runtime directories; actual data lives in mounted volumes
RUN mkdir -p database \
             temp/voiceover \
             temp/videos/final \
             temp/videos/clips \
             logs

# Run as a non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "main.py"]
