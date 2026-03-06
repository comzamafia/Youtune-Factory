# ─────────────────────────────────────────────────────────────────────
# Stage 1: Build — install Python deps in a virtual env
# ─────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps needed at build time (psycopg2 needs libpq-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─────────────────────────────────────────────────────────────────────
# Stage 2: Runtime — lean image with only what we need
# ─────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Runtime system deps: FFmpeg for video, libsndfile for audio, libpq for PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Create processing/output directories
RUN mkdir -p input/novels input/scripts \
    assets/images assets/music assets/fonts \
    processing/scenes processing/voice processing/subtitles \
    output/video output/thumbnail database

# Run as non-root for security
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app
USER appuser

# Railway injects PORT; fallback to 8000 for local docker run
ENV PORT=8000

EXPOSE $PORT

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:$PORT/api/v1/health || exit 1

CMD ["sh", "-c", "python main.py --host 0.0.0.0 --port $PORT"]

